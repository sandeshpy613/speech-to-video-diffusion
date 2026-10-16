let currentLang = 'english';
let isRecording = false;
let mediaRecorder;
let audioChunks = [];

function selectLang(lang) {
    currentLang = lang;
    document.querySelectorAll('.lang-pill').forEach(el => el.classList.remove('active'));
    const activePill = document.querySelector(`.lang-pill[data-lang="${lang}"]`);
    if(activePill) activePill.classList.add('active');
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
        mediaRecorder.onstop = async () => {
            const blob = new Blob(audioChunks, { type: 'audio/wav' });
            await uploadVoice(blob);
        };
        mediaRecorder.start();
        isRecording = true;
        document.getElementById('recordBtn').classList.add('recording');
    } catch(err) { alert("Mic error: " + err); }
}

function stopRecording() {
    mediaRecorder.stop();
    isRecording = false;
    document.getElementById('recordBtn').classList.remove('recording');
}

async function uploadVoice(blob) {
    const fd = new FormData();
    fd.append('audio', blob);
    fd.append('language', currentLang);
    const res = await fetch('/api/process-voice', { method: 'POST', body: fd });
    const data = await res.json();
    if(data.success) {
        document.getElementById('mainInput').value = data.text;
        document.getElementById('audioPath').value = data.audio_path;
    }
}

async function generateVideo() {
    const text = document.getElementById('mainInput').value;
    const audio_path = document.getElementById('audioPath').value;
    
    // Show Loading Area
    document.getElementById('loadingArea').style.display = 'block';
    document.getElementById('statusMsg').innerText = "Requesting generation...";

    const res = await fetch('/api/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ text, language: currentLang, audio_path })
    });
    const data = await res.json();
    if(data.success) pollStatus(data.job_id);
}

// --- Button Activation ---
document.addEventListener('DOMContentLoaded', () => {
    const recordBtn = document.getElementById('recordBtn');
    if(recordBtn) {
        recordBtn.addEventListener('click', () => {
            if(!isRecording) startRecording();
            else stopRecording();
        });
    }

    const uploadBtn = document.getElementById('uploadBtn');
    if(uploadBtn) {
        uploadBtn.addEventListener('click', () => {
            document.getElementById('audioFileInput').click();
        });
    }

    const fileInput = document.getElementById('audioFileInput');
    if(fileInput) {
        fileInput.addEventListener('change', (e) => {
            if(e.target.files[0]) uploadVoice(e.target.files[0]);
        });
    }
});

function pollStatus(jobId) {
    const interval = setInterval(async () => {
        const res = await fetch(`/api/status/${jobId}`);
        const data = await res.json();
        const statusEl = document.getElementById('statusMsg');
        if(data.status === 'completed') {
            clearInterval(interval);
            window.location.reload();
        } else {
            statusEl.innerText = data.progress || "Processing...";
        }
    }, 5000);
}

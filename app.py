import os
import sys
import io
import uuid
import logging
import threading
import gc
import torch
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from diffusers import DiffusionPipeline, DPMSolverMultistepScheduler
from diffusers.utils import export_to_video
from moviepy.editor import VideoFileClip, concatenate_videoclips, AudioFileClip, afx, concatenate_audioclips, CompositeAudioClip
from moviepy.audio.AudioClip import AudioArrayClip
import numpy as np
from gtts import gTTS
import speech_recognition as sr
from deep_translator import GoogleTranslator

# --- SYSTEM STABILITY: FORCE UTF-8 ---
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# --- CONFIGURATION ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'titan-secret-key-3000'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_FOLDER'] = 'generated_videos'

# Ensure folders exist
for folder in [app.config['UPLOAD_FOLDER'], app.config['GENERATED_FOLDER']]:
    if not os.path.exists(folder):
        os.makedirs(folder)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler("app.log", encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- DATABASE MODELS ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password = db.Column(db.String(60), nullable=False)

class GeneratedVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    input_text = db.Column(db.String(255))
    english_word = db.Column(db.String(255))
    video_path = db.Column(db.String(255))
    unique_id = db.Column(db.String(100), unique=True)
    language = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- AI ENGINE INITIALIZATION ---
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32
logger.info(f"TITAN ENGINE: Using device {device.upper()}")

pipe = None
def load_ai_model():
    global pipe
    try:
        logger.info("Loading Zeroscope V2 (High Quality)...")
        pipe = DiffusionPipeline.from_pretrained(
            "cerspense/zeroscope_v2_576w", 
            torch_dtype=dtype, 
            use_safetensors=False,
            resume_download=True
        )
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
        pipe.to(device)
        if device == "cpu":
            pipe.enable_attention_slicing()
        else:
            pipe.enable_model_cpu_offload()
        logger.info("AI Model Loaded Successfully!")
    except Exception as e:
        logger.error(f"Model Load Failed: {e}")

threading.Thread(target=load_ai_model).start()

# --- SHARED STATE ---
local_jobs = {}

# --- CORE LOGIC: PAPER IMPLEMENTATION ---
def generate_story_logic_internal(text, lang, job_id, user_id, original_audio_path=None):
    """Implementation of Research Paper Workflow: 8 Scenes + Auditory Looping"""
    # Use English for the AI drawing prompts
    if lang == 'kannada':
        visual_word = GoogleTranslator(source='kn', target='en').translate(text)
    else:
        visual_word = text
        
    logger.info(f"[{job_id}] Paper-Based Generation. Voice: {text}, Visuals: {visual_word}")
    
    # 1. Structured Prompt Generation (High Detail Actions)
    quality_tags = "masterpiece, high detail, 8k, highly realistic, cinematic lighting"
    narrative_prompts = [
        f"A simple view of {visual_word} standing still, {quality_tags}, clear background.",
        f"{visual_word} moving slowly towards the camera, {quality_tags}.",
        f"{visual_word} jumping up and down, simple motion, {quality_tags}.",
        f"{visual_word} moving slowly to the left side, {quality_tags}.",
        f"{visual_word} moving slowly to the right side, {quality_tags}.",
        f"A close-up view of {visual_word}, very clear details, {quality_tags}.",
        f"{visual_word} spinning around slowly in place, {quality_tags}.",
        f"A final clear view of {visual_word} in bright lighting, {quality_tags}."
    ]

    video_files = []
    try:
        for i, prompt in enumerate(narrative_prompts):
            local_jobs[job_id]['progress'] = f"Generating Scene {i+1}/8..."
            now = datetime.now().strftime("%H:%M:%S")
            print(f"[{now}] >>> Processing Scene {i+1}/8: {prompt[:50]}...", flush=True)
            
            # High Quality Inference (25 steps for clarity)
            frames = pipe(prompt, num_inference_steps=25, height=320, width=576, num_frames=20, guidance_scale=12.5).frames[0]
            
            # Simple Progress Bar
            filled = int((i + 1) / 8 * 20)
            bar = "#" * filled + "-" * (20 - filled)
            print(f"Overall Progress: [{bar}] {int((i+1)/8*100)}%", flush=True)
            
            fname = f"tmp_{job_id}_{i}.mp4"
            export_to_video(frames, fname, fps=8)
            video_files.append(fname)
            gc.collect()

        # 2. Scene Stitching
        local_jobs[job_id]['progress'] = "Stitching scenes together..."
        clips = [VideoFileClip(f) for f in video_files]
        final_video = concatenate_videoclips(clips, method="compose")
        
        # 3. AUDITORY FEEDBACK LOOP (Research Paper Feature)
        try:
            # A. Determine the loop source (Mic Recording takes priority over AI TTS)
            if original_audio_path and os.path.exists(original_audio_path):
                word_clip = AudioFileClip(original_audio_path)
                logger.info(f"[{job_id}] Using Mic Recording for Focus Loop.")
            else:
                # Fallback to Neural TTS
                tts_path = os.path.join(app.config['UPLOAD_FOLDER'], f"tts_{job_id}.mp3")
                # Use the original text and original language for the voice loop
                gTTS(text=text, lang='kn' if lang=='kannada' else 'en').save(tts_path)
                word_clip = AudioFileClip(tts_path)
                logger.info(f"[{job_id}] Using Neural TTS for Focus Loop.")
            
            # B. Create a 2s silence clip
            silence_array = np.zeros((int(word_clip.fps * 2), 2))
            silence_clip = AudioArrayClip(silence_array, fps=word_clip.fps)
            
            # C. Create the rhythmic unit (Voice + 2s Silence) and loop it
            loop_unit = concatenate_audioclips([word_clip, silence_clip])
            final_audio = loop_unit.fx(afx.audio_loop, duration=final_video.duration)
                
            final_video = final_video.set_audio(final_audio)
            logger.info(f"[{job_id}] Auditory focus loop integrated successfully.")
        except Exception as ae:
            logger.warning(f"Audio focus loop failed: {ae}")

        unique_id = str(uuid.uuid4())
        video_filename = f"{unique_id}.mp4"
        video_path = os.path.join(app.config['GENERATED_FOLDER'], video_filename)
        final_video.write_videofile(video_path, codec="libx264", logger=None)

        # 4. Save to Database
        with app.app_context():
            new_v = GeneratedVideo(
                user_id=user_id, 
                input_text=text,  # Save the original word (Kannada or English)
                english_word=visual_word, 
                language=lang,
                video_path=video_path, 
                unique_id=unique_id
            )
            db.session.add(new_v)
            db.session.commit()

        local_jobs[job_id].update({'status': 'completed', 'video_url': f'/api/video/{unique_id}', 'video_id': unique_id})
        logger.info(f"[{job_id}] Video generation complete!")

        # Cleanup
        for f in video_files: 
            if os.path.exists(f): os.remove(f)

    except Exception as e:
        logger.error(f"[{job_id}] Error: {e}")
        local_jobs[job_id].update({'status': 'failed', 'error': str(e)})

# --- ROUTES ---
@app.route('/')
def index():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    videos = GeneratedVideo.query.filter_by(user_id=current_user.id).order_by(GeneratedVideo.created_at.desc()).all()
    return render_template('dashboard.html', videos=videos)

@app.route('/api/process-voice', methods=['POST'])
@login_required
def process_voice():
    if 'audio' not in request.files: return jsonify({'success': False}), 400
    audio_file = request.files['audio']
    lang = request.form.get('language', 'english')
    fname = secure_filename(f"v_{uuid.uuid4()}.wav")
    path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
    audio_file.save(path)
    
    try:
        r = sr.Recognizer()
        with sr.AudioFile(path) as source:
            audio = r.record(source)
        text = r.recognize_google(audio, language='kn-IN' if lang == 'kannada' else 'en-US')
        
        # Neural Translation (from paper)
        english_text = text
        if lang == 'kannada':
            english_text = GoogleTranslator(source='kn', target='en').translate(text)
            
        return jsonify({'success': True, 'text': text, 'english': english_text, 'audio_path': path})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/generate', methods=['POST'])
@login_required
def generate():
    data = request.get_json()
    text = data.get('text')
    lang = data.get('language', 'english')
    audio_path = data.get('audio_path')
    user_id = current_user.id
    
    job_id = str(uuid.uuid4())
    local_jobs[job_id] = {'status': 'processing', 'progress': 'Starting...'}
    
    # Pass original 'text' for voice and 'lang' for context
    threading.Thread(target=generate_story_logic_internal, args=(text, lang, job_id, user_id, audio_path)).start()
    return jsonify({'success': True, 'job_id': job_id})

@app.route('/api/status/<job_id>')
@login_required
def status(job_id):
    return jsonify(local_jobs.get(job_id, {'status': 'not_found'}))

@app.route('/api/video/<video_id>')
@login_required
def get_video(video_id):
    v = GeneratedVideo.query.filter_by(unique_id=video_id).first()
    return send_file(v.video_path) if v else (jsonify({'err': 'none'}), 404)

@app.route('/api/download/<video_id>')
@login_required
def download_video(video_id):
    v = GeneratedVideo.query.filter_by(unique_id=video_id).first()
    if v:
        return send_file(v.video_path, as_attachment=True)
    return (jsonify({'err': 'none'}), 404)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        # Support both 'username' and 'email' as login identifiers
        identifier = data.get('username') or data.get('email')
        password = data.get('password')
        
        # Check username or email
        u = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
        
        if u and bcrypt.check_password_hash(u.password, password):
            login_user(u)
            if request.is_json:
                return jsonify({'success': True, 'message': 'Logged in successfully!'})
            return redirect(url_for('dashboard'))
        
        if request.is_json:
            return jsonify({'success': False, 'message': 'Invalid credentials'})
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        if User.query.filter_by(username=username).first():
            if request.is_json: return jsonify({'success': False, 'message': 'Username already exists'})
            return redirect(url_for('signup'))

        pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_u = User(username=username, email=email, password=pw)
        db.session.add(new_u)
        db.session.commit()
        
        if request.is_json:
            return jsonify({'success': True, 'message': 'Account created successfully!'})
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', password=bcrypt.generate_password_hash('admin123').decode('utf-8')))
            db.session.commit()
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=3000)

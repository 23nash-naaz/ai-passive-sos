import time
import os
import requests
import smtplib
import streamlit as st
import numpy as np
import wave
from email.mime.text import MIMEText
from threading import Thread
import imageio_ffmpeg as ffmpeg  # Provides bundled ffmpeg binary

# === Configuration (use environment variables in production) ===
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "29f8ab7b44c64f58903439c9afe57ed4")
ASSEMBLYAI_UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
ASSEMBLYAI_TRANSCRIPT_URL = "https://api.assemblyai.com/v2/transcript"

# === Audio Configuration ===
# These parameters are for reference; ffmpeg handles the recording.
SAMPLE_RATE = 44100       # Hz (for writing the WAV file)
CHANNELS = 1              # Mono audio
CHUNK_DURATION = 5        # Seconds per audio chunk
AUDIO_FILENAME = "temp_chunk.wav"

# === Distress Keywords ===
DISTRESS_KEYWORDS = {"help", "sos", "emergency", "911", "save me", "distress", "assistance", "trapped", "danger"}

# --- Custom CSS for Beautiful UI ---
st.markdown(
    """
    <style>
    body {
        background-color: #f0f2f6;
    }
    .header {
        font-size: 2.5em;
        color: #4B0082;
        font-weight: bold;
        text-align: center;
    }
    .subheader {
        font-size: 1.2em;
        color: #3124;
        text-align: center;
    }
    .section {
        background-color: #eeeeee;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Page Title and Description ---
st.markdown('<div class="header">AI Passive SOS</div>', unsafe_allow_html=True)
st.markdown('<div class="subheader">Passive Listening. Automatic Alerts. Enhanced Safety.</div>', unsafe_allow_html=True)
st.write("This system continuously records your audio, transcribes it using AssemblyAI, and sends an SOS alert if distress keywords are detected.")

# --- Email Configuration Section ---
st.markdown('<div class="section"><h3>Email Configuration</h3></div>', unsafe_allow_html=True)
with st.container():
    email_username = st.text_input("📧 Enter your Email (Sender)", "")
    email_password = st.text_input("🔑 Enter your Email Password (App Password)", "", type="password")
    recipient_email = st.text_input("📩 Enter Recipient Email for SOS Alerts:", "")

# --- Global flag for continuous recording ---
stop_due_to_distress = False

def record_audio(filename=AUDIO_FILENAME, duration=CHUNK_DURATION):
    """
    Record audio using the bundled ffmpeg binary from imageio-ffmpeg and save as a WAV file.
    This command uses the default audio input; adjust the device parameter if needed.
    """
    ffmpeg_exe = ffmpeg.get_ffmpeg_exe()  # Get bundled ffmpeg binary
    # Build the ffmpeg command. The command below assumes a Linux environment with PulseAudio.
    # Adjust "-f" and "-i" options as needed for your deployment.
    command = f"{ffmpeg_exe} -f pulse -i default -t {duration} {filename} -y"
    ret = os.system(command)
    if ret != 0:
        st.error("❌ Audio recording failed. Check your audio input configuration.")
    else:
        st.info(f"✅ Audio chunk recorded as {filename}")

def upload_audio(file_path):
    """Upload audio file to AssemblyAI and return the audio URL."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    with open(file_path, "rb") as f:
        response = requests.post(ASSEMBLYAI_UPLOAD_URL, headers=headers, data=f)
    response.raise_for_status()
    st.info("🔄 Audio chunk uploaded to AssemblyAI.")
    return response.json()['upload_url']

def request_transcription(audio_url):
    """Request transcription from AssemblyAI."""
    headers = {"authorization": ASSEMBLYAI_API_KEY, "content-type": "application/json"}
    json_data = {"audio_url": audio_url}
    response = requests.post(ASSEMBLYAI_TRANSCRIPT_URL, json=json_data, headers=headers)
    response.raise_for_status()
    st.info("⏳ Transcription requested...")
    return response.json()['id']

def poll_transcription(transcript_id):
    """Poll AssemblyAI API until transcription is complete and return the text."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    polling_url = f"{ASSEMBLYAI_TRANSCRIPT_URL}/{transcript_id}"
    while True:
        response = requests.get(polling_url, headers=headers)
        response.raise_for_status()
        status = response.json()['status']
        if status == 'completed':
            st.info("✅ Transcription completed.")
            return response.json()['text']
        elif status == 'error':
            raise Exception("Error in transcription")
        time.sleep(3)

def contains_distress(text):
    """Check if the transcript contains any distress keywords."""
    text_lower = text.lower()
    for keyword in DISTRESS_KEYWORDS:
        if keyword in text_lower:
            st.error(f"🚨 Detected distress keyword: {keyword}")
            return True
    return False

def send_alert_email(transcript_text):
    """Send an SOS alert email with the transcript text."""
    if not (email_username and email_password and recipient_email):
        st.warning("⚠️ Please enter all email credentials before sending an alert.")
        return

    subject = "🚨 SOS Alert: Distress Detected!"
    body = f"A distress keyword was detected in a recent transcription:\n\n{transcript_text}"
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = email_username
    msg["To"] = recipient_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(email_username, email_password)
            server.sendmail(email_username, recipient_email, msg.as_string())
        st.success("✅ SOS Alert email sent successfully!")
    except Exception as e:
        st.error(f"❌ Failed to send email: {e}")

def process_audio_file():
    """Process the recorded audio file: upload, transcribe, detect distress, and alert if needed."""
    global stop_due_to_distress
    try:
        audio_url = upload_audio(AUDIO_FILENAME)
        transcript_id = request_transcription(audio_url)
        transcript_text = poll_transcription(transcript_id)
        st.markdown(f"### 📝 Chunk Transcription:\n{transcript_text}")
        if contains_distress(transcript_text):
            st.warning("🚨 Distress keywords detected! Sending SOS alert message.")
            send_alert_email(transcript_text)
            stop_due_to_distress = True
    except Exception as e:
        st.error(f"❌ Error processing audio file: {e}")

def continuous_recording():
    """
    Continuously record audio in CHUNK_DURATION segments using ffmpeg
    and process each chunk. Automatically stops if a distress keyword is detected.
    """
    global stop_due_to_distress
    st.info("🎤 Continuous Recording Started...")
    while True:
        record_audio()  # Record a chunk using ffmpeg
        st.info("Processing audio chunk...")
        process_audio_file()  # Process the recorded file
        if stop_due_to_distress:
            st.warning("⛔ Distress detected! Stopping continuous recording.")
            break
    st.info("🛑 Continuous Recording Stopped.")

# --- Control Panel ---
st.markdown('<div class="section"><h3>Control Panel</h3></div>', unsafe_allow_html=True)
if st.button("🎙️ Start Passive SOS", key="start"):
    if not (email_username and email_password and recipient_email):
        st.warning("⚠️ Please fill in all email credentials before starting.")
    else:
        Thread(target=continuous_recording).start()

import time
import requests
import smtplib
import streamlit as st
from email.mime.text import MIMEText
from threading import Thread
from streamlit_audiorecorder import st_audiorecorder
import numpy as np
import wave

# === AssemblyAI Configuration ===
ASSEMBLYAI_API_KEY = "YOUR_ASSEMBLYAI_API_KEY"
ASSEMBLYAI_UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
ASSEMBLYAI_TRANSCRIPT_URL = "https://api.assemblyai.com/v2/transcript"

# === Distress Keywords ===
DISTRESS_KEYWORDS = {"help", "sos", "emergency", "911", "save me", "distress", "assistance", "trapped", "danger"}

# --- Page Title and Description ---
st.title("AI Passive SOS")
st.write("This system records audio, transcribes it using AssemblyAI, and sends an SOS alert if distress keywords are detected.")

# --- Email Configuration Section ---
st.sidebar.header("Email Configuration")
email_username = st.sidebar.text_input("📧 Sender Email", "")
email_password = st.sidebar.text_input("🔑 Email App Password", "", type="password")
recipient_email = st.sidebar.text_input("📩 Recipient Email", "")

# --- Function to Save Audio ---
def save_audio(audio_data, filename="temp_audio.wav"):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(audio_data)
    return filename

# --- Upload Audio to AssemblyAI ---
def upload_audio(file_path):
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    with open(file_path, "rb") as f:
        response = requests.post(ASSEMBLYAI_UPLOAD_URL, headers=headers, data=f)
    response.raise_for_status()
    return response.json()['upload_url']

# --- Request Transcription ---
def request_transcription(audio_url):
    headers = {"authorization": ASSEMBLYAI_API_KEY, "content-type": "application/json"}
    json_data = {"audio_url": audio_url}
    response = requests.post(ASSEMBLYAI_TRANSCRIPT_URL, json=json_data, headers=headers)
    response.raise_for_status()
    return response.json()['id']

# --- Poll Transcription ---
def poll_transcription(transcript_id):
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    polling_url = f"{ASSEMBLYAI_TRANSCRIPT_URL}/{transcript_id}"
    while True:
        response = requests.get(polling_url, headers=headers)
        response.raise_for_status()
        status = response.json()['status']
        if status == 'completed':
            return response.json()['text']
        elif status == 'error':
            raise Exception("Error in transcription")
        time.sleep(3)

# --- Detect Distress Keywords ---
def contains_distress(text):
    for keyword in DISTRESS_KEYWORDS:
        if keyword in text.lower():
            return True
    return False

# --- Send SOS Email ---
def send_alert_email(transcript_text):
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

# --- Main Logic for Recording and Processing ---
audio_data = st_audiorecorder("Click to Record", key="audio")

if audio_data is not None:
    st.audio(audio_data, format="audio/wav")
    st.success("✅ Audio recorded successfully!")
    filename = save_audio(audio_data)
    
    try:
        audio_url = upload_audio(filename)
        transcript_id = request_transcription(audio_url)
        transcript_text = poll_transcription(transcript_id)
        st.write("### Transcription:", transcript_text)
        
        if contains_distress(transcript_text):
            st.warning("🚨 Distress detected! Sending SOS alert...")
            send_alert_email(transcript_text)
    except Exception as e:
        st.error(f"❌ Error processing audio: {e}")


import time
import requests
import smtplib
import os
import wave
import numpy as np
from email.mime.text import MIMEText
from fastapi import FastAPI, UploadFile, File, HTTPException
import uvicorn
import tempfile
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# === AssemblyAI Configuration ===
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "29f8ab7b44c64f58903439c9afe57ed4")  # Set your actual key via env var
ASSEMBLYAI_UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
ASSEMBLYAI_TRANSCRIPT_URL = "https://api.assemblyai.com/v2/transcript"

# === Audio Configuration ===
SAMPLE_RATE = 44100       # in Hz
CHANNELS = 1              # mono audio

# === Distress Keywords ===
DISTRESS_KEYWORDS = {
    "help", "sos", "emergency", "911", "save me", "distress", "assistance", "trapped", "danger"
}

# === Email Configuration ===
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME", "your_email@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "your_app_password")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "recipient@example.com")

# ------ Utility Functions ------

def save_audio_file(audio_bytes: bytes) -> str:
    """Save audio bytes to a temporary WAV file and return its file path."""
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        with wave.open(temp_file, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit (2 bytes per sample)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_bytes)
        temp_file.close()
        logger.info("Audio saved to temporary file: %s", temp_file.name)
        return temp_file.name
    except Exception as e:
        logger.error("Error saving audio file: %s", e)
        raise

def upload_audio_to_assemblyai(file_path: str) -> str:
    """Upload the audio file to AssemblyAI and return the uploaded audio URL."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    with open(file_path, "rb") as f:
        response = requests.post(ASSEMBLYAI_UPLOAD_URL, headers=headers, data=f)
    if response.status_code != 200:
        msg = f"Upload failed: {response.status_code} - {response.text}"
        logger.error(msg)
        raise HTTPException(status_code=500, detail=msg)
    upload_url = response.json()['upload_url']
    logger.info("Audio uploaded successfully. URL: %s", upload_url)
    return upload_url

def request_transcription(audio_url: str) -> str:
    """Request a transcription from AssemblyAI and return the transcript ID."""
    headers = {"authorization": ASSEMBLYAI_API_KEY, "content-type": "application/json"}
    json_data = {"audio_url": audio_url}
    response = requests.post(ASSEMBLYAI_TRANSCRIPT_URL, json=json_data, headers=headers)
    if response.status_code != 200:
        msg = f"Transcription request failed: {response.status_code} - {response.text}"
        logger.error(msg)
        raise HTTPException(status_code=500, detail=msg)
    transcript_id = response.json()['id']
    logger.info("Transcription requested; ID: %s", transcript_id)
    return transcript_id

def poll_transcription(transcript_id: str) -> str:
    """Poll AssemblyAI until the transcription is complete and return the transcribed text."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    polling_url = f"{ASSEMBLYAI_TRANSCRIPT_URL}/{transcript_id}"
    for _ in range(30):  # try for roughly 90 seconds
        response = requests.get(polling_url, headers=headers)
        if response.status_code != 200:
            msg = f"Polling failed: {response.status_code} - {response.text}"
            logger.error(msg)
            raise HTTPException(status_code=500, detail=msg)
        result = response.json()
        status = result.get("status")
        if status == "completed":
            transcript_text = result.get("text", "No speech detected.")
            logger.info("Transcription completed.")
            return transcript_text
        elif status == "error":
            msg = f"Transcription error: {result.get('error', 'Unknown error')}"
            logger.error(msg)
            raise HTTPException(status_code=500, detail=msg)
        time.sleep(3)
    raise HTTPException(status_code=504, detail="Transcription timed out.")

def contains_distress(text: str) -> bool:
    """Return True if any distress keyword is found in the text."""
    text_lower = text.lower()
    for keyword in DISTRESS_KEYWORDS:
        if keyword in text_lower:
            logger.info("Detected distress keyword: %s", keyword)
            return True
    return False

def send_alert_email(transcript_text: str):
    """Send an SOS alert email with the transcript text."""
    if not (EMAIL_USERNAME and EMAIL_PASSWORD and RECIPIENT_EMAIL):
        logger.warning("Email credentials are missing.")
        raise Exception("Email credentials are not set.")
    
    subject = "🚨 SOS Alert: Distress Detected!"
    body = f"A distress keyword was detected in the following transcription:\n\n{transcript_text}"
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_USERNAME
    msg["To"] = RECIPIENT_EMAIL

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USERNAME, RECIPIENT_EMAIL, msg.as_string())
        logger.info("SOS Alert email sent successfully.")
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        raise

def process_audio_file(audio_bytes: bytes) -> dict:
    """
    Process the given audio:
      1. Save as a temporary file.
      2. Upload to AssemblyAI.
      3. Request transcription and poll for results.
      4. Check transcription for distress keywords.
      5. Send an alert email if distress is detected.
    Returns a dictionary with the transcript and alert status.
    """
    temp_audio_path = save_audio_file(audio_bytes)
    try:
        audio_url = upload_audio_to_assemblyai(temp_audio_path)
        transcript_id = request_transcription(audio_url)
        transcript_text = poll_transcription(transcript_id)
        alert_sent = False
        if contains_distress(transcript_text):
            send_alert_email(transcript_text)
            alert_sent = True
        return {"transcript": transcript_text, "alert_sent": alert_sent}
    finally:
        try:
            os.remove(temp_audio_path)
            logger.info("Removed temporary file: %s", temp_audio_path)
        except Exception as e:
            logger.warning("Could not remove temporary file: %s", e)

# ------ FastAPI Endpoints ------

@app.post("/process_audio")
async def process_audio_endpoint(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        result = process_audio_file(audio_bytes)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error("Error processing audio: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status")
def status_endpoint():
    return {"status": "running"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

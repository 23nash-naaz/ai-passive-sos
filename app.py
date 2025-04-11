import time
import requests
import smtplib
import streamlit as st
import numpy as np
import wave
from email.mime.text import MIMEText
from io import BytesIO
import os
from pydub import AudioSegment
import tempfile

# === AssemblyAI Configuration ===
ASSEMBLYAI_API_KEY = "29f8ab7b44c64f58903439c9afe57ed4"  # AssemblyAI API key directly integrated
ASSEMBLYAI_UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
ASSEMBLYAI_TRANSCRIPT_URL = "https://api.assemblyai.com/v2/transcript"

# === Audio Configuration ===
SAMPLE_RATE = 16000      # reduced sample rate for better web compatibility
CHANNELS = 1             # mono audio
CHUNK_DURATION = 5       # seconds per audio chunk

# === Distress Keywords ===
DISTRESS_KEYWORDS = {"help", "sos", "emergency", "911", "save me", "distress", "assistance", "trapped", "danger"}

# --- Session state initialization ---
if 'last_transcript' not in st.session_state:
    st.session_state.last_transcript = ""
if 'processing' not in st.session_state:
    st.session_state.processing = False

# --- Custom CSS for Beautiful UI ---
st.markdown(
    """
    <style>
    .stApp {
        background-color: #f0f2f6;
    }
    .header {
        font-size: 2.5em;
        color: #4B0082;
        font-weight: bold;
        text-align: center;
        margin-bottom: 1rem;
    }
    .subheader {
        font-size: 1.2em;
        color: #333;
        text-align: center;
        margin-bottom: 2rem;
    }
    .section {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    .stButton>button {
        background-color: #4B0082;
        color: white;
        padding: 10px 24px;
        border: none;
        border-radius: 5px;
        width: 100%;
    }
    .stButton>button:hover {
        background-color: #6A0DAD;
    }
    .status-box {
        padding: 1rem;
        border-radius: 5px;
        margin: 1rem 0;
    }
    .alert {
        background-color: #ffebee;
        border-left: 5px solid #f44336;
    }
    .info {
        background-color: #e3f2fd;
        border-left: 5px solid #2196f3;
    }
    .success {
        background-color: #e8f5e9;
        border-left: 5px solid #4caf50;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Page Title and Description ---
st.markdown('<div class="header">AI Passive SOS</div>', unsafe_allow_html=True)
st.markdown('<div class="subheader">Passive Listening. Automatic Alerts. Enhanced Safety.</div>', unsafe_allow_html=True)
st.write("This system records your audio, transcribes it using AssemblyAI, and sends an SOS alert if distress keywords are detected.")

# --- Email Configuration Section ---
st.markdown('<div class="section"><h3>Email Configuration</h3></div>', unsafe_allow_html=True)
with st.container():
    email_username = st.text_input("📧 Enter your Email (Sender)", "")
    
    # For Gmail, recommend using App Password
    email_password = st.text_input("🔑 Enter your Email Password", "", type="password", 
                                 help="For Gmail, use an App Password: https://support.google.com/accounts/answer/185833")
    
    recipient_email = st.text_input("📩 Enter Recipient Email for SOS Alerts:", "")
    
    # Email service selection
    email_service = st.selectbox(
        "Select Email Service",
        ["Gmail", "Outlook/Hotmail", "Yahoo", "Other (Custom SMTP)"]
    )
    
    # Show custom SMTP settings if "Other" is selected
    if email_service == "Other (Custom SMTP)":
        smtp_server = st.text_input("SMTP Server:", "")
        smtp_port = st.number_input("SMTP Port:", value=587, min_value=1, max_value=65535)
    else:
        # Set default SMTP settings based on selection
        if email_service == "Gmail":
            smtp_server = "smtp.gmail.com"
            smtp_port = 587
        elif email_service == "Outlook/Hotmail":
            smtp_server = "smtp.office365.com"
            smtp_port = 587
        elif email_service == "Yahoo":
            smtp_server = "smtp.mail.yahoo.com"
            smtp_port = 587

def get_email_credentials():
    """Return a dictionary with all email settings"""
    return {
        "username": email_username,
        "password": email_password,
        "recipient": recipient_email,
        "smtp_server": smtp_server,
        "smtp_port": smtp_port
    }

def upload_audio_to_assemblyai(audio_data):
    """Upload audio data to AssemblyAI and return the audio URL."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    
    # Send the audio data directly in the request
    response = requests.post(
        ASSEMBLYAI_UPLOAD_URL,
        headers=headers,
        data=audio_data
    )
    response.raise_for_status()
    return response.json()['upload_url']

def request_transcription(audio_url):
    """Request transcription from AssemblyAI."""
    headers = {
        "authorization": ASSEMBLYAI_API_KEY, 
        "content-type": "application/json"
    }
    json_data = {"audio_url": audio_url}
    response = requests.post(ASSEMBLYAI_TRANSCRIPT_URL, json=json_data, headers=headers)
    response.raise_for_status()
    return response.json()['id']

def poll_transcription(transcript_id):
    """Poll AssemblyAI API until transcription is complete and return the text."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    polling_url = f"{ASSEMBLYAI_TRANSCRIPT_URL}/{transcript_id}"
    
    for _ in range(30):  # Set a limit to prevent infinite polling
        response = requests.get(polling_url, headers=headers)
        response.raise_for_status()
        result = response.json()
        
        if result['status'] == 'completed':
            return result['text'] or "No speech detected."
        elif result['status'] == 'error':
            raise Exception(f"Transcription error: {result.get('error', 'Unknown error')}")
        
        time.sleep(2)  # Wait 2 seconds between polling attempts
    
    raise Exception("Transcription timed out after 60 seconds")

def contains_distress(text):
    """Check if the transcript contains any distress keywords."""
    if not text:
        return False
        
    text_lower = text.lower()
    found_keywords = []
    
    for keyword in DISTRESS_KEYWORDS:
        if keyword in text_lower:
            found_keywords.append(keyword)
    
    return found_keywords

def send_alert_email(transcript_text, keywords_found):
    """Send an SOS alert email with the transcript text."""
    creds = get_email_credentials()
    
    if not (creds["username"] and creds["password"] and creds["recipient"]):
        st.warning("⚠️ Please enter all email credentials before sending an alert.")
        return False
        
    subject = "🚨 SOS Alert: Distress Detected!"
    body = f"""SOS ALERT: Distress detected in audio recording!

Detected Keywords: {', '.join(keywords_found)}

Full Transcript:
{transcript_text}

This is an automated alert from AI Passive SOS.
"""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = creds["username"]
    msg["To"] = creds["recipient"]

    try:
        with smtplib.SMTP(creds["smtp_server"], creds["smtp_port"]) as server:
            server.starttls()
            server.login(creds["username"], creds["password"])
            server.sendmail(creds["username"], creds["recipient"], msg.as_string())
        return True
    except Exception as e:
        st.error(f"❌ Failed to send email: {str(e)}")
        return False

def process_audio(audio_data):
    """Process audio: upload, transcribe, detect distress, and send an alert if needed."""
    status_placeholder = st.empty()
    
    try:
        # Step 1: Upload to AssemblyAI
        status_placeholder.info("🔄 Uploading audio to transcription service...")
        audio_url = upload_audio_to_assemblyai(audio_data)
        
        # Step 2: Request transcription
        status_placeholder.info("⏳ Requesting transcription...")
        transcript_id = request_transcription(audio_url)
        
        # Step 3: Wait for transcription to complete
        status_placeholder.info("⏳ Processing audio transcription (this may take a moment)...")
        transcript_text = poll_transcription(transcript_id)
        st.session_state.last_transcript = transcript_text
        
        # Display the transcript
        st.markdown("### 📝 Transcript:")
        st.write(transcript_text or "No speech detected")
        
        # Step 4: Check for distress keywords
        distress_keywords = contains_distress(transcript_text)
        if distress_keywords:
            st.markdown(f"""
            <div class="status-box alert">
                <h3>🚨 ALERT: Distress Detected!</h3>
                <p>Detected keywords: {', '.join(distress_keywords)}</p>
            </div>
            """, unsafe_allow_html=True)
            
            # Step 5: Send alert if distress detected
            if send_alert_email(transcript_text, distress_keywords):
                st.markdown("""
                <div class="status-box success">
                    <h3>✅ SOS Alert Sent</h3>
                    <p>An emergency notification has been sent to the designated contact.</p>
                </div>
                """, unsafe_allow_html=True)
        else:
            status_placeholder.success("✅ Audio processed successfully. No distress detected.")
            
    except Exception as e:
        status_placeholder.error(f"❌ Error: {str(e)}")
        st.error(f"Processing failed: {str(e)}")
    
    st.session_state.processing = False

# --- Streamlit Audio Recorder ---
st.markdown('<div class="section"><h3>Audio Recording</h3></div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    # Record button
    audio_bytes = st.audio_recorder(
        text="Click to record", 
        recording_color="#4B0082",
        neutral_color="#6A0DAD",
        sample_rate=SAMPLE_RATE,
    )

with col2:
    # Test alert button
    if st.button("✉️ Test Alert Email"):
        if not (email_username and email_password and recipient_email):
            st.warning("⚠️ Please fill in all email credentials before testing.")
        else:
            test_message = "This is a test alert from the AI Passive SOS system. If you received this message, the alert system is working properly."
            if send_alert_email(test_message, ["TEST ALERT"]):
                st.success("✅ Test email sent successfully!")

# Process the recorded audio
if audio_bytes and not st.session_state.processing:
    st.session_state.processing = True
    
    # Convert the audio bytes to format compatible with AssemblyAI
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
        temp_audio.write(audio_bytes)
    
    # Load with pydub and export as proper WAV format
    audio = AudioSegment.from_file(temp_audio.name)
    
    # Export as WAV to a BytesIO object
    buf = BytesIO()
    audio.export(buf, format="wav")
    buf.seek(0)
    
    # Remove the temp file
    os.unlink(temp_audio.name)
    
    # Process the audio
    process_audio(buf.read())

# --- Instructions Section ---
with st.expander("📋 How to Use"):
    st.markdown("""
    ### How to Use AI Passive SOS
    
    1. **Configure Email Settings**:
       - Enter your email address and password
       - For Gmail users, you'll need to create an App Password
       - Enter the recipient email for emergency alerts
    
    2. **Record Audio**:
       - Click the record button to start recording
       - Speak clearly into your microphone
       - Click again to stop recording and process the audio
    
    3. **Monitor Results**:
       - The system will transcribe your speech
       - If distress keywords are detected, an alert will be sent automatically
       
    4. **Distress Keywords**:
       The system listens for: help, sos, emergency, 911, save me, distress, assistance, trapped, danger
    """)

with st.expander("⚙️ Troubleshooting"):
    st.markdown("""
    ### Troubleshooting
    
    **Browser Not Detecting Microphone**
    - Make sure your browser has permission to access your microphone
    - Try using Chrome or Edge for best compatibility
    - Refresh the page and try again
    
    **Email Alerts Not Sending**
    - For Gmail: Make sure you're using an App Password, not your regular password
    - Check that your email and password are entered correctly
    - Try the "Test Alert Email" button to verify your settings
    
    **Audio Processing Issues**
    - Speak clearly and avoid background noise
    - Make sure your recording is at least 1-2 seconds long
    - If transcription fails, try recording again
    """)

# Footer
st.markdown("---")
st.markdown(
    """<div style="text-align: center; color: #666;">
    AI Passive SOS | Safety Through Technology | v1.0
    </div>""", 
    unsafe_allow_html=True
)


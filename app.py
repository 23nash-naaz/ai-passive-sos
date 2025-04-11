import time
import requests
import smtplib
import streamlit as st
import numpy as np
from email.mime.text import MIMEText
from io import BytesIO
import os
import tempfile
from streamlit_webrtc import webrtc_streamer, WebRtcMode, RTCConfiguration
import av
import queue
import threading
import logging
import wave

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === AssemblyAI Configuration ===
ASSEMBLYAI_API_KEY = "29f8ab7b44c64f58903439c9afe57ed4"
ASSEMBLYAI_UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
ASSEMBLYAI_TRANSCRIPT_URL = "https://api.assemblyai.com/v2/transcript"

# === Audio Configuration ===
SAMPLE_RATE = 16000  # sample rate for better web compatibility
CHANNELS = 1         # mono audio

# === Distress Keywords ===
DISTRESS_KEYWORDS = {"help", "sos", "emergency", "911", "save me", "distress", "assistance", "trapped", "danger"}

# --- Session state initialization ---
if 'audio_frames' not in st.session_state:
    st.session_state.audio_frames = []
if 'recording' not in st.session_state:
    st.session_state.recording = False
if 'audio_buffer' not in st.session_state:
    st.session_state.audio_buffer = queue.Queue()
if 'last_transcript' not in st.session_state:
    st.session_state.last_transcript = ""
if 'processing' not in st.session_state:
    st.session_state.processing = False
if 'webrtc_ctx' not in st.session_state:
    st.session_state.webrtc_ctx = None

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

def save_audio_bytes(audio_bytes):
    """Save audio bytes to a temporary WAV file and return the filename."""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    temp_file.write(audio_bytes)
    temp_file.close()
    return temp_file.name

def upload_audio_to_assemblyai(audio_file_path):
    """Upload audio file to AssemblyAI and return the audio URL."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    
    try:
        with open(audio_file_path, "rb") as f:
            response = requests.post(
                ASSEMBLYAI_UPLOAD_URL,
                headers=headers,
                data=f
            )
        
        if response.status_code != 200:
            st.error(f"Upload failed with status {response.status_code}: {response.text}")
            return None
            
        return response.json()['upload_url']
    except Exception as e:
        st.error(f"Error uploading audio: {str(e)}")
        return None

def request_transcription(audio_url):
    """Request transcription from AssemblyAI."""
    headers = {
        "authorization": ASSEMBLYAI_API_KEY, 
        "content-type": "application/json"
    }
    json_data = {"audio_url": audio_url}
    
    try:
        response = requests.post(ASSEMBLYAI_TRANSCRIPT_URL, json=json_data, headers=headers)
        
        if response.status_code != 200:
            st.error(f"Transcription request failed with status {response.status_code}: {response.text}")
            return None
            
        return response.json()['id']
    except Exception as e:
        st.error(f"Error requesting transcription: {str(e)}")
        return None

def poll_transcription(transcript_id):
    """Poll AssemblyAI API until transcription is complete and return the text."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    polling_url = f"{ASSEMBLYAI_TRANSCRIPT_URL}/{transcript_id}"
    
    try:
        for _ in range(30):  # Set a limit to prevent infinite polling
            response = requests.get(polling_url, headers=headers)
            
            if response.status_code != 200:
                st.error(f"Polling failed with status {response.status_code}: {response.text}")
                return None
                
            result = response.json()
            
            if result['status'] == 'completed':
                return result['text'] or "No speech detected."
            elif result['status'] == 'error':
                st.error(f"Transcription error: {result.get('error', 'Unknown error')}")
                return None
            
            time.sleep(2)  # Wait 2 seconds between polling attempts
        
        st.warning("Transcription timed out after 60 seconds")
        return None
    except Exception as e:
        st.error(f"Error polling transcription: {str(e)}")
        return None

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

def process_audio(audio_bytes):
    """Process audio: save, upload, transcribe, detect distress, and send an alert if needed."""
    status_placeholder = st.empty()
    
    try:
        # Step 1: Save audio to temp file
        status_placeholder.info("💾 Saving audio recording...")
        temp_audio_file = save_audio_bytes(audio_bytes)
        
        # Step 2: Upload to AssemblyAI
        status_placeholder.info("🔄 Uploading audio to transcription service...")
        audio_url = upload_audio_to_assemblyai(temp_audio_file)
        if not audio_url:
            status_placeholder.error("❌ Failed to upload audio to AssemblyAI")
            return
        
        # Clean up temp file
        os.unlink(temp_audio_file)
        
        # Step 3: Request transcription
        status_placeholder.info("⏳ Requesting transcription...")
        transcript_id = request_transcription(audio_url)
        if not transcript_id:
            status_placeholder.error("❌ Failed to request transcription")
            return
        
        # Step 4: Wait for transcription to complete
        status_placeholder.info("⏳ Processing audio transcription (this may take a moment)...")
        transcript_text = poll_transcription(transcript_id)
        if not transcript_text:
            status_placeholder.error("❌ Failed to retrieve transcription")
            return
            
        st.session_state.last_transcript = transcript_text
        
        # Display the transcript
        st.markdown("### 📝 Transcript:")
        st.write(transcript_text or "No speech detected")
        
        # Step 5: Check for distress keywords
        distress_keywords = contains_distress(transcript_text)
        if distress_keywords:
            st.markdown(f"""
            <div class="status-box alert">
                <h3>🚨 ALERT: Distress Detected!</h3>
                <p>Detected keywords: {', '.join(distress_keywords)}</p>
            </div>
            """, unsafe_allow_html=True)
            
            # Step 6: Send alert if distress detected
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
    finally:
        st.session_state.processing = False

# --- Audio capture with streamlit-webrtc ---
st.markdown('<div class="section"><h3>Audio Recording</h3></div>', unsafe_allow_html=True)

class AudioProcessor:
    def __init__(self):
        self.audio_buffer = queue.Queue()
        
    def recv(self, frame):
        if st.session_state.recording:
            sound = frame.to_ndarray().astype(np.float32)
            self.audio_buffer.put(sound)
        return frame

# Create a status placeholder for recording status
status_text = st.empty()
if st.session_state.recording:
    status_text.info("🔴 Recording in progress...")
else:
    status_text.info("🎤 Ready to record")

# Buttons to start/stop recording
col1, col2 = st.columns(2)
with col1:
    start_button = st.button("▶️ Start Recording")
with col2:
    stop_button = st.button("⏹️ Stop Recording")

# WebRTC Configuration
rtc_configuration = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})

# Create audio processor
audio_processor = AudioProcessor()

# WebRTC Component
webrtc_ctx = webrtc_streamer(
    key="audio-recorder",
    mode=WebRtcMode.SENDONLY,
    rtc_configuration=rtc_configuration,
    media_stream_constraints={"video": False, "audio": True},
    video_processor_factory=None,
    audio_processor_factory=lambda: audio_processor,
    async_processing=True,
)

# Handle button clicks
if start_button and webrtc_ctx.state.playing:
    st.session_state.recording = True
    status_text.info("🔴 Recording started...")
    
if stop_button and st.session_state.recording:
    st.session_state.recording = False
    status_text.info("⏹️ Recording stopped. Processing audio...")
    
    # Process all audio from the buffer
    frames = []
    while not audio_processor.audio_buffer.empty():
        try:
            frames.append(audio_processor.audio_buffer.get_nowait())
        except queue.Empty:
            break
    
    if frames:
        # Concatenate all frames
        audio_data = np.concatenate(frames, axis=0)
        
        # Convert to int16 for WAV format
        audio_int16 = (audio_data * 32767).astype(np.int16)
        
        # Create a BytesIO object and save as WAV
        buf = BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit audio
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())
        
        # Start processing the audio
        if not st.session_state.processing:
            st.session_state.processing = True
            buf.seek(0)  # Go back to the start of the BytesIO buffer
            process_audio(buf.read())

# --- Test Alert Button ---
col1, col2 = st.columns(2)

with col2:
    # Test alert button
    if st.button("✉️ Test Alert Email"):
        if not (email_username and email_password and recipient_email):
            st.warning("⚠️ Please fill in all email credentials before testing.")
        else:
            test_message = "This is a test alert from the AI Passive SOS system. If you received this message, the alert system is working properly."
            if send_alert_email(test_message, ["TEST ALERT"]):
                st.success("✅ Test email sent successfully!")

# --- Instructions Section ---
with st.expander("📋 How to Use"):
    st.markdown("""
    ### How to Use AI Passive SOS
    
    1. **Configure Email Settings**:
       - Enter your email address and password
       - For Gmail users, you'll need to create an App Password
       - Enter the recipient email for emergency alerts
    
    2. **Record Audio**:
       - Click "Start Recording" to begin recording
       - Speak clearly into your microphone
       - Click "Stop Recording" when done to process the audio
    
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
    
    **Microphone Not Working**
    - Allow microphone permissions in your browser
    - Try closing other applications that might be using the microphone
    - Ensure your microphone is properly connected and selected in your system settings
    """)

# Footer
st.markdown("---")
st.markdown(
    """<div style="text-align: center; color: #666;">
    AI Passive SOS | Safety Through Technology | v1.0
    </div>""", 
    unsafe_allow_html=True
)

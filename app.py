import time
import requests
import smtplib
import streamlit as st
import numpy as np
from email.mime.text import MIMEText
from io import BytesIO
import os
import tempfile
import av
import logging
import wave
import threading
import queue
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except OSError:
    # PortAudio not found, disable direct recording features
    SOUNDDEVICE_AVAILABLE = False
    print("PortAudio library not found. Direct recording features will be disabled.")

try:
    from streamlit_webrtc import webrtc_streamer, WebRtcMode, RTCConfiguration, ClientSettings
    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False
    print("streamlit_webrtc module not found. WebRTC features will be disabled.")

from werkzeug.utils import secure_filename

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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

# --- Network connectivity check ---
def check_connectivity():
    try:
        # Use a reliable endpoint with short timeout
        requests.get("https://www.google.com", timeout=3)
        return True
    except requests.exceptions.RequestException:
        return False

# --- Session state initialization ---
def initialize_session_state():
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
    if 'connection_attempt' not in st.session_state:
        st.session_state.connection_attempt = False
    if 'using_file_upload' not in st.session_state:
        st.session_state.using_file_upload = False
    if 'direct_recording' not in st.session_state:
        st.session_state.direct_recording = False
    if 'direct_recorder' not in st.session_state:
        st.session_state.direct_recorder = None

initialize_session_state()

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
    .method-selector {
        background-color: #f5f5f5;
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 15px;
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
            st.info("⚠️ For Gmail: You must use an App Password, not your regular password.")
            
            with st.expander("Gmail App Password Instructions"):
                st.markdown("""
                1. Go to your [Google Account](https://myaccount.google.com/)
                2. Select **Security**
                3. Under "Signing in to Google," select **App Passwords** (you may need to enable 2-Step Verification first)
                4. At the bottom, click **Select app** and choose **Other (Custom name)**
                5. Enter "AI Passive SOS" and click **Generate**
                6. Use the 16-character password shown on your screen
                7. Click **Done**
                """)
        elif email_service == "Outlook/Hotmail":
            smtp_server = "smtp.office365.com"
            smtp_port = 587
        elif email_service == "Yahoo":
            smtp_server = "smtp.mail.yahoo.com"
            smtp_port = 587
            
    if email_service != "Gmail":
        st.info("Some email providers require enabling 'Less secure app access' in your account settings.")

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
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_file.write(audio_bytes)
        temp_file.close()
        logger.info(f"Audio saved to temporary file: {temp_file.name}")
        return temp_file.name
    except Exception as e:
        logger.error(f"Error saving audio to temporary file: {str(e)}")
        raise

def upload_audio_to_assemblyai(audio_file_path):
    """Upload audio file to AssemblyAI and return the audio URL."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    
    try:
        logger.info(f"Uploading audio from {audio_file_path} to AssemblyAI")
        with open(audio_file_path, "rb") as f:
            response = requests.post(
                ASSEMBLYAI_UPLOAD_URL,
                headers=headers,
                data=f
            )
        
        response.raise_for_status()  # Throw exception for bad response codes
        upload_url = response.json()['upload_url']
        logger.info(f"Audio uploaded successfully. URL: {upload_url}")
        return upload_url
    except Exception as e:
        error_msg = f"Error uploading audio: {str(e)}"
        logger.error(error_msg)
        st.error(error_msg)
        return None

def request_transcription(audio_url):
    """Request transcription from AssemblyAI."""
    headers = {
        "authorization": ASSEMBLYAI_API_KEY, 
        "content-type": "application/json"
    }
    json_data = {"audio_url": audio_url}
    
    try:
        logger.info("Requesting transcription from AssemblyAI")
        response = requests.post(ASSEMBLYAI_TRANSCRIPT_URL, json=json_data, headers=headers)
        
        response.raise_for_status()  # Throw exception for bad response codes
        transcript_id = response.json()['id']
        logger.info(f"Transcription requested successfully. ID: {transcript_id}")
        return transcript_id
    except Exception as e:
        error_msg = f"Error requesting transcription: {str(e)}"
        logger.error(error_msg)
        st.error(error_msg)
        return None

def poll_transcription(transcript_id):
    """Poll AssemblyAI API until transcription is complete and return the text."""
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    polling_url = f"{ASSEMBLYAI_TRANSCRIPT_URL}/{transcript_id}"
    
    try:
        logger.info(f"Polling for transcription results: {transcript_id}")
        
        # Polling using incremental backoff for more reliable results
        max_attempts = 30
        
        for attempt in range(max_attempts):
            logger.info(f"Polling attempt {attempt+1}/{max_attempts}")
            response = requests.get(polling_url, headers=headers)
            
            response.raise_for_status()  # Throw exception for bad response codes
            result = response.json()
            
            if result['status'] == 'completed':
                transcription = result['text'] if result['text'] else "No speech detected."
                logger.info(f"Transcription completed: {transcription[:50]}...")
                return transcription
            elif result['status'] == 'error':
                error_msg = f"Transcription error: {result.get('error', 'Unknown error')}"
                logger.error(error_msg)
                st.error(error_msg)
                return None
            
            # Incremental backoff with max wait time
            wait_time = min(2 + attempt, 10)
            time.sleep(wait_time)
        
        warning_msg = f"Transcription timed out after {max_attempts} attempts"
        logger.warning(warning_msg)
        st.warning(warning_msg)
        return None
    except Exception as e:
        error_msg = f"Error polling transcription: {str(e)}"
        logger.error(error_msg)
        st.error(error_msg)
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
    
    if found_keywords:
        logger.info(f"Distress keywords detected: {', '.join(found_keywords)}")
    else:
        logger.info("No distress keywords detected in transcript")
        
    return found_keywords

def send_alert_email(transcript_text, keywords_found):
    """Send an SOS alert email with the transcript text."""
    creds = get_email_credentials()
    
    if not (creds["username"] and creds["password"] and creds["recipient"]):
        warning_msg = "⚠️ Please enter all email credentials before sending an alert."
        logger.warning(warning_msg)
        st.warning(warning_msg)
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
        logger.info(f"Attempting to send email alert to {creds['recipient']}")
        with smtplib.SMTP(creds["smtp_server"], creds["smtp_port"]) as server:
            logger.info("Establishing connection with SMTP server")
            server.ehlo()  # Identify to the SMTP server
            logger.info("Starting TLS encryption")
            server.starttls()  # Secure the connection
            server.ehlo()  # Re-identify over TLS connection
            
            # Detailed authentication logging
            try:
                logger.info(f"Attempting login with username: {creds['username']}")
                server.login(creds["username"], creds["password"])
                logger.info("Email authentication successful")
                st.info("✅ Email login successful")
            except smtplib.SMTPAuthenticationError as auth_err:
                error_msg = f"❌ Email authentication failed: {str(auth_err)}"
                logger.error(error_msg)
                st.error(error_msg)
                if creds["smtp_server"] == "smtp.gmail.com":
                    st.info("For Gmail, use an App Password instead of your regular password")
                return False
                
            # Send with more detailed error reporting
            try:
                logger.info(f"Sending email from {creds['username']} to {creds['recipient']}")
                server.sendmail(creds["username"], creds["recipient"], msg.as_string())
                success_msg = "📧 Email sent successfully"
                logger.info(success_msg)
                st.success(success_msg)
            except Exception as send_err:
                error_msg = f"❌ Failed to send email: {str(send_err)}"
                logger.error(error_msg)
                st.error(error_msg)
                return False
                
        return True
        
    except Exception as e:
        error_msg = f"❌ Failed to connect to email server: {str(e)}"
        logger.error(error_msg)
        st.error(error_msg)
        st.info("Check your SMTP server and port settings")
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
        try:
            os.unlink(temp_audio_file)
            logger.info(f"Temporary file removed: {temp_audio_file}")
        except Exception as e:
            logger.warning(f"Unable to remove temporary file: {str(e)}")
        
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
                st.markdown("""
                <div class="status-box alert">
                    <h3>⚠️ Failed to Send Alert</h3>
                    <p>Please check your email configuration and try again.</p>
                </div>
                """, unsafe_allow_html=True)
        else:
            status_placeholder.success("✅ Audio processed successfully. No distress detected.")
            
    except Exception as e:
        error_msg = f"❌ Error: {str(e)}"
        logger.error(error_msg)
        status_placeholder.error(error_msg)
    finally:
        st.session_state.processing = False

# --- Choose recording method ---
st.markdown('<div class="section"><h3>Audio Recording</h3></div>', unsafe_allow_html=True)

# Check for available recording methods
available_methods = ["File Upload"]
if WEBRTC_AVAILABLE and SOUNDDEVICE_AVAILABLE:
    available_methods.append("Browser Microphone (WebRTC)")

# Create a radio button to select the input method
st.markdown('<div class="method-selector">', unsafe_allow_html=True)
input_method = st.radio(
    "Choose recording method:",
    available_methods,
    index=0,  # Default to file upload which is more reliable
    help="File upload is the most reliable option across all environments"
)
st.markdown('</div>', unsafe_allow_html=True)

# --- File Uploader Option ---
if input_method == "File Upload" or len(available_methods) == 1:
    st.session_state.using_file_upload = True
    
    st.write("Upload an audio file for processing:")
    uploaded_file = st.file_uploader("Choose an audio file", type=['wav', 'mp3', 'm4a', 'ogg'])
    
    if uploaded_file is not None:
        audio_bytes = uploaded_file.getvalue()
        st.audio(audio_bytes, format=f"audio/{uploaded_file.type.split('/')[1]}")
        
        if st.button("Process Audio File"):
            if not st.session_state.processing:
                st.session_state.processing = True
                process_audio(audio_bytes)

# --- WebRTC Option ---
elif input_method == "Browser Microphone (WebRTC)" and WEBRTC_AVAILABLE and SOUNDDEVICE_AVAILABLE:
    st.session_state.using_file_upload = False
    
    # Create a status placeholder for recording status
    status_text = st.empty()
    if st.session_state.recording:
        status_text.info("🔴 Recording in progress...")
    else:
        status_text.info("🎤 Ready to record")
    
    # Custom AudioProcessor class
    class AudioProcessor:
        def __init__(self):
            self.frames = []
            self.audio_lock = threading.Lock()
            
        def recv(self, frame):
            """Process each audio frame"""
            with self.audio_lock:
                if st.session_state.recording:
                    # Lower the volume slightly to help with WebRTC clipping
                    sound = frame.to_ndarray().astype(np.float32) * 0.95
                    self.frames.append(sound)
            return frame
        
        def get_frames(self):
            """Get current frames and clear buffer"""
            with self.audio_lock:
                result = self.frames.copy()
                self.frames = []
            return result
    
    # Buttons to start/stop recording
    col1, col2 = st.columns(2)
    with col1:
        start_button = st.button("▶️ Start Recording")
    with col2:
        stop_button = st.button("⏹️ Stop Recording")
    
    # WebRTC Configuration - Optimized for better connectivity
    client_settings = ClientSettings(
        rtc_configuration={
            "iceServers": [
                {"urls": ["stun:stun.cloudflare.com:3478"]},  # Cloudflare STUN
                {"urls": ["stun:stun.l.google.com:19302"]},   # Google STUN
                {"urls": ["stun:stun1.l.google.com:19302"]},
                {"urls": ["stun:stun2.l.google.com:19302"]},
                {"urls": ["stun:stun.stunprotocol.org:3478"]},
                {"urls": ["stun:openrelay.metered.ca:80"]}    # Additional STUN servers
            ]
        },
        media_stream_constraints={
            "video": False,
            "audio": {
                "echoCancellation": True,
                "noiseSuppression": True,
                "autoGainControl": True
            }
        }
    )
    
    # Create audio processor
    audio_processor = AudioProcessor()
    
    # Enhanced WebRTC component with more diagnostics
    try:
        # Use a larger key to force reinitialization
        webrtc_ctx = webrtc_streamer(
            key="fixed-audio-recorder-v2",
            mode=WebRtcMode.SENDONLY,
            client_settings=client_settings,
            video_processor_factory=None,
            audio_processor_factory=lambda: audio_processor,
            async_processing=True,
            audio_receiver_size=128,  # Smaller buffer for better reliability
        )
        
        # WebRTC connection status and troubleshooting
        if webrtc_ctx.state.playing:
            st.success("✅ WebRTC connection established successfully")
            st.session_state.connection_attempt = False
        else:
            if st.session_state.connection_attempt:
                st.warning("⚠️ WebRTC connection is taking longer than expected.")
                st.info("📋 Try these fixes:")
                
                with st.expander("WebRTC Troubleshooting Tips"):
                    st.markdown("""
                    ### Fixing WebRTC Connection Issues
                    
                    1. **Browser Settings**:
                       - Ensure your browser has permission to access your microphone
                       - Try using Chrome, Edge, or Firefox (the most compatible browsers)
                       - Disable any browser extensions that might be blocking media access
                    
                    2. **Network Issues**:
                       - Disable VPN services if you're using them
                       - Connect to a different network if possible
                       - If on a corporate network, firewall settings might be blocking WebRTC
                    
                    3. **Try the file upload option** if WebRTC continues to fail
                    """)
                
                # Add a helpful switch to file upload button
                if st.button("Switch to file upload instead"):
                    st.session_state.using_file_upload = True
                    st.experimental_rerun()
                    
            st.session_state.connection_attempt = True
        
        # Handle button clicks for WebRTC
        if start_button:
            if webrtc_ctx.state.playing:
                st.session_state.recording = True
                status_text.info("🔴 Recording started...")
                logger.info("Recording started")
            else:
                st.error("❌ Cannot start recording. WebRTC connection not established.")
                logger.error("Failed to start recording - no WebRTC connection")
        
        if stop_button and st.session_state.recording:
            logger.info("Recording stopped. Processing audio...")
            st.session_state.recording = False
            status_text.info("⏹️ Recording stopped. Processing audio...")
            
            # Get recorded frames
            frames = audio_processor.get_frames()
            
            if frames and len(frames) > 0:
                logger.info(f"Processing {len(frames)} audio frames")
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
            else:
                st.warning("⚠️ No audio recorded. Please try again.")
                logger.warning("No audio frames collected during recording")
                
    except Exception as e:
        st.error(f"Error initializing WebRTC: {str(e)}")
        logger.error(f"WebRTC initialization error: {str(e)}")
        
        # Automatically offer file upload as fallback
        st.info("🔄 Switching to file upload mode due to WebRTC initialization error...")
        st.session_state.using_file_upload = True
        st.experimental_rerun()
# If neither WebRTC nor sounddevice is available
else:
    st.warning("⚠️ Browser microphone recording is not available in this environment due to missing dependencies.")
    st.info("Please use the File Upload option instead.")
    st.session_state.using_file_upload = True

# --- Test Alert Button ---
col1, col2 = st.columns(2)

with col2:
    # Test alert button
    if st.button("✉️ Test Alert Email"):
        if not (email_username and email_password and recipient_email):
            st.warning("⚠️ Please fill in all email credentials before testing.")
        else:
            logger.info("Sending test email alert")
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
       - Choose your preferred input method (File Upload or WebRTC)
       - For WebRTC: Click "Start Recording" to begin, then "Stop Recording" when done
       - For File Upload: Upload an audio file and click "Process Audio File"
    
    3. **Monitor Results**:
       - The system will transcribe your speech
       - If distress keywords are detected, an alert will be sent automatically
       
    4. **Distress Keywords**:
       The system listens for: help, sos, emergency, 911, save me, distress, assistance, trapped, danger
    """)

with st.expander("⚙️ Troubleshooting"):
    st.markdown("""
    ### Troubleshooting
    
    **WebRTC Connection Issues**
    - If you see "Taking a while to connect" messages, try the File Upload option instead
    - Try disabling VPN services or firewalls
    - Check that your browser allows microphone access
    - Use Chrome or Edge for better compatibility
    
    **Browser Microphone Issues**
    - Make sure your browser has permission to access your microphone
    - Check that your microphone is not being used by another application
    - Try refreshing the page or restarting your browser
    
    **Email Alerts Not Sending**
    - For Gmail: Make sure you're using an App Password, not your regular password
    - Check that your email and password are entered correctly
    - Try the "Test Alert Email" button to verify your settings
    
    **Audio Processing Issues**
    - Speak clearly and avoid background noise
    - Make sure your recording is at least 1-2 seconds long
    - If transcription fails, try recording again
    
    **Deployment Issues**
    - If direct microphone recording isn't available, the application will automatically
      show only the File Upload option
    - Try uploading pre-recorded audio files, which works in all environments
    """)

# --- Render.yaml Configuration Notice ---
with st.expander("🔧 Deployment Configuration"):
    st.markdown("""
    ### Render.yaml Configuration
    
    If you're deploying on Render, create a `render.yaml` file in your project root with the following content:
    
    ```yaml
    services:
      - type: web
        name: ai-passive-sos
        env: python
        buildCommand: pip install -r requirements.txt
        startCommand: streamlit run app.py
        envVars:
          - key: PYTHON_VERSION
            value: 3.11
        packages:
          - portaudio19-dev
          - python3-pyaudio
    ```
    
    This will install the necessary system dependencies for audio recording functionality.
    """)

# Footer
st.markdown("---")
st.markdown(
    """<div style="text-align: center; margin-top: 2rem; opacity: 0.7;">
        <p>AI Passive SOS | Enhanced Personal Safety System</p>
        <p>Created with ❤️ by the AI Passive SOS Team</p>
        <small>Powered by AssemblyAI for speech transcription</small>
    </div>
    """,
    unsafe_allow_html=True
)

# --- Extended testing and diagnostics (optional section) ---
if st.checkbox("Show Debug Information"):
    with st.expander("System Diagnostics"):
        st.write("### System Status")
        
        # Check internet connectivity
        internet_status = "Connected" if check_connectivity() else "Disconnected"
        st.write(f"🌐 Internet Connection: {internet_status}")
        
        # Check AssemblyAI API connectivity
        try:
            response = requests.get(
                "https://api.assemblyai.com/v2/transcript", 
                headers={"authorization": ASSEMBLYAI_API_KEY}
            )
            api_status = "Connected" if response.status_code == 200 else f"Error: Status {response.status_code}"
        except Exception as e:
            api_status = f"Error: {str(e)}"
        st.write(f"🔌 AssemblyAI API: {api_status}")
        
        # Check available recording methods
        st.write("🎙️ Available Recording Methods:")
        st.write(f"- Direct Recording via sounddevice: {'Available' if SOUNDDEVICE_AVAILABLE else 'Not Available'}")
        st.write(f"- WebRTC Recording: {'Available' if WEBRTC_AVAILABLE else 'Not Available'}")
        st.write(f"- File Upload: Always Available")
        
        # Show recent transcript
        if st.session_state.last_transcript:
            st.write("### Last Transcript")
            st.text_area("Text", st.session_state.last_transcript, height=150)
            
        # Clear session state button
        if st.button("Clear Session State"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.success("Session state cleared!")
            initialize_session_state()

# --- Prevent webcam from automatically starting ---
if 'has_initialized' not in st.session_state:
    st.session_state.has_initialized = True
    # Force a rerun to prevent auto-start of camera
    st.experimental_rerun()

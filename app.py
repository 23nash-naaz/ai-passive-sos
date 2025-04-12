from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import smtplib
import json
import os
import io
import numpy as np
import time
import threading
import sounddevice as sd
import soundfile as sf
import speech_recognition as sr
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variables for state management
CONFIG_FILE = "config.json"
KEYWORDS_FILE = "keywords.json"
is_recording = False
distress_detected = False
recording_thread = None
last_result = None

# Load configuration
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        "email_username": "",
        "email_password": "",
        "recipient_email": ""
    }

# Save configuration
def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

# Load keywords
def load_keywords():
    if os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, 'r') as f:
            return json.load(f).get("keywords", [])
    return ["help", "emergency", "stop", "danger", "fire", "hurt"]

# Save keywords
def save_keywords(keywords):
    with open(KEYWORDS_FILE, 'w') as f:
        json.dump({"keywords": keywords}, f)

# Initialize keywords if not exists
if not os.path.exists(KEYWORDS_FILE):
    save_keywords(["help", "emergency", "stop", "danger", "fire", "hurt"])

# Function to send email alert
def send_email_alert(detected_words):
    try:
        config = load_config()
        if not all([config.get("email_username"), config.get("email_password"), config.get("recipient_email")]):
            return False, "Email configuration incomplete"
        
        msg = MIMEMultipart()
        msg['From'] = config["email_username"]
        msg['To'] = config["recipient_email"]
        msg['Subject'] = "EMERGENCY ALERT - Distress Keywords Detected"
        
        body = f"""
        EMERGENCY ALERT
        
        Distress keywords have been detected through the Passive SOS system.
        
        Detected keywords: {', '.join(detected_words)}
        
        Time of detection: {time.strftime('%Y-%m-%d %H:%M:%S')}
        
        Please check on the person or contact emergency services if appropriate.
        
        This is an automated alert from the Passive SOS system.
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(config["email_username"], config["email_password"])
        text = msg.as_string()
        server.sendmail(config["email_username"], config["recipient_email"], text)
        server.quit()
        
        return True, "Alert email sent successfully"
    except Exception as e:
        return False, f"Failed to send email: {str(e)}"

# Audio processing function
def process_audio_data(audio_data_base64):
    global distress_detected, last_result
    
    try:
        # Decode base64 audio data
        audio_bytes = base64.b64decode(audio_data_base64)
        
        # Save to temporary file
        with open("temp_audio.wav", "wb") as f:
            f.write(audio_bytes)
        
        # Initialize recognizer
        r = sr.Recognizer()
        
        # Load audio file
        with sr.AudioFile("temp_audio.wav") as source:
            audio = r.record(source)
        
        # Recognize speech
        text = r.recognize_google(audio)
        
        # Check for distress keywords
        keywords = load_keywords()
        detected_words = []
        
        for keyword in keywords:
            if keyword.lower() in text.lower():
                detected_words.append(keyword)
        
        # If distress keywords detected, send alert
        alert_sent = False
        alert_message = ""
        
        if detected_words:
            distress_detected = True
            alert_sent, alert_message = send_email_alert(detected_words)
        
        # Prepare result
        result = {
            "text": text,
            "distress_detected": len(detected_words) > 0,
            "detected_words": detected_words,
            "alert_sent": alert_sent,
            "alert_message": alert_message
        }
        
        # Store last result
        last_result = result
        
        # Cleanup
        if os.path.exists("temp_audio.wav"):
            os.remove("temp_audio.wav")
        
        return result
    
    except sr.UnknownValueError:
        return {"error": "Speech Recognition could not understand the audio"}
    
    except sr.RequestError as e:
        return {"error": f"Could not request results from Speech Recognition service: {e}"}
    
    except Exception as e:
        return {"error": f"Error processing audio: {str(e)}"}

# Function to continuously record and process audio
def continuous_recording():
    global is_recording, distress_detected
    
    try:
        fs = 44100  # Sample rate
        duration = 5  # Seconds per recording
        
        while is_recording:
            # Record audio
            audio_data = sd.rec(int(duration * fs), samplerate=fs, channels=1)
            sd.wait()
            
            # Normalize and convert to base64
            audio_float32 = audio_data.astype(np.float32)
            if audio_float32.max() > 0:
                audio_float32 = audio_float32 / audio_float32.max()
            
            buffer = io.BytesIO()
            sf.write(buffer, audio_float32, fs, format='WAV')
            buffer.seek(0)
            audio_base64 = base64.b64encode(buffer.read()).decode('utf-8')
            
            # Process the audio
            result = process_audio_data(audio_base64)
            
            # If distress detected, stop recording and set flag
            if result.get("distress_detected", False):
                distress_detected = True
                is_recording = False
                break
    except Exception as e:
        print(f"Error in continuous recording: {str(e)}")
        is_recording = False

# API routes
@app.route('/api/status', methods=['GET'])
def get_status():
    global is_recording, distress_detected, last_result
    return jsonify({
        "is_recording": is_recording,
        "distress_detected": distress_detected,
        "last_result": last_result
    })

@app.route('/api/config', methods=['GET'])
def get_config():
    config = load_config()
    # Don't return password in response
    if "email_password" in config:
        config["email_password"] = "********" if config["email_password"] else ""
    return jsonify(config)

@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.get_json()
    config = load_config()
    
    if "email_username" in data:
        config["email_username"] = data["email_username"]
    if "email_password" in data:
        config["email_password"] = data["email_password"]
    if "recipient_email" in data:
        config["recipient_email"] = data["recipient_email"]
    
    save_config(config)
    return jsonify({"status": "success", "message": "Configuration updated successfully"})

@app.route('/api/test_email', methods=['POST'])
def test_email():
    try:
        success, message = send_email_alert(["TEST"])
        if success:
            return jsonify({"status": "success", "message": "Test email sent successfully"})
        else:
            return jsonify({"status": "error", "message": message})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/keywords', methods=['GET'])
def get_keywords():
    keywords = load_keywords()
    return jsonify({"keywords": keywords})

@app.route('/api/update_keywords', methods=['POST'])
def update_keywords():
    data = request.get_json()
    keywords = data.get("keywords", [])
    save_keywords(keywords)
    return jsonify({"status": "success", "message": "Keywords updated successfully"})

@app.route('/api/start_recording', methods=['POST'])
def start_recording():
    global is_recording, distress_detected, recording_thread
    
    if not is_recording:
        is_recording = True
        distress_detected = False
        recording_thread = threading.Thread(target=continuous_recording)
        recording_thread.daemon = True
        recording_thread.start()
        return jsonify({"status": "success", "message": "Recording started successfully"})
    else:
        return jsonify({"status": "error", "message": "Recording is already in progress"})

@app.route('/api/stop_recording', methods=['POST'])
def stop_recording():
    global is_recording
    
    if is_recording:
        is_recording = False
        return jsonify({"status": "success", "message": "Recording stopped successfully"})
    else:
        return jsonify({"status": "error", "message": "No recording in progress"})

@app.route('/api/process_audio', methods=['POST'])
def process_audio():
    data = request.get_json()
    audio_data = data.get("audio_data")
    
    if not audio_data:
        return jsonify({"status": "error", "message": "No audio data provided"}), 400
    
    try:
        result = process_audio_data(audio_data)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/record_audio', methods=['POST'])
def record_audio():
    try:
        data = request.get_json()
        duration = data.get('duration', 5)  # Default to 5 seconds if not specified
        
        # Record audio in the main thread (this is safe)
        fs = 44100  # Sample rate
        channels = 1  # Mono
        
        # Record audio
        audio_data = sd.rec(int(duration * fs), samplerate=fs, channels=channels)
        sd.wait()  # Wait until recording is finished
        
        # Normalize audio data
        audio_float32 = audio_data.astype(np.float32)
        if audio_float32.max() > 0:
            audio_float32 = audio_float32 / audio_float32.max()
        
        # Convert to base64
        buffer = io.BytesIO()
        sf.write(buffer, audio_float32, 44100, format='WAV')
        buffer.seek(0)
        audio_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        
        return jsonify({
            "status": "success",
            "message": f"Audio recorded for {duration} seconds",
            "audio_data": audio_base64
        })
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error recording audio: {str(e)}"
        }), 500

@app.route('/api/reset', methods=['POST'])
def reset_status():
    global distress_detected
    distress_detected = False
    return jsonify({"status": "success", "message": "Status reset successfully"})

# Run the app
if __name__ == '__main__':
    # Make sure required files exist
    if not os.path.exists(CONFIG_FILE):
        save_config({
            "email_username": "",
            "email_password": "",
            "recipient_email": ""
        })
    
    # Run without debug mode or reloader to avoid threading issues
    app.run(host='0.0.0.0', port=5000, debug=False)
    
    # Alternative if you need debug features but no reloader:
    # app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)

   


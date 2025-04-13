from flask import Flask, request, jsonify, send_from_directory
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
import logging
from waitress import serve

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Rest of your functions unchanged...

# Serve static files (if you have a frontend)
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    if path == "" or path == "/":
        return send_from_directory('static', 'index.html')
    return send_from_directory('static', path)

# All your existing API routes remain unchanged

# Run the app
if __name__ == '__main__':
    # Make sure required files exist
    if not os.path.exists(CONFIG_FILE):
        save_config({
            "email_username": "",
            "email_password": "",
            "recipient_email": ""
        })
    
    # Get port from environment variable (for deployment platforms)
    port = int(os.environ.get('PORT', 5000))
    
    # For development
    if os.environ.get('FLASK_ENV') == 'development':
        logger.info(f"Running in development mode on port {port}")
        app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
    # For production
    else:
        logger.info(f"Running in production mode on port {port}")
        serve(app, host='0.0.0.0', port=port)

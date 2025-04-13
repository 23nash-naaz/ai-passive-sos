import streamlit as st
import requests
import json
import base64
import time
import threading

# API endpoint configuration
API_BASE_URL = st.secrets.get("API_BASE_URL", "http://127.0.0.1:5000")  # Use Streamlit secrets for configuration

st.set_page_config(page_title="SOS API Tester", page_icon="🚨", layout="wide")

# App title and description
st.title("🚨 Passive SOS API Testing Interface")
st.markdown("""
This application allows you to test your Passive SOS API functionality without deploying to a production environment.
Configure settings, test audio processing, and monitor the system status all from this interface.
""")

# Sidebar for configuration
st.sidebar.header("Configuration")

# API URL Configuration
with st.sidebar.expander("API Configuration", expanded=True):
    api_url = st.text_input("API Base URL", value=API_BASE_URL)
    if api_url != API_BASE_URL:
        API_BASE_URL = api_url
        st.sidebar.success("API URL updated!")

# Email Configuration
with st.sidebar.expander("Email Settings", expanded=True):
    email_username = st.text_input("Email Username", placeholder="your.email@gmail.com")
    email_password = st.text_input("Email Password", type="password")
    recipient_email = st.text_input("Recipient Email", placeholder="alert.recipient@example.com")
    
    if st.button("Save Email Settings"):
        try:
            response = requests.post(
                f"{API_BASE_URL}/api/config",
                json={
                    "email_username": email_username,
                    "email_password": email_password,
                    "recipient_email": recipient_email
                }
            )
            if response.status_code == 200:
                st.sidebar.success("Email settings saved successfully!")
            else:
                st.sidebar.error(f"Failed to save settings: {response.text}")
        except Exception as e:
            st.sidebar.error(f"Error connecting to API: {str(e)}")
    
    if st.button("Test Email"):
        try:
            response = requests.post(f"{API_BASE_URL}/api/test_email")
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success":
                    st.sidebar.success("Test email sent successfully!")
                else:
                    st.sidebar.error(f"Failed to send test email: {result.get('message')}")
            else:
                st.sidebar.error(f"API error: {response.text}")
        except Exception as e:
            st.sidebar.error(f"Error connecting to API: {str(e)}")

# Distress Keywords
with st.sidebar.expander("Distress Keywords", expanded=True):
    try:
        response = requests.get(f"{API_BASE_URL}/api/keywords")
        if response.status_code == 200:
            keywords = response.json().get("keywords", [])
            keywords_text = st.text_area("Keywords (one per line)", 
                                        value="\n".join(keywords if keywords else []))
            
            if st.button("Update Keywords"):
                new_keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
                response = requests.post(
                    f"{API_BASE_URL}/api/update_keywords",
                    json={"keywords": new_keywords}
                )
                if response.status_code == 200:
                    st.sidebar.success("Keywords updated successfully!")
                else:
                    st.sidebar.error(f"Failed to update keywords: {response.text}")
        else:
            st.sidebar.error(f"Failed to fetch keywords: {response.text}")
    except Exception as e:
        st.sidebar.error(f"Error connecting to API: {str(e)}")
        st.sidebar.info("Enter keywords below and click 'Update Keywords' when API is available")
        keywords_text = st.text_area("Keywords (one per line)", value="help\nemergency\nhelp me")

# Main content area with tabs
tab1, tab2, tab3 = st.tabs(["Service Control", "Audio Testing", "System Status"])

# Tab 1: Service Control
with tab1:
    st.header("Passive SOS Service Control")
    
    # Get current status
    try:
        response = requests.get(f"{API_BASE_URL}/api/status")
        if response.status_code == 200:
            status = response.json()
            is_recording = status.get("is_recording", False)
            distress_detected = status.get("distress_detected", False)
            
            # Status indicators
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Recording Status", "Active" if is_recording else "Inactive")
            with col2:
                st.metric("Distress Detected", "YES" if distress_detected else "No")
            
            # Control buttons
            if is_recording:
                if st.button("Stop Recording", key="stop_btn"):
                    response = requests.post(f"{API_BASE_URL}/api/stop_recording")
                    if response.status_code == 200:
                        st.success("Recording stopped successfully!")
                        time.sleep(1)  # Small delay before rerunning
                        st.rerun()
                    else:
                        st.error(f"Failed to stop recording: {response.text}")
            else:
                if st.button("Start Recording", key="start_btn"):
                    response = requests.post(f"{API_BASE_URL}/api/start_recording")
                    if response.status_code == 200:
                        st.success("Recording started successfully!")
                        time.sleep(1)  # Small delay before rerunning
                        st.rerun()
                    else:
                        st.error(f"Failed to start recording: {response.text}")
        else:
            st.error(f"Failed to get status: {response.text}")
    except Exception as e:
        st.error(f"Error connecting to API: {str(e)}")
        st.warning("API connection failed. Please check if the API server is running and the URL is correct.")

    # Last processing result
    st.subheader("Last Processing Result")
    try:
        response = requests.get(f"{API_BASE_URL}/api/status")
        if response.status_code == 200:
            status = response.json()
            if "last_result" in status:
                last_result = status["last_result"]
                st.json(last_result)
            else:
                st.info("No processing results available yet.")
        else:
            st.error(f"Failed to get status: {response.text}")
    except Exception as e:
        st.error(f"Error connecting to API: {str(e)}")

# Tab 2: Audio Testing
with tab2:
    st.header("Audio Testing")
    st.markdown("""
    This section allows you to test the SOS API with audio input in two ways:
    1. Record audio through the API's microphone capabilities 
    2. Upload an audio file to test distress detection
    """)

    # Audio recording (Modified to use the API for recording)
    st.subheader("Record Audio")
    
    col1, col2 = st.columns(2)
    with col1:
        record_button = st.button("Request Audio Recording from API")
    with col2:
        record_duration = st.slider("Recording Duration (seconds)", 3, 15, 5)
    
    # Process the recorded audio
    if record_button:
        with st.spinner(f"Requesting API to record audio for {record_duration} seconds..."):
            try:
                # Request the API to record audio
                response = requests.post(
                    f"{API_BASE_URL}/api/record_audio",
                    json={"duration": record_duration}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "success":
                        st.success("Audio recorded successfully through the API!")
                        
                        # If API returns the audio data, we can process it
                        if "audio_data" in result:
                            audio_base64 = result["audio_data"]
                            
                            # Process the audio
                            try:
                                process_response = requests.post(
                                    f"{API_BASE_URL}/api/process_audio",
                                    json={"audio_data": audio_base64}
                                )
                                
                                if process_response.status_code == 200:
                                    process_result = process_response.json()
                                    st.subheader("Processing Result")
                                    st.json(process_result)
                                    
                                    # Highlight if distress was detected
                                    if process_result.get("result", {}).get("distress_detected", False):
                                        st.warning("⚠️ Distress keywords detected in the audio!")
                                        if process_result.get("result", {}).get("alert_sent", False):
                                            st.success("✅ Alert email was sent successfully!")
                                        else:
                                            st.error("❌ Alert email was not sent. Check email configuration.")
                                else:
                                    st.error(f"API error processing audio: {process_response.text}")
                            except Exception as e:
                                st.error(f"Error processing recorded audio: {str(e)}")
                    else:
                        st.error(f"Failed to record audio: {result.get('message')}")
                else:
                    st.error(f"API error: {response.text}")
            except Exception as e:
                st.error(f"Error connecting to API: {str(e)}")
    
    # File uploader for testing
    st.subheader("Upload Audio File")
    uploaded_file = st.file_uploader("Choose an audio file", type=["wav", "mp3"])
    
    if uploaded_file is not None:
        if st.button("Process Uploaded Audio"):
            with st.spinner("Processing uploaded audio..."):
                # Read the file and convert to base64
                audio_bytes = uploaded_file.read()
                audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
                
                # Send to API
                try:
                    response = requests.post(
                        f"{API_BASE_URL}/api/process_audio",
                        json={"audio_data": audio_base64}
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        st.subheader("Processing Result")
                        st.json(result)
                        
                        # Highlight if distress was detected
                        if result.get("result", {}).get("distress_detected", False):
                            st.warning("⚠️ Distress keywords detected in the audio!")
                            if result.get("result", {}).get("alert_sent", False):
                                st.success("✅ Alert email was sent successfully!")
                            else:
                                st.error("❌ Alert email was not sent. Check email configuration.")
                    else:
                        st.error(f"API error: {response.text}")
                except Exception as e:
                    st.error(f"Error connecting to API: {str(e)}")

# Tab 3: System Status
with tab3:
    st.header("System Status Monitor")
    
    # Status display
    st.subheader("Current System Status")
    status_placeholder = st.empty()
    
    # Function to update status
    def update_status():
        try:
            response = requests.get(f"{API_BASE_URL}/api/status")
            if response.status_code == 200:
                status = response.json()
                
                # Check if recording is active
                is_recording = status.get("is_recording", False)
                distress_detected = status.get("distress_detected", False)
                
                # Create status message
                status_message = st.container()
                with status_message:
                    col1, col2 = st.columns(2)
                    with col1:
                        if is_recording:
                            st.success("✅ Service is ACTIVE")
                        else:
                            st.error("❌ Service is INACTIVE")
                    with col2:
                        if distress_detected:
                            st.warning("⚠️ Distress has been detected!")
                        else:
                            st.info("No distress detected")
                
                # Display last result if available
                if "last_result" in status:
                    st.subheader("Latest Processing Result")
                    st.json(status["last_result"])
                
                # Get configuration
                try:
                    config_response = requests.get(f"{API_BASE_URL}/api/config")
                    if config_response.status_code == 200:
                        config = config_response.json()
                        
                        st.subheader("Configuration")
                        st.markdown(f"""
                        - **Email Username**: {config.get("email_username") or "Not configured"}
                        - **Recipient Email**: {config.get("recipient_email") or "Not configured"}
                        """)
                except Exception as e:
                    st.error(f"Error fetching configuration: {str(e)}")
                
                # Display keywords
                try:
                    keywords_response = requests.get(f"{API_BASE_URL}/api/keywords")
                    if keywords_response.status_code == 200:
                        keywords = keywords_response.json().get("keywords", [])
                        
                        st.subheader("Distress Keywords")
                        if keywords:
                            st.write(", ".join(keywords))
                        else:
                            st.write("No keywords configured")
                except Exception as e:
                    st.error(f"Error fetching keywords: {str(e)}")
                
                return True
            else:
                st.error(f"Failed to get status: {response.text}")
                return False
        except Exception as e:
            st.error(f"Error connecting to API: {str(e)}")
            return False
    
    # Initial status update
    status_updated = update_status()
    
    # Auto-refresh toggle
    auto_refresh = st.checkbox("Auto-refresh status (every 5 seconds)")
    
    # Create a placeholder for the countdown
    refresh_placeholder = st.empty()
    
    # Store the auto-refresh state in session state
    if 'auto_refresh' not in st.session_state:
        st.session_state.auto_refresh = False
        st.session_state.refresh_time = time.time()
    
    if auto_refresh != st.session_state.auto_refresh:
        st.session_state.auto_refresh = auto_refresh
        st.session_state.refresh_time = time.time()
    
    # Handle auto-refresh with a safer approach for Streamlit Cloud
    if auto_refresh:
        refresh_interval = 5  # seconds
        current_time = time.time()
        elapsed = current_time - st.session_state.refresh_time
        
        if elapsed >= refresh_interval:
            status_placeholder.empty()
            with status_placeholder:
                update_status()
            st.session_state.refresh_time = current_time
            
        remaining = max(0, refresh_interval - elapsed)
        refresh_placeholder.text(f"Refreshing in {int(remaining)} seconds...")
        time.sleep(1)  # Add a small delay for smoother updates
        st.rerun()
    else:
        if st.button("Refresh Status Now"):
            status_placeholder.empty()
            with status_placeholder:
                update_status()
            st.session_state.refresh_time = time.time()

# Footer
st.markdown("---")
st.markdown("SOS API Testing Interface | © 2025")

   


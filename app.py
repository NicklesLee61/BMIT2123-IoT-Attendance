import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime

# ==========================================
# 1. Basic configuration and Firebase initialization
# ==========================================
st.set_page_config(page_title="Smart Campus IoT Portal", layout="wide")
st.title("🎓 BMIT2123 Smart Campus Dashboard")

# Initialize Firebase (to prevent duplicate initialization)
if not firebase_admin._apps:
    try:
        # Local test path; it is recommended to use st.secrets during deployment.
        cred = credentials.Certificate("service-account-key.json")
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Firebase Connection failed: {e}")

# ==========================================
# 2.Sidebar: Reverse Control Commands
# ==========================================
st.sidebar.header("🕹️ IoT Control Panel")
control_ref = db.reference('/control')

# Function 1: Mode Switching
sys_mode = st.sidebar.selectbox("System Mode:", ["Attendance", "Enrollment"])
if st.sidebar.button("Update Mode"):
    control_ref.update({"mode": sys_mode})
    st.sidebar.success(f"Mode set to {sys_mode}")

# Function 2: Security Lock
is_locked = st.sidebar.toggle("🔒 Device Lock")
control_ref.update({"is_locked": is_locked})

# Function 3: Manual Override
st.sidebar.markdown("---")
manual_id = st.sidebar.text_input("Enter Student ID for Force Check-in:")
if st.sidebar.button("Force Mark Present"):
    if manual_id:
        # Write data directly to the attendance node to achieve "remote manual intervention".
        db.reference('/attendance').push().set({
            'student_id': manual_id,
            'name': "Manual_Admin_Override",
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'status': 'Present'
        })
        st.sidebar.warning(f"Manual check-in done for {manual_id}")

# ==========================================
# 3. Main page: Data reading and Pandas processing
# ==========================================
st.header("📊 Real-time Attendance Analytics")

#Reading data from Firebase
attendance_ref = db.reference('/attendance')
raw_data = attendance_ref.get()

if raw_data:
    # --- Core logic: JSON flattening ---
    # Convert Firebase nested dictionaries to lists, then to Pandas DataFrames.
    records = []
    for key, value in raw_data.items():
        if key != 'init': # Exclude initialization placeholders
            records.append(value)
    
    df = pd.DataFrame(records)
    
    # Use Pandas for simple cleaning (ensure the time format is correct).
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # --- Interface Layout ---
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Live Logs")
       # Display a table instead of Excel
        st.dataframe(df.sort_values(by='timestamp', ascending=False), use_container_width=True)
        
    with col2:
        st.subheader("Attendance Distribution")
       # Statistical analysis and chart generation
        status_counts = df['status'].value_counts()
        fig, ax = plt.subplots()
        ax.pie(status_counts, labels=status_counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#e74c3c'])
        st.pyplot(fig)

else:
    st.info("No logs found. Waiting for edge device signal...")
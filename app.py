import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime

# ==========================================
# 1. SYSTEM CONFIGURATION & CLOUD AUTH
# ==========================================
st.set_page_config(page_title="IoT Smart Campus Portal", layout="wide", page_icon="🎓")
st.title("🎓 BMIT2123: Smart Campus Admin Dashboard")

# Initialize Firebase using Cloud Secrets for security
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production Mode: Fetch credentials from Streamlit Secrets
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Development Mode: Local JSON file
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Cloud Connection Failed: {e}")
        st.stop()

# ==========================================
# 2. SIDEBAR: REMOTE IOT CONTROL
# ==========================================
st.sidebar.header("🕹️ IoT Command Center")
control_ref = db.reference('/control')

# Operation Mode Toggle
sys_mode = st.sidebar.selectbox("Operation Mode:", ["Attendance", "Enrollment"])
if st.sidebar.button("Push Mode Update"):
    control_ref.update({"mode": sys_mode})
    st.sidebar.success(f"Hardware set to {sys_mode}")

# Emergency Device Lock
is_locked = st.sidebar.toggle("🔒 Emergency Device Lock")
control_ref.update({"is_locked": is_locked})

# Manual Attendance Override
st.sidebar.markdown("---")
manual_id = st.sidebar.text_input("Manual Force Check-in (Student ID):")
if st.sidebar.button("Force Mark Present"):
    if manual_id:
        # Push to a specific date node or general attendance
        today_str = datetime.now().strftime("%Y-%m-%d")
        db.reference(f'/attendance/{today_str}').push().set({
            'student_id': str(manual_id),
            'name': "Admin_Override",
            'timestamp': int(datetime.now().timestamp()),
            'status': 'present'
        })
        st.sidebar.warning(f"Override sent for {manual_id}")

# ==========================================
# 3. DATA ANALYTICS: NESTED DATA PROCESSING
# ==========================================
st.header("📊 Real-time Attendance Analytics")

# Fetch nested JSON data from Firebase
raw_data = db.reference('/attendance').get()

if raw_data:
    all_records = []
    
    # Logic: Flattening the nested structure { "date": { "record_id": {data} } }
    for date_key, daily_records in raw_data.items():
        if isinstance(daily_records, dict):
            for record_id, record_data in daily_records.items():
                # Extract all fields (name, status, timestamp, etc.)
                all_records.append(record_data)
    
    if all_records:
        df = pd.DataFrame(all_records)
        
        # Data Cleaning: Convert Epoch timestamp (int) to Datetime object
        if 'timestamp' in df.columns:
            # Using unit='s' for standard Unix timestamps
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        
        # UI Layout: Table and Visualization
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("Live Logs")
            # Sort by latest time for better readability
            st.dataframe(df.sort_values(by='timestamp', ascending=False), use_container_width=True)
            
        with col2:
            st.subheader("Cloud Analytics")
            if 'status' in df.columns:
                # Replace Excel charts with real-time Matplotlib plots
                status_counts = df['status'].value_counts()
                fig, ax = plt.subplots()
                ax.pie(status_counts, labels=status_counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#e74c3c'])
                st.pyplot(fig)
    else:
        st.info("Awaiting formatted records from the edge device...")
else:
    st.info("No attendance nodes detected. Please verify your Raspberry Pi connection.")

import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime

# ==========================================
# 1. System Configuration & Cloud Auth
# ==========================================
st.set_page_config(page_title="IoT Smart Campus Portal", layout="wide", page_icon="🎓")
st.title("🎓 BMIT2123: Smart Campus Admin Dashboard")
st.markdown("Developed by: Lee Yee Xiang | Data Science & IoT Integration")

# Professional Firebase Initialization
if not firebase_admin._apps:
    try:
        # Priority: Check if running on Streamlit Cloud (using Secrets)
        if "firebase" in st.secrets:
            cred_dict = dict(st.secrets["firebase"])
            # TOML secrets handle newlines differently; this fix ensures connection
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Fallback: Local development using JSON file
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"⚠️ Cloud Connection Failed: {e}")

# ==========================================
# 2. Sidebar: Bi-directional IoT Control
# ==========================================
st.sidebar.header("🕹️ Remote Command Center")
control_ref = db.reference('/control')

# Feature A: Real-time Mode Switching
st.sidebar.subheader("System Settings")
sys_mode = st.sidebar.selectbox("Operation Mode:", ["Attendance", "Enrollment"])
if st.sidebar.button("Push Mode Update"):
    control_ref.update({"mode": sys_mode})
    st.sidebar.success(f"Hardware set to {sys_mode}")

# Feature B: Emergency Security Lock
is_locked = st.sidebar.toggle("🔒 Emergency Device Lock", help="Remotely disables all edge sensors.")
control_ref.update({"is_locked": is_locked})

# Feature C: Administrative Manual Override
st.sidebar.markdown("---")
st.sidebar.subheader("✍️ Manual Intervention")
manual_id = st.sidebar.text_input("Force Sign-in (Student ID):")
if st.sidebar.button("Force Mark Present"):
    if manual_id:
        db.reference('/attendance').push().set({
            'student_id': str(manual_id),
            'name': "Manual_Admin_Override",
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'status': 'Present'
        })
        st.sidebar.warning(f"Override pulse sent for {manual_id}")

# ==========================================
# 3. Main Analytics: Replacing Excel
# ==========================================
st.header("📊 Real-time Attendance Analytics")

# Fetch dynamic data from Cloud
attendance_ref = db.reference('/attendance')
raw_data = attendance_ref.get()

if raw_data:
    # --- Data Science Logic: JSON Flattening ---
    records = [v for k, v in raw_data.items() if k != 'init']
    df = pd.DataFrame(records)
    
    # Process timestamps for professional reporting
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Dashboard Layout
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Live Attendance Stream")
        # Direct dataframe rendering replaces static spreadsheets
        st.dataframe(
            df.sort_values(by='timestamp', ascending=False), 
            use_container_width=True,
            hide_index=True
        )
        
    with col2:
        st.subheader("Cloud Analytics")
        if not df.empty and 'status' in df.columns:
            # Automatic status distribution visualization
            status_counts = df['status'].value_counts()
            fig, ax = plt.subplots(figsize=(5, 5))
            ax.pie(status_counts, labels=status_counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#e74c3c'])
            st.pyplot(fig)
else:
    st.info("System is healthy. Awaiting hardware signals from edge devices...")

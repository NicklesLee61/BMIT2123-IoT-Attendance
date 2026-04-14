import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime, time as dt_time
import time

# ==========================================
# 1. SYSTEM CONFIG & CLOUD AUTHENTICATION
# ==========================================
st.set_page_config(page_title="IoT Smart Campus Portal", layout="wide", page_icon="🛡️")
st.title("🛡️ BMIT2123: All-in-One Smart Campus Management")

# Initialize Firebase securely using Streamlit Secrets or local JSON
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production: Streamlit Cloud Secrets
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local Development Mode
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Cloud Connection Failed: {e}"); st.stop()

# ==========================================
# 2. DATA PROCESSING ENGINE (Flattening & Logic)
# ==========================================
# Fetch dynamic data from Cloud
students_data = db.reference('/students').get() or {} # Profile Database
attendance_raw = db.reference('/attendance').get()   # Attendance Logs

all_records = []
if attendance_raw:
    # Logic: Flattening nested Firebase structure { "date": { "id": {data} } }
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for record_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{record_id}"
                info['record_date'] = date_key
                all_records.append(info)

df = pd.DataFrame(all_records)

# Feature: Auto-Late Detection Logic
if not df.empty:
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', errors='coerce')
    # Official class start time set to 09:00 AM
    CLASS_START = dt_time(9, 0)
    df['arrival_status'] = df['timestamp'].apply(
        lambda x: "Late" if x.time() > CLASS_START else "On-Time"
    )

# ==========================================
# 3. SIDEBAR: ADMIN COMMAND CENTER
# ==========================================
st.sidebar.title("🎮 Command Center")

# --- MODULE A: REMOTE HARDWARE CONTROL ---
with st.sidebar.expander("🛠️ Hardware Controls", expanded=False):
    sys_mode = st.selectbox("Device Mode:", ["Attendance", "Enrollment"])
    if st.button("Apply Mode"): db.reference('/control/mode').set(sys_mode)
    
    lock_status = st.toggle("🔒 Emergency System Lock")
    db.reference('/control/is_locked').set(lock_status)
    
    if st.button("🔔 Trigger Remote Bell"):
        db.reference('/control/trigger_buzzer').set(True)
        time.sleep(1); db.reference('/control/trigger_buzzer').set(False)

# --- MODULE B: 2FA ENROLLMENT (STUDENT PROFILES) ---
with st.sidebar.expander("👤 Student Registration / FP Mapping", expanded=False):
    reg_id = st.text_input("Student ID (Unique):")
    reg_name = st.text_input("Full Name:")
    reg_rfid = st.text_input("RFID Card UID:")
    # Mapping Fingerprint ID stored on R307 sensor
    reg_fpid = st.number_input("Sensor Fingerprint ID (1-127):", min_value=1, max_value=127, step=1)
    
    if st.button("Sync Profile to Cloud"):
        if reg_id and reg_name:
            db.reference(f'/students/{reg_id}').update({
                "student_id": reg_id, "name": reg_name, "card_id": reg_rfid,
                "fingerprint_id": reg_fpid, "registered_date": datetime.now().isoformat()
            })
            st.sidebar.success(f"Profile for {reg_id} updated!"); st.rerun()

# --- MODULE C: ATTENDANCE MANAGEMENT ---
with st.sidebar.expander("📝 Manual Logs & Deletion", expanded=False):
    # Manual Add
    target_student = st.selectbox("Manual Sign-in:", list(students_data.keys())) if students_data else None
    if st.button("Force Mark Present") and target_student:
        today_str = datetime.now().strftime("%Y-%m-%d")
        db.reference(f'/attendance/{today_str}').push().set({
            'student_id': target_student, 'name': students_data[target_student].get('name', 'N/A'),
            'status': 'present', 'timestamp': int(time.time()), 'date': today_str, 'verification_method': "Manual"
        }); st.rerun()
    
    st.markdown("---")
    # Delete Record
    if not df.empty:
        df['del_label'] = df['record_date'] + " | " + df['name']
        to_del = st.selectbox("Select Record to Erase:", df['del_label'].tolist())
        if st.button("🗑️ Confirm Delete"):
            path = df[df['del_label'] == to_del]['firebase_path'].values[0]
            db.reference(f'/attendance/{path}').delete(); st.rerun()

# ==========================================
# 4. MAIN INTERFACE: TABS & ANALYTICS
# ==========================================
tab_monitor, tab_analytics = st.tabs(["📺 Live Monitoring", "📈 Advanced Insights & EDA"])

# --- TAB 1: LIVE MONITORING ---
with tab_monitor:
    c1, c2, c3 = st.columns(3)
    c1.metric("Registered Students", len(students_data))
    c2.metric("Total Logs Count", len(df))
    c3.metric("System Status", "🔒 LOCKED" if lock_status else "🟢 ACTIVE")

    st.markdown("---")
    col_logs, col_pie = st.columns([2, 1])
    with col_logs:
        st.subheader("📋 Real-time Logs (with Auto-Late Detection)")
        if not df.empty:
            st.dataframe(df[['timestamp', 'name', 'arrival_status', 'student_id', 'status']]
                         .sort_values(by='timestamp', ascending=False), use_container_width=True)
    with col_pie:
        st.subheader("Cloud Statistics")
        if not df.empty:
            counts = df['status'].value_counts()
            fig, ax = plt.subplots()
            ax.pie(counts, labels=counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#f1c40f', '#e74c3c'])
            st.pyplot(fig)

# --- TAB 2: ADVANCED INSIGHTS (DATA SCIENCE MODULE) ---
with tab_analytics:
    st.header("🔍 Deep Campus Insights")
    
    # Feature 1: Absence Alert (Set Difference Logic)
    st.subheader("🚩 Missing Students Today")
    today_date = datetime.now().strftime("%Y-%m-%d")
    all_uids = set(students_data.keys())
    present_today_uids = set(df[df['record_date'] == today_date]['student_id'].unique()) if not df.empty else set()
    missing_ids = all_uids - present_today_uids
    
    if missing_ids:
        st.error(f"Alert: {len(missing_ids)} students have not checked in today.")
        st.write(f"Missing IDs: {', '.join(missing_ids)}")
    else:
        st.success("Perfect Attendance for Today!")

    st.markdown("---")

    # Feature 3: Peak Check-in Hours (EDA Trend Analysis)
    st.subheader("⏰ Peak Activity Trends")
    if not df.empty:
        df['hour'] = df['timestamp'].dt.hour
        st.bar_chart(df.groupby('hour').size())
        st.caption("Use this chart to identify peak arrival windows for campus resource planning.")

    st.markdown("---")

    # Feature 2: Individual Student Archive (Drill-down)
    st.subheader("🔎 Student History Lookup")
    target = st.selectbox("Inspect Student ID:", ["Select ID"] + list(students_data.keys()))
    if target != "Select ID":
        personal = df[df['student_id'] == target]
        if not personal.empty:
            # Calculate Consistency
            days_campus_active = len(df['record_date'].unique())
            attendance_rate = (len(personal['record_date'].unique()) / days_active) * 100 if days_active > 0 else 0
            st.metric(f"Loyalty/Consistency for {target}", f"{attendance_rate:.1f}%")
            st.table(personal[['timestamp', 'status', 'arrival_status']].sort_values(by='timestamp', ascending=False))
        else: st.info("No records found for this student.")

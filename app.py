import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime
import time

# ==========================================
# 1. SYSTEM CONFIG & CLOUD AUTHENTICATION
# ==========================================
st.set_page_config(page_title="IoT Smart Campus Portal", layout="wide", page_icon="🛡️")
st.title("🛡️ BMIT2123: All-in-One Smart Campus Management")

# Initialize Firebase securely
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Cloud Connection Failed: {e}"); st.stop()

# ==========================================
# 2. DATA PROCESSING ENGINE
# ==========================================
# Fetch dynamic data from Cloud
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Flattening nested Firebase structure
all_records = []
if attendance_raw:
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for record_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{record_id}"
                info['record_date'] = date_key
                all_records.append(info)

df = pd.DataFrame(all_records)
if not df.empty:
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', errors='coerce')

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

# --- MODULE B: 2FA ENROLLMENT (CARDS & FINGERPRINT) ---
with st.sidebar.expander("👤 Register New Card/Student", expanded=False):
    reg_id = st.text_input("Student ID (Unique):")
    reg_name = st.text_input("Full Name:")
    reg_rfid = st.text_input("RFID Card UID:")
    reg_course = st.text_input("Course Name:")
    reg_fpid = st.number_input("Sensor Fingerprint ID (1-127):", min_value=1, max_value=127, step=1)
    
    if st.button("Sync Profile to Cloud"):
        if reg_id and reg_name:
            db.reference(f'/cards/{reg_rfid}').update({
                "student_id": reg_id, "name": reg_name, "card_id": reg_rfid,
                "course": reg_course, "fingerprint_id": reg_fpid,
                "registered_date": datetime.now().isoformat()
            })
            db.reference(f'/students/{reg_id}').update({
                "student_id": reg_id, "name": reg_name, "rfid": reg_rfid, "course": reg_course
            })
            st.sidebar.success(f"Profile for {reg_id} updated!"); st.rerun()

# --- MODULE C: ATTENDANCE MANAGEMENT ---
with st.sidebar.expander("📝 Manual Logs & Deletion", expanded=True):
    st.subheader("Manual Record Entry")
    target_student = st.selectbox("Select Student:", list(students_data.keys())) if students_data else None
    target_status = st.selectbox("Set Status:", ["present", "absent", "late"])
    
    if st.button("Confirm Manual Log") and target_student:
        today_str = datetime.now().strftime("%Y-%m-%d")
        db.reference(f'/attendance/{today_str}').push().set({
            'student_id': target_student, 
            'name': students_data[target_student].get('name', 'N/A'),
            'status': target_status, 'timestamp': int(time.time()), 'date': today_str, 
            'verification_method': "Manual_Override"
        }); st.rerun()
    
    st.markdown("---")
    if not df.empty:
        df['del_label'] = df['record_date'] + " | " + df['name']
        to_del = st.selectbox("Select Attendance to Erase:", df['del_label'].tolist())
        if st.button("🗑️ Confirm Delete Attendance"):
            path = df[df['del_label'] == to_del]['firebase_path'].values[0]
            db.reference(f'/attendance/{path}').delete(); st.rerun()

# ==========================================
# 4. MAIN INTERFACE: TABS & ANALYTICS
# ==========================================
tab_monitor, tab_cards, tab_analytics = st.tabs(["📺 Live Monitoring", "💳 Card & Biometric DB", "📈 Advanced Insights"])

# --- TAB 1: LIVE MONITORING ---
with tab_monitor:
    m1, m2, m3 = st.columns(3)
    m1.metric("Students Registered", len(students_data))
    m2.metric("Total Attendance Logs", len(df))
    m3.metric("System Security", "🔒 LOCKED" if lock_status else "🟢 ACTIVE")

    st.markdown("---")
    col_logs, col_pie = st.columns([2, 1])
    with col_logs:
        st.subheader("📋 Real-time Logs")
        if not df.empty:
            # Removed 'arrival_status' column
            st.dataframe(df[['timestamp', 'name', 'status', 'student_id']]
                         .sort_values(by='timestamp', ascending=False), use_container_width=True)
    with col_pie:
        st.subheader("Cloud Statistics")
        if not df.empty:
            counts = df['status'].value_counts()
            fig, ax = plt.subplots()
            ax.pie(counts, labels=counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#f1c40f', '#e74c3c'])
            st.pyplot(fig)

# --- TAB 2: CARD & BIOMETRIC DATABASE ---
with tab_cards:
    st.header("📇 Physical Card & Fingerprint Registry")
    if cards_data:
        cards_list = [v for k, v in cards_data.items()]
        st.dataframe(pd.DataFrame(cards_list), use_container_width=True)
        st.markdown("---")
        card_to_del = st.selectbox("Select Card ID to unregister:", [c['card_id'] for c in cards_list])
        if st.button("Delete Card Mapping"):
            db.reference(f'/cards/{card_to_del}').delete(); st.rerun()
    else:
        st.info("No physical cards are currently registered.")

# --- TAB 3: ADVANCED INSIGHTS ---
with tab_analytics:
    st.header("🔍 Deep Campus Insights")
    
    # Feature 1: Absence Alert
    st.subheader("🚩 Missing Students Today")
    today_date = datetime.now().strftime("%Y-%m-%d")
    all_uids = set(students_data.keys())
    present_today_uids = set(df[(df['record_date'] == today_date) & (df['status'] != 'absent')]['student_id'].unique()) if not df.empty else set()
    missing_ids = all_uids - present_today_uids
    
    if missing_ids:
        st.error(f"Alert: {len(missing_ids)} students have not checked in today.")
        st.write(f"Missing IDs: {', '.join(missing_ids)}")
    else:
        st.success("Perfect Attendance for Today!")

    st.markdown("---")

    # Feature 2: Peak Check-in Hours
    st.subheader("⏰ Peak Activity Trends")
    if not df.empty:
        df['hour'] = df['timestamp'].dt.hour
        st.bar_chart(df.groupby('hour').size())

    st.markdown("---")

    # Feature 3: Student History Lookup
    st.subheader("🔎 Student History Lookup")
    target = st.selectbox("Select ID to inspect:", ["Select ID"] + list(students_data.keys()))
    if target != "Select ID":
        personal = df[df['student_id'] == target]
        if not personal.empty:
            days_active = len(df['record_date'].unique())
            attendance_rate = (len(personal[personal['status'] != 'absent']['record_date'].unique()) / days_active) * 100 if days_active > 0 else 0
            st.metric(f"Attendance Rate for {target}", f"{attendance_rate:.1f}%")
            # Removed 'arrival_status' from the table
            st.table(personal[['timestamp', 'status']].sort_values(by='timestamp', ascending=False))


import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime
import time

# ==========================================
# 1. SYSTEM CONFIG & AUTH
# ==========================================
st.set_page_config(page_title="IoT Command Center", layout="wide", page_icon="🛡️")
st.title("🛡️ BMIT2123: All-in-One Smart Campus Management")

# Professional Firebase Initialization
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production: Fetch from Streamlit Cloud Secrets
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local: Use local JSON key
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Database Connection Failed: {e}")
        st.stop()

# ==========================================
# 2. DATA PROCESSING ENGINE
# ==========================================
# Fetching Attendance Records
attendance_raw = db.reference('/attendance').get()
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
    # Convert epoch to readable datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', errors='coerce')

# Fetching Student Database
students_ref = db.reference('/students')
students_data = students_ref.get() or {}

# ==========================================
# 3. SIDEBAR: MANAGEMENT MODULES
# ==========================================
st.sidebar.title("🎮 Admin Control Panel")

# --- MODULE 1: HARDWARE REMOTE CONTROL ---
with st.sidebar.expander("🛠️ Hardware Commands", expanded=False):
    sys_mode = st.selectbox("Operation Mode:", ["Attendance", "Enrollment"])
    if st.button("Update Mode"):
        db.reference('/control').update({"mode": sys_mode})
        st.success(f"Hardware set to {sys_mode}")
    
    is_locked = st.toggle("🔒 System Lockdown")
    db.reference('/control').update({"is_locked": is_locked})

# --- MODULE 2: STUDENT REGISTRATION (NEW!) ---
with st.sidebar.expander("👤 Student Registration / Update", expanded=False):
    st.write("Register new students or update existing profiles.")
    reg_id = st.text_input("Student ID (e.g., personA):")
    reg_name = st.text_input("Full Name:")
    reg_rfid = st.text_input("RFID UID:")
    reg_course = st.text_input("Course (e.g., Data Science):")
    
    if st.button("Save Student Profile"):
        if reg_id and reg_name:
            # Upsert logic: Update if exists, create if new
            students_ref.child(reg_id).update({
                "student_id": reg_id,
                "name": reg_name,
                "rfid": reg_rfid,
                "course": reg_course,
                "registered_date": datetime.now().isoformat(),
                "attendance_count": students_data.get(reg_id, {}).get("attendance_count", 0)
            })
            st.success(f"Profile for {reg_id} synced to cloud!")
            st.rerun()

# --- MODULE 3: ATTENDANCE OVERRIDE ---
with st.sidebar.expander("📝 Manual Attendance Log", expanded=False):
    manual_id = st.selectbox("Select Student:", list(students_data.keys())) if students_data else None
    manual_status = st.selectbox("Status:", ["present", "late", "absent"])
    if st.button("Mark Attendance") and manual_id:
        today_str = datetime.now().strftime("%Y-%m-%d")
        db.reference(f'/attendance/{today_str}').push().set({
            'student_id': manual_id,
            'name': students_data[manual_id].get('name', 'Unknown'),
            'status': manual_status,
            'timestamp': int(time.time()),
            'date': today_str,
            'verification_method': "Admin_Manual"
        })
        st.toast(f"Logged {manual_id} as {manual_status}")
        st.rerun()

# --- MODULE 4: RECORD DELETION ---
with st.sidebar.expander("🗑️ Delete Record", expanded=False):
    if not df.empty:
        df['delete_label'] = df['record_date'] + " | " + df['name']
        to_del = st.selectbox("Choose record:", df['delete_label'].tolist())
        if st.button("Confirm Delete"):
            path = df[df['delete_label'] == to_del]['firebase_path'].values[0]
            db.reference(f'/attendance/{path}').delete()
            st.warning("Record erased.")
            st.rerun()

# ==========================================
# 4. MAIN DASHBOARD: ANALYTICS
# ==========================================
m1, m2, m3 = st.columns(3)
m1.metric("Students Registered", len(students_data))
m2.metric("Total Logs", len(df))
m3.metric("System Status", "🔒 LOCKED" if is_locked else "🟢 ACTIVE")

st.markdown("---")
if not df.empty:
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("📋 Real-time Logs")
        st.dataframe(df[['timestamp', 'name', 'status', 'student_id', 'verification_method']]
                     .sort_values(by='timestamp', ascending=False), use_container_width=True)
    with c2:
        st.subheader("📊 Statistics")
        counts = df['status'].value_counts()
        fig, ax = plt.subplots()
        ax.pie(counts, labels=counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#f1c40f', '#e74c3c'])
        st.pyplot(fig)
else:
    st.info("System is ready and connected to Firebase Cloud.")

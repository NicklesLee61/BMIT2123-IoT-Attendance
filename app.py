import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime, time as dt_time
import time

# ==========================================
# 1. SYSTEM CONFIG & AUTHENTICATION
# ==========================================
st.set_page_config(page_title="IoT Smart Campus Portal", layout="wide", page_icon="🛡️")
st.title("🛡️ BMIT2123: Advanced Smart Campus Management")

# Professional Firebase Initialization with Secrets handling
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production Mode: Streamlit Cloud
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
        st.error(f"Database Connection Failed: {e}")
        st.stop()

# ==========================================
# 2. DATA PROCESSING ENGINE
# ==========================================
# Fetching Students Metadata
students_data = db.reference('/students').get() or {}

# Fetching Attendance Records & Data Flattening
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

# Feature 4: Auto-Late Logic
if not df.empty:
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', errors='coerce')
    # Set official class start time (e.g., 09:00 AM)
    CLASS_START = dt_time(9, 0)
    df['arrival_status'] = df['timestamp'].apply(
        lambda x: "Late" if x.time() > CLASS_START else "On-Time"
    )

# ==========================================
# 3. SIDEBAR: CONTROL & MANAGEMENT
# ==========================================
st.sidebar.title("🎮 Admin Control Panel")

# --- Module 1: Hardware Commands ---
with st.sidebar.expander("🛠️ Hardware Commands", expanded=False):
    sys_mode = st.selectbox("Operation Mode:", ["Attendance", "Enrollment"])
    if st.button("Update Mode"):
        db.reference('/control').update({"mode": sys_mode})
        st.sidebar.success(f"Hardware set to {sys_mode}")
    
    is_locked = st.toggle("🔒 System Lockdown")
    db.reference('/control').update({"is_locked": is_locked})
    
    # Extra: Remote Buzzer Trigger
    if st.button("🔔 Trigger Class Bell"):
        db.reference('/control').update({"trigger_buzzer": True})
        time.sleep(1)
        db.reference('/control').update({"trigger_buzzer": False})

# --- Module 2: Student Registration ---
with st.sidebar.expander("👤 Student Management", expanded=False):
    reg_id = st.text_input("Student ID (Unique):")
    reg_name = st.text_input("Name:")
    if st.button("Save Profile"):
        if reg_id and reg_name:
            db.reference(f'/students/{reg_id}').update({
                "student_id": reg_id, "name": reg_name, "registered_date": datetime.now().isoformat()
            })
            st.sidebar.success(f"Profile for {reg_id} synced!")
            st.rerun()

# --- Module 3: Attendance Override ---
with st.sidebar.expander("📝 Manual Attendance Log", expanded=False):
    manual_id = st.selectbox("Select Student:", list(students_data.keys())) if students_data else None
    if st.button("Mark Present Now") and manual_id:
        today_str = datetime.now().strftime("%Y-%m-%d")
        db.reference(f'/attendance/{today_str}').push().set({
            'student_id': manual_id,
            'name': students_data[manual_id].get('name', 'Unknown'),
            'status': 'present',
            'timestamp': int(time.time()),
            'date': today_str,
            'verification_method': "Admin_Manual"
        })
        st.rerun()

# --- Module 4: Record Deletion ---
with st.sidebar.expander("🗑️ Delete Record", expanded=False):
    if not df.empty:
        df['delete_label'] = df['record_date'] + " | " + df['name']
        to_del = st.selectbox("Choose record:", df['delete_label'].tolist())
        if st.button("🗑️ Confirm Delete"):
            path = df[df['delete_label'] == to_del]['firebase_path'].values[0]
            db.reference(f'/attendance/{path}').delete()
            st.rerun()

# ==========================================
# 4. MAIN INTERFACE: TABS SYSTEM
# ==========================================
tab_monitor, tab_analytics = st.tabs(["📺 Real-time Monitoring", "📈 Advanced Data Insights"])

# --- TAB 1: REAL-TIME MONITORING ---
with tab_monitor:
    m1, m2, m3 = st.columns(3)
    m1.metric("Students Registered", len(students_data))
    m2.metric("Total Logs", len(df))
    m3.metric("System Security", "🔒 LOCKED" if is_locked else "🟢 ACTIVE")

    st.markdown("---")
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("📋 Live Logs (with Auto-Late Detection)")
        if not df.empty:
            st.dataframe(df[['timestamp', 'name', 'status', 'arrival_status', 'student_id']]
                         .sort_values(by='timestamp', ascending=False), use_container_width=True)
    with c2:
        st.subheader("📊 Statistics")
        if not df.empty:
            counts = df['status'].value_counts()
            fig, ax = plt.subplots()
            ax.pie(counts, labels=counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#f1c40f', '#e74c3c'])
            st.pyplot(fig)

# --- TAB 2: ADVANCED ANALYTICS (EDA) ---
with tab_analytics:
    st.header("🔍 Deeper Campus Insights")
    
    # Feature 1: Absence Alert (Set Logic)
    st.subheader("🚩 Missing Students Today")
    today_date = datetime.now().strftime("%Y-%m-%d")
    all_enrolled_ids = set(students_data.keys())
    present_today_ids = set(df[df['record_date'] == today_date]['student_id'].unique()) if not df.empty else set()
    absent_ids = all_enrolled_ids - present_today_ids
    
    if absent_ids:
        st.error(f"Alert: {len(absent_ids)} students are missing from today's sessions.")
        st.write(f"Missing IDs: {', '.join(absent_ids)}")
    else:
        st.success("Perfect Attendance! All registered students have checked in.")

    st.markdown("---")

    # Feature 3: Hourly Check-in Trend (Heatmap/Bar Chart)
    st.subheader("⏰ Peak Check-in Hours")
    if not df.empty:
        df['hour'] = df['timestamp'].dt.hour
        hourly_data = df.groupby('hour').size()
        st.bar_chart(hourly_data)
        st.caption("Identify peak traffic hours to optimize campus management.")

    st.markdown("---")

    # Feature 2: Student Profile Lookup
    st.subheader("🔎 Individual Student Archive")
    target_id = st.selectbox("Select Student ID to inspect:", ["None"] + list(students_data.keys()))
    if target_id != "None":
        personal_history = df[df['student_id'] == target_id]
        if not personal_history.empty:
            st.write(f"Showing historical attendance for: **{target_id}**")
            # Calculate consistency rate
            days_active = len(df['record_date'].unique())
            attendance_rate = (len(personal_history['record_date'].unique()) / days_active) * 100
            st.metric("Attendance Consistency", f"{attendance_rate:.1f}%")
            st.table(personal_history[['timestamp', 'status', 'arrival_status']].sort_values(by='timestamp', ascending=False))
        else:
            st.info("No historical logs found for this student ID.")

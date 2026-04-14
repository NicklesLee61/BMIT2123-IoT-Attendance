import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime
import time

# ==========================================
# 1. SYSTEM AUTHENTICATION
# ==========================================
st.set_page_config(page_title="IoT Admin Command Center", layout="wide", page_icon="🛡️")
st.title("🛡️ BMIT2123: Professional IoT & Biometric Management")

# Initialize Firebase using Secrets for Cloud Deployment
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production: Streamlit Cloud Secrets
            cred_dict = dict(st.secrets["firebase"])
            # Essential: Handle the \n in private_key
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local Development
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Cloud Connection Failed: {e}"); st.stop()

# ==========================================
# 2. DATA ENGINE (Logic Flattening)
# ==========================================
# Fetching metadata from Firebase nodes
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process Nested Attendance Logs
all_records = []
if attendance_raw:
    # Flatten structure: { "date": { "record_id": {data} } }
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for record_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{record_id}"
                info['record_date'] = date_key
                all_records.append(info)

df = pd.DataFrame(all_records)
if not df.empty:
    # Convert Epoch integer to Datetime object
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', errors='coerce')

# ==========================================
# 3. SIDEBAR: REMOTE CONTROL
# ==========================================
st.sidebar.title("🎮 Command Center")

with st.sidebar.expander("🛠️ Hardware Commands", expanded=False):
    # Mode selection logic
    sys_mode = st.selectbox("Operation Mode:", ["Attendance", "Enrollment"])
    if st.button("Push Mode Update"): 
        db.reference('/control/mode').set(sys_mode)
    
    # Emergency Lockdown
    is_locked = st.toggle("🔒 Emergency Device Lock")
    db.reference('/control/is_locked').set(is_locked)
    
    # Remote Buzzer Trigger
    if st.button("🔔 Trigger Remote Bell"):
        db.reference('/control/trigger_buzzer').set(True)
        time.sleep(1); db.reference('/control/trigger_buzzer').set(False)

# ==========================================
# 4. MAIN INTERFACE: TABS SYSTEM
# ==========================================
tab_monitor, tab_mgmt, tab_analytics = st.tabs(["📺 Live Monitoring", "🗃️ Registry Management", "📈 Insights"])

# --- TAB 1: LIVE MONITORING ---
with tab_monitor:
    m1, m2, m3 = st.columns(3)
    m1.metric("Students Registered", len(students_data))
    m2.metric("Total Attendance Logs", len(df))
    m3.metric("System Status", "🔒 LOCKED" if is_locked else "🟢 ACTIVE")

    st.markdown("---")
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("📋 Real-time Logs")
        if not df.empty:
            # Table visualization
            st.dataframe(df[['timestamp', 'name', 'status', 'student_id']]
                         .sort_values(by='timestamp', ascending=False), use_container_width=True)
    with c2:
        st.subheader("Cloud Analytics")
        if not df.empty:
            counts = df['status'].value_counts()
            fig, ax = plt.subplots()
            ax.pie(counts, labels=counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#f1c40f', '#e74c3c'])
            st.pyplot(fig)

# --- TAB 2: PROFESSIONAL REGISTRY MGMT ---
with tab_mgmt:
    st.header("🗃️ Biometric & Card Registry")
    
    # Advanced stats
    occupied_fpid = [v.get('fingerprint_id') for k, v in cards_data.items() if v.get('fingerprint_id')]
    col_a, col_b = st.columns(2)
    col_a.info(f"Stored Fingerprints: {len(occupied_fpid)} / 127")
    col_b.info(f"Next Suggested ID: {(max(occupied_fpid)+1) if occupied_fpid else 1}")

    st.markdown("---")
    
    # Console-style management actions
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("➕ 7. Add RFID + Fingerprint Record")
        with st.form("add_student"):
            new_id = st.text_input("Student ID (e.g., 24WMR15298):")
            new_name = st.text_input("Full Name:")
            new_rfid = st.text_input("RFID UID:")
            new_course = st.text_input("Course Name:")
            new_fpid = st.number_input("Sensor Fingerprint ID (1-127):", 
                                       min_value=1, max_value=127, 
                                       value=(max(occupied_fpid)+1 if occupied_fpid else 1))
            if st.form_submit_button("Execute Registration"):
                if new_id and new_rfid:
                    # Sync to /cards and /students nodes
                    db.reference(f'/cards/{new_rfid}').update({
                        "student_id": new_id, "name": new_name, "card_id": new_rfid,
                        "course": new_course, "fingerprint_id": new_fpid,
                        "registered_date": datetime.now().isoformat()
                    })
                    db.reference(f'/students/{new_id}').update({
                        "student_id": new_id, "name": new_name, "rfid": new_rfid, "course": new_course
                    })
                    st.success(f"Synced {new_name} to slot #{new_fpid}!"); st.rerun()

    with col2:
        st.subheader("🗑️ Delete Operations")
        # Console Option 2: Delete by FP ID
        del_fpid = st.number_input("2. Delete fingerprint by ID:", min_value=1, max_value=127)
        if st.button("Execute FP ID Delete"):
            target_cards = [k for k, v in cards_data.items() if v.get('fingerprint_id') == del_fpid]
            for c in target_cards: db.reference(f'/cards/{c}').delete()
            st.warning(f"ID #{del_fpid} cleared."); st.rerun()
            
        st.markdown("---")
        # Console Option 5: Delete by Selection
        if not df.empty:
            st.subheader("📝 Manual Log Management")
            target_sid = st.selectbox("Select Student for Manual Log:", list(students_data.keys()))
            target_status = st.selectbox("Status:", ["present", "absent", "late"])
            if st.button("Confirm Manual Override"):
                t_str = datetime.now().strftime("%Y-%m-%d")
                db.reference(f'/attendance/{t_str}').push().set({
                    'student_id': target_sid, 'name': students_data[target_sid].get('name', 'N/A'),
                    'status': target_status, 'timestamp': int(time.time()), 'date': t_str, 
                    'verification_method': "Manual_Admin"
                }); st.rerun()

    st.markdown("---")
    # Console Option 4: Show All Records
    st.subheader("4. Show all RFID records")
    if cards_data:
        # Replicating the list format: card_id => [name, card_id, flag, fingerprint_id]
        display_list = []
        for uid, v in cards_data.items():
            display_list.append({
                "Output Format": f"{uid} => ['{v.get('name')}', '{uid}', 0, {v.get('fingerprint_id')}]",
                "Name": v.get('name'),
                "Course": v.get('course'),
                "Finger_ID": v.get('fingerprint_id')
            })
        st.table(pd.DataFrame(display_list))

# --- TAB 3: ANALYTICS (Data Science) ---
with tab_analytics:
    st.header("🔍 Campus Data Intelligence")
    
    # 🚩 Today's Absence Alert
    st.subheader("🚩 Missing Students Today")
    today = datetime.now().strftime("%Y-%m-%d")
    all_uids = set(students_data.keys())
    present_today = set(df[(df['record_date'] == today) & (df['status'] != 'absent')]['student_id'].unique()) if not df.empty else set()
    missing = all_uids - present_today
    if missing:
        st.error(f"{len(missing)} students are missing today. IDs: {', '.join(missing)}")
    else: st.success("100% Attendance!")

    st.markdown("---")
    # ⏰ Hourly Trends
    st.subheader("⏰ Peak Activity Trend")
    if not df.empty:
        df['hour'] = df['timestamp'].dt.hour
        st.bar_chart(df.groupby('hour').size())

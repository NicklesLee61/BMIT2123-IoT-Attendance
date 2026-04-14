import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime
import time

# ==========================================================
# 1. SYSTEM AUTHENTICATION & INITIALIZATION
# ==========================================================
st.set_page_config(page_title="IoT Command Center", layout="wide", page_icon="🛡️")
st.title("🛡️ BMIT2123: Professional Biometric & RFID Management")

# Initialize Firebase with Streamlit Secrets
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            cred_dict = dict(st.secrets["firebase"])
            # Fix newline handling for private keys
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Cloud Connection Failed: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE: FETCHING & SORTING
# ==========================================================
# Fetch primary data nodes from Firebase
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Attendance Flattening Logic
all_records = []
if attendance_raw:
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for record_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{record_id}"
                info['record_date'] = date_key
                all_records.append(info)
df_attendance = pd.DataFrame(all_records)
if not df_attendance.empty:
    df_attendance['timestamp'] = pd.to_datetime(df_attendance['timestamp'], unit='s', errors='coerce')

# ==========================================================
# 3. SIDEBAR: REMOTE HARDWARE COMMANDS
# ==========================================================
st.sidebar.title("🎮 Command Center")
with st.sidebar.expander("🛠️ Hardware Controls", expanded=False):
    sys_mode = st.selectbox("Operation Mode:", ["Attendance", "Enrollment"])
    if st.button("Apply Mode"): db.reference('/control/mode').set(sys_mode)
    is_locked = st.toggle("🔒 Emergency Device Lock")
    db.reference('/control/is_locked').set(is_locked)
    if st.button("🔔 Trigger Remote Bell"):
        db.reference('/control/trigger_buzzer').set(True)
        time.sleep(1); db.reference('/control/trigger_buzzer').set(False)

# ==========================================================
# 4. MAIN INTERFACE: TABS SYSTEM
# ==========================================================
tab_monitor, tab_mgmt, tab_analytics = st.tabs(["📺 Live Monitoring", "🗃️ Registry Management", "📈 Insights"])

# --- TAB 1: LIVE MONITORING ---
with tab_monitor:
    st.subheader("📋 Real-time Logs")
    if not df_attendance.empty:
        st.dataframe(df_attendance[['timestamp', 'name', 'status', 'student_id']]
                     .sort_values(by='timestamp', ascending=False), use_container_width=True)
    else: st.info("Waiting for hardware signals...")

# --- TAB 2: UNIFIED REGISTRY MANAGEMENT (SORTED BY STUDENT ID) ---
with tab_mgmt:
    st.header("🗃️ Student Biometric Registry")
    
    # Process Registry Data for combined display
    if cards_data:
        registry_list = []
        for card_uid, val in cards_data.items():
            registry_list.append({
                "Student ID": val.get('student_id', 'N/A'),
                "Full Name": val.get('name', 'N/A'),
                "Fingerprint ID": val.get('fingerprint_id', 'N/A'),
                "RFID UID": card_uid,
                "Course": val.get('course', 'N/A')
            })
        
        # 1. Logic: Sort by Student ID
        reg_df = pd.DataFrame(registry_list).sort_values(by="Student ID")
        
        # 2. Unified Display
        st.subheader("Master Student List (Sorted by Student ID)")
        st.dataframe(reg_df, use_container_width=True)

        st.markdown("---")
        # Management Actions
        c_add, c_del = st.columns(2)
        with c_add:
            st.subheader("➕ Enroll New Record")
            with st.form("enroll_student"):
                new_sid = st.text_input("Student ID:")
                new_name = st.text_input("Name:")
                new_rfid = st.text_input("RFID UID:")
                new_course = st.text_input("Course:")
                # Flexible input for Fingerprint ID to avoid "garbled" constraints
                new_fpid = st.text_input("Assign Fingerprint ID (Hardware Slot):")
                if st.form_submit_button("Sync to Cloud"):
                    if new_sid and new_rfid:
                        db.reference(f'/cards/{new_rfid}').update({
                            "student_id": new_sid, "name": new_name, "card_id": new_rfid,
                            "course": new_course, "fingerprint_id": new_fpid,
                            "registered_date": datetime.now().isoformat()
                        })
                        db.reference(f'/students/{new_sid}').update({
                            "student_id": new_sid, "name": new_name, "rfid": new_rfid, "course": new_course
                        })
                        st.success(f"Profile {new_sid} Updated!"); st.rerun()
        
        with c_del:
            st.subheader("🗑️ Remove Records")
            del_id = st.selectbox("Select Student ID to remove mapping:", reg_df['Student ID'].tolist())
            if st.button("Delete Hardware Mapping"):
                # Find card UID linked to this Student ID to delete from /cards
                card_to_del = reg_df[reg_df['Student ID'] == del_id]['RFID UID'].values[0]
                db.reference(f'/cards/{card_to_del}').delete()
                st.warning(f"Mapping for {del_id} removed."); st.rerun()
    else:
        st.info("No records found. Please enroll a user via the sidebar.")

# --- TAB 3: INSIGHTS (DATA SCIENCE) ---
with tab_analytics:
    st.header("🔍 Campus Data Intelligence")
    st.subheader("🚩 Missing Students (Today)")
    today = datetime.now().strftime("%Y-%m-%d")
    all_uids = set(students_data.keys())
    present_today = set(df_attendance[(df_attendance['record_date'] == today) & (df_attendance['status'] != 'absent')]['student_id'].unique()) if not df_attendance.empty else set()
    missing = all_uids - present_today
    if missing:
        st.error(f"Missing Students: {', '.join(missing)}")
    else: st.success("All students are accounted for today.")

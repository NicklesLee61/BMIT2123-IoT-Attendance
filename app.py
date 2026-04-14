import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime
import time
import io

# ==========================================================
# 1. SYSTEM CONFIGURATION & CLOUD AUTHENTICATION
# ==========================================================
st.set_page_config(page_title="IoT Command Center", layout="wide", page_icon="🛡️")
st.title("🛡️ BMIT2123: Master Command & Analytics Portal")

# Secure Initialization using Streamlit Secrets
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production environment: Cloud Secrets
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local development environment
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Cloud Connection Failed: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE: FETCHING & PROCESSING
# ==========================================================
# Fetching metadata from Firebase
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process Nested Attendance Logs into a flat list
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
    # Remote mode selection for Raspberry Pi
    sys_mode = st.selectbox("Operation Mode:", ["Attendance", "Enrollment"])
    if st.button("Apply Mode"): 
        db.reference('/control/mode').set(sys_mode)
    
    # Remote system lockdown
    is_locked = st.toggle("🔒 Emergency Device Lock")
    db.reference('/control/is_locked').set(is_locked)
    
    # Remote bell trigger
    if st.button("🔔 Trigger Remote Bell"):
        db.reference('/control/trigger_buzzer').set(True)
        time.sleep(1); db.reference('/control/trigger_buzzer').set(False)

# ==========================================================
# 4. MAIN INTERFACE: PROFESSIONAL TABS SYSTEM
# ==========================================================
tab_monitor, tab_registry, tab_reporting = st.tabs([
    "📺 Live Monitoring", 
    "🗃️ Registry Management", 
    "📊 Module 3: Analytics & Reporting"
])

# --- TAB 1: LIVE MONITORING (2FA Validation) ---
with tab_monitor:
    st.subheader("📋 Real-time Logs (Business Rule Validation)")
    if not df_attendance.empty:
        # Display logs with verification_method to ensure validation rules
        st.dataframe(df_attendance[['timestamp', 'name', 'status', 'student_id', 'verification_method']]
                     .sort_values(by='timestamp', ascending=False), use_container_width=True)
    else: st.info("Waiting for hardware synchronization...")

# --- TAB 2: REGISTRY MGMT (Student ID Sorting) ---
with tab_registry:
    st.header("🗃️ Unified Student & Biometric Registry")
    
    if cards_data:
        # Merging card and student metadata for unified view
        reg_list = []
        for card_uid, val in cards_data.items():
            reg_list.append({
                "Student ID": val.get('student_id', 'N/A'),
                "Full Name": val.get('name', 'N/A'),
                "Fingerprint Slot": val.get('fingerprint_id', 'N/A'),
                "RFID UID": card_uid,
                "Course": val.get('course', 'N/A')
            })
        
        # LOGIC: Strict sorting by Student ID
        reg_df = pd.DataFrame(reg_list).sort_values(by="Student ID")
        st.subheader("Master List (Sorted by Student ID)")
        st.dataframe(reg_df, use_container_width=True)

        st.markdown("---")
        # Enrollment Section: Fixes 'garbled' ID by allowing manual input
        with st.expander("➕ Enroll / Update Student Mapping"):
            with st.form("enroll_form"):
                n_id = st.text_input("Student ID (e.g., 24WMR15298):")
                n_name = st.text_input("Name:")
                n_rfid = st.text_input("RFID UID (Scan on Pi first):")
                n_course = st.text_input("Course:")
                n_fpid = st.text_input("Fingerprint Hardware ID (Slot #):")
                
                if st.form_submit_button("Sync to Cloud"):
                    if n_id and n_rfid:
                        # Sync both hardware and profile nodes
                        db.reference(f'/cards/{n_rfid}').update({
                            "student_id": n_id, "name": n_name, "card_id": n_rfid,
                            "course": n_course, "fingerprint_id": n_fpid,
                            "registered_date": datetime.now().isoformat()
                        })
                        db.reference(f'/students/{n_id}').update({
                            "student_id": n_id, "name": n_name, "rfid": n_rfid, "course": n_course
                        })
                        st.success(f"Profile {n_id} updated successfully!"); st.rerun()

# --- TAB 3: DATA ANALYTICS & REPORTING (Module 3) ---
with tab_reporting:
    st.header("📊 Module 3: Advanced Reporting Interface")
    
    if not df_attendance.empty:
        # 3.1 Attendance Visualization
        col_charts, col_summary = st.columns([2, 1])
        with col_charts:
            st.subheader("Daily Attendance Trend")
            status_counts = df_attendance['status'].value_counts()
            fig, ax = plt.subplots()
            ax.bar(status_counts.index, status_counts.values, color=['#2ecc71', '#f1c40f', '#e74c3c'])
            st.pyplot(fig)
        
        with col_summary:
            # Automated Absence Alert
            st.subheader("🚩 Today's Absence Alert")
            today_str = datetime.now().strftime("%Y-%m-%d")
            all_uids = set(students_data.keys())
            # Logic: Only count students marked 'present' or 'late' as present
            present_ids = set(df_attendance[(df_attendance['record_date'] == today_str) & (df_attendance['status'] != 'absent')]['student_id'].unique())
            missing = all_uids - present_ids
            if missing: st.error(f"Missing Students: {', '.join(missing)}")
            else: st.success("100% Attendance for today!")

        st.markdown("---")
        
        # 3.2 Admin Reporting: Manual Status Modification
        st.subheader("📝 Manual Report Adjustment (Medical Leave / Corrections)")
        with st.form("manual_correction"):
            m_sid = st.selectbox("Select Student:", list(students_data.keys()))
            m_status = st.selectbox("Adjustment:", ["present", "late", "absent (Medical Leave)", "absent"])
            if st.form_submit_button("Submit Corrected Report"):
                t_key = datetime.now().strftime("%Y-%m-%d")
                db.reference(f'/attendance/{t_key}').push().set({
                    'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                    'status': m_status, 'timestamp': int(time.time()), 'date': t_key,
                    'verification_method': "Admin_Manual_Override"
                }); st.success(f"Report adjusted for {m_sid}"); st.rerun()

        st.markdown("---")
        
        # 3.3 Permanent Record-Keeping: Firebase to Excel
        st.subheader("💾 Permanent Record-Keeping (Excel Sync)")
        st.write("Bridging cloud data to a formatted Excel sheet for advanced calculation.")
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df_attendance[['timestamp', 'name', 'student_id', 'status', 'verification_method']].to_excel(writer, index=False, sheet_name='BMIT2123_Logs')
            writer.close()
        
        st.download_button(
            label="📥 Download Official Attendance Report (.xlsx)",
            data=buffer.getvalue(),
            file_name=f"Attendance_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.ms-excel"
        )
    else:
        st.info("Insufficient data for reporting. Sync hardware sensors to populate logs.")

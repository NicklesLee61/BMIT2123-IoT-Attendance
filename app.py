import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime
import time
import io

# ==========================================================
# 1. SYSTEM INITIALIZATION & SECURE AUTH
# ==========================================================
st.set_page_config(page_title="IoT Master Command", layout="wide", page_icon="🛡️")

# Securely initialize Firebase using Streamlit Secrets
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production environment: Fetch from Streamlit Cloud Secrets
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local Dev: Use local JSON key
            cred = credentials.Certificate("service-account-key.json")
        firebase_admin.initialize_app(cred, {'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'})
    except Exception as e:
        st.error(f"Database Initialization Failed: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE: REAL-TIME SYNC & DEFENSIVE LOGIC
# ==========================================================
# Fetch primary data nodes from Firebase
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

# Process attendance logs with formatted time strings for Module 3
all_records = []
if attendance_raw:
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for rec_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{rec_id}"
                info['record_date'] = date_key
                all_records.append(info)

df_attendance = pd.DataFrame(all_records)
if not df_attendance.empty:
    # Logic: Convert unix epoch to STRING to prevent Excel format issues
    df_attendance['formatted_time'] = pd.to_datetime(df_attendance['timestamp'], unit='s', errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')

# ==========================================================
# 3. SIDEBAR: REMOTE HARDWARE COMMANDS
# ==========================================================
st.sidebar.title("🎮 Master Control Center")
st.sidebar.markdown(f"**Current System Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Operations", expanded=True):
    # Mode Switch: Attendance vs Enrollment
    target_mode = st.selectbox("Switch Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Apply Mode Update"):
        control_ref.update({"mode": target_mode})
        st.sidebar.success(f"Mode set to {target_mode}"); st.rerun()
    
    # Emergency Lockdown Toggle
    is_locked = st.sidebar.toggle("🔒 Sensor Lock", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})
    
    # Remote Buzzer Trigger for Alerts
    if st.sidebar.button("🔔 Trigger Remote Bell"):
        control_ref.update({"trigger_buzzer": True})
        time.sleep(1); control_ref.update({"trigger_buzzer": False})

# ==========================================================
# 4. MAIN INTERFACE: PROFESSIONAL TABS SYSTEM
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

tab_monitor, tab_registry, tab_reporting = st.tabs([
    "📺 Live Monitoring", 
    "🗃️ Registry Management", 
    "📊 Module 3: Reporting & Analytics"
])

# --- TAB 1: LIVE MONITORING (Real-time Validation) ---
with tab_monitor:
    st.subheader("📋 Real-time Logs (Business Rule Validation Check)")
    if not df_attendance.empty:
        # Satisfaction of Module 3: Validation display
        st.dataframe(df_attendance[['formatted_time', 'name', 'status', 'student_id', 'verification_method']]
                     .sort_values('formatted_time', ascending=False), use_container_width=True)
    else: st.warning("Hardware is active. Waiting for student entry signals...")

# --- TAB 2: REGISTRY MGMT (Student ID Sorting & Deletion) ---
with tab_registry:
    st.header("🗃️ Master Biometric Registry")
    
    if cards_data:
        # Logic: Convert to list and Reindex to handle missing fingerprint data
        reg_df = pd.DataFrame(list(cards_data.values()))
        expected_cols = ['student_id', 'name', 'card_id', 'fingerprint_id', 'course']
        reg_df = reg_df.reindex(columns=expected_cols).fillna("N/A")
        
        # LOGIC: Strict sorting by Student ID for professional use
        st.subheader("Master Student List (Sorted by ID)")
        st.dataframe(reg_df.sort_values("student_id"), use_container_width=True)

        st.markdown("---")
        # Enrollment Section: Uses alphanumeric tokens for Fingerprint
        c_reg, c_del = st.columns(2)
        with c_reg:
            st.subheader("➕ Enroll New Record")
            with st.form("enroll_form"):
                n_id = st.text_input("Student ID (Unique):")
                n_name = st.text_input("Full Name:")
                n_rfid = st.text_input("RFID UID (12-digit):")
                n_course = st.text_input("Course Name:")
                n_fpid = st.text_input("Biometric Token (Alphanumeric):") # Fixed input logic
                if st.form_submit_button("Sync Profile to Cloud"):
                    if n_id and n_rfid:
                        # Dual-node synchronization
                        db.reference(f'/cards/{n_rfid}').update({"student_id": n_id, "name": n_name, "fingerprint_id": n_fpid, "card_id": n_rfid, "course": n_course, "registered_date": datetime.now().isoformat()})
                        db.reference(f'/students/{n_id}').update({"name": n_name, "rfid": n_rfid, "course": n_course})
                        st.success(f"Profile {n_id} successfully mapped!"); st.rerun()

        with c_del:
            # FEATURE: Logical Deletion of Student Records
            st.subheader("🗑️ Delete Student Record")
            if students_data:
                del_id = st.selectbox("Select ID to remove mapping:", sorted(students_data.keys()))
                if st.button("Permanently Remove from Registry"):
                    # Logic: Find RFID from student profile to clean both nodes
                    linked_card = students_data[del_id].get('rfid')
                    if linked_card: db.reference(f'/cards/{linked_card}').delete()
                    db.reference(f'/students/{del_id}').delete()
                    st.warning(f"Student {del_id} and all linked biometric mappings cleared."); st.rerun()
    else:
        st.info("Registry is currently empty. Switch to Enrollment Mode to add students.")

# --- TAB 3: MODULE 3 (Reporting, Analysis & Excel Bridge) ---
with tab_reporting:
    st.header("📊 Module 3: Advanced Reporting Interface")
    st.markdown("---")
    
    if not df_attendance.empty:
        # 3.1 Data Analysis & Visualization (Inside Web App)
        col_charts, col_summary = st.columns([2, 1])
        with col_charts:
            st.subheader("Attendance Distribution Analysis")
            status_counts = df_attendance['status'].value_counts()
            fig, ax = plt.subplots()
            ax.bar(status_counts.index, status_counts.values, color=['#2ecc71', '#f1c40f', '#e74c3c'])
            st.pyplot(fig)
            st.caption("Visual distribution of current lecture status.")
        
        with col_summary:
            # Logic: Automatic Absence Alert via set difference
            st.subheader("🚩 Today's Absence Alert")
            all_uids = set(students_data.keys())
            present_today = set(df_attendance[df_attendance['status'] != 'absent']['student_id'].unique())
            missing = all_uids - present_today
            if missing: st.error(f"Students Missing ({len(missing)}): {', '.join(missing)}")
            else: st.success("All students are accounted for today!")

        st.markdown("---")
        # 3.2 Automated Reporting: Manual Correction (Medical Leave)
        st.subheader("📝 Manual Status Correction (e.g., Medical Leave)")
        with st.form("manual_report"):
            m_sid = st.selectbox("Select Student:", list(students_data.keys()))
            m_status = st.selectbox("Adjustment Status:", ["present", "late", "absent (Medical Leave)", "absent"])
            if st.form_submit_button("Submit Corrected Report"):
                today_key = datetime.now().strftime("%Y-%m-%d")
                db.reference(f'/attendance/{today_key}').push().set({
                    'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                    'status': m_status, 'timestamp': int(time.time()), 'date': today_key,
                    'verification_method': "Manual_Admin_Adjustment"
                }); st.success("Manual report synced!"); st.rerun()

        st.markdown("---")
        # 3.3 Permanent Record Bridge: Firebase to Excel Sync
        st.subheader("💾 Permanent Record-Keeping (Excel Export)")
        st.write("Bridging Firebase data to a professional report for advanced archival.")
        
        # Prepare clean data for export
        export_df = df_attendance[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].copy()
        export_df.rename(columns={'formatted_time': 'Timestamp (Sync)'}, inplace=True)
        
        buffer = io.BytesIO()
        # Uses 'xlsxwriter' to satisfy bridge requirement
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            export_df.to_excel(writer, index=False, sheet_name='Official_Report')
            writer.close()
        
        st.download_button(
            label="📥 Download Official Excel Report (.xlsx)",
            data=buffer.getvalue(),
            file_name=f"BMIT2123_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.ms-excel"
        )
    else:
        st.info("No attendance records found for analysis. Ensure hardware is active and syncing logs.")

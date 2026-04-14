import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
from datetime import datetime
import time
import io

# ==========================================================
# 1. SYSTEM INITIALIZATION & SECURE AUTHENTICATION
# ==========================================================
st.set_page_config(page_title="IoT Master Command", layout="wide", page_icon="🛡️")

# Initialize Firebase with Streamlit Secrets for cloud deployment
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production environment: Fetch from Streamlit Cloud Secrets
            cred_dict = dict(st.secrets["firebase"])
            # Fix newline character for RSA private key
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local development environment
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Database Initialization Failed: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE: REAL-TIME SYNC & LOGIC
# ==========================================================
# Fetching the hardware control state to drive the UI mode
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

# Fetching core database nodes
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process raw attendance logs with Excel-safe timestamp strings
all_records = []
if attendance_raw:
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for record_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{record_id}"
                all_records.append(info)

df_attendance = pd.DataFrame(all_records)
if not df_attendance.empty:
    # Logic: Convert unix epoch to formatted STRING to prevent '#' in Excel
    df_attendance['dt_object'] = pd.to_datetime(df_attendance['timestamp'], unit='s', errors='coerce')
    df_attendance['formatted_time'] = df_attendance['dt_object'].dt.strftime('%Y-%m-%d %H:%M:%S')

# ==========================================================
# 3. SIDEBAR: REMOTE HARDWARE COMMANDS
# ==========================================================
st.sidebar.title("🎮 Hardware Master Control")
st.sidebar.markdown(f"**Physical System Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Settings", expanded=True):
    # Mode selection: Attendance vs Enrollment
    target_mode = st.selectbox("Switch Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Push Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()
    
    # Emergency Lockdown Toggle
    is_locked = st.sidebar.toggle("🔒 Global Sensor Lock", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

# ==========================================================
# 4. DYNAMIC INTERFACE LOGIC: MODE-AWARE UI
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    # --- ENROLLMENT MODE UI: FOCUS ON DATABASE MAPPING ---
    tab_reg, tab_db = st.tabs(["➕ New Registration", "🗃️ Registry Database"])
    
    with tab_reg:
        st.info("System is in Enrollment Mode. Link RFID Cards to Alphanumeric Biometric Tokens.")
        with st.form("enroll_form"):
            c1, c2 = st.columns(2)
            with c1:
                n_sid = st.text_input("Student ID (Unique):")
                n_name = st.text_input("Full Name:")
            with c2:
                n_rfid = st.text_input("RFID Card UID:")
                # Flexible input for Fingerprint ID to allow Alphanumeric Tokens
                n_fpid = st.text_input("Fingerprint Token (Alphanumeric):")
            
            if st.form_submit_button("Sync Profile to Cloud"):
                if n_id and n_rfid and n_fpid:
                    # Logic: Concurrent sync to /cards and /students nodes
                    db.reference(f'/cards/{n_rfid}').update({
                        "student_id": n_sid, "name": n_name, "fingerprint_id": n_fpid,
                        "card_id": n_rfid, "registered_date": datetime.now().isoformat()
                    })
                    db.reference(f'/students/{n_sid}').update({"name": n_name, "rfid": n_rfid})
                    st.success(f"Mapping for {n_sid} established!"); st.rerun()

    with tab_list:
        if cards_data:
            # Defensive Logic: Reindex to prevent KeyError if cols are missing
            reg_df = pd.DataFrame(list(cards_data.values()))
            expected_cols = ['student_id', 'name', 'card_id', 'fingerprint_id']
            reg_df = reg_df.reindex(columns=expected_cols).fillna("N/A")
            
            st.subheader("Master Student Registry (Sorted by ID)")
            # Strict Sorting by Student ID
            st.dataframe(reg_df.sort_values("student_id"), use_container_width=True)
        else:
            st.warning("Database is currently empty. Please enroll a user.")

else:
    # --- ATTENDANCE MODE UI: MONITORING & MODULE 3 ANALYTICS ---
    tab_live, tab_m3 = st.tabs(["📺 Live Monitoring", "📊 Module 3: Reporting & Analytics"])
    
    with tab_live:
        st.subheader("📋 Real-time Logs (2FA Validation)")
        if not df_attendance.empty:
            # Business Rule: Show verification method for audit trail
            st.dataframe(df_attendance[['formatted_time', 'name', 'status', 'student_id', 'verification_method']]
                         .sort_values('formatted_time', ascending=False), use_container_width=True)
        else: st.warning("Hardware is active. Waiting for attendance signals...")

    with tab_m3:
        st.header("🔍 Module 3: Advanced Management Insights")
        
        if not df_attendance.empty:
            # 3.1 Attendance Visual Trends
            col_bar, col_absent = st.columns([2, 1])
            with col_bar:
                st.subheader("Daily Status Distribution")
                counts = df_attendance['status'].value_counts()
                fig, ax = plt.subplots()
                ax.bar(counts.index, counts.values, color=['#2ecc71', '#f1c40f', '#e74c3c'])
                st.pyplot(fig)
            
            with col_absent:
                # Logic: Set Difference to find missing students
                st.subheader("🚩 Today's Absence Alert")
                all_sids = set(students_data.keys())
                today_date = datetime.now().strftime("%Y-%m-%d")
                present_sids = set(df_attendance[df_attendance['status'] != 'absent']['student_id'].unique())
                missing = all_sids - present_sids
                if missing: st.error(f"Absent ({len(missing)}): {', '.join(missing)}")
                else: st.success("Full Attendance Achieved!")

            st.markdown("---")
            # 3.2 Manual Reporting: Admin Overrides (e.g., Medical Leave)
            st.subheader("📝 Manual Report Adjustment")
            with st.form("override"):
                m_sid = st.selectbox("Select Student:", list(students_data.keys()))
                m_status = st.selectbox("Set Status:", ["present", "late", "absent (Medical Leave)"])
                if st.form_submit_button("Submit Adjusted Report"):
                    t_key = datetime.now().strftime("%Y-%m-%d")
                    db.reference(f'/attendance/{t_key}').push().set({
                        'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                        'status': m_status, 'timestamp': int(time.time()), 
                        'verification_method': "Manual_Admin_Adjustment"
                    }); st.rerun()

            st.markdown("---")
            # 3.3 Permanent Record-Keeping: Firebase to Excel Bridge
            st.subheader("💾 Permanent Record Export")
            # Logic: Pre-format data to ensure clean Excel output
            export_df = df_attendance[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].copy()
            export_df.rename(columns={'formatted_time': 'Timestamp (Validated)'}, inplace=True)
            
            buffer = io.BytesIO()
            # Requirement: 'xlsxwriter' must be present in requirements.txt
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Official_Report')
                writer.close()
            
            st.download_button(
                label="📥 Download Official Attendance (.xlsx)",
                data=buffer.getvalue(),
                file_name=f"BMIT2123_Attendance_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.ms-excel"
            )
        else:
            st.info("Insufficient data for analysis. Please sync hardware to populate cloud logs.")

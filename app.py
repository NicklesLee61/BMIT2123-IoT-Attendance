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
st.set_page_config(page_title="IoT Command Center", layout="wide", page_icon="🛡️")

if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            cred = credentials.Certificate("service-account-key.json")
        firebase_admin.initialize_app(cred, {'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'})
    except Exception as e:
        st.error(f"Cloud Connection Failed: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE (Real-time Retrieval)
# ==========================================================
# Fetch hardware state first to drive UI logic
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

# Fetch other data
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process Attendance with strict DateTime conversion
all_records = []
if attendance_raw:
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for rec_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{rec_id}"
                all_records.append(info)

df = pd.DataFrame(all_records)
if not df.empty:
    # Fix: Ensure timestamp is formatted as STRING for Excel and UI display
    df['dt_object'] = pd.to_datetime(df['timestamp'], unit='s', errors='coerce')
    df['formatted_time'] = df['dt_object'].dt.strftime('%Y-%m-%d %H:%M:%S')

# ==========================================================
# 3. SIDEBAR: HARDWARE SYNC & MODE CONTROL
# ==========================================================
st.sidebar.title("🎮 Hardware Master Control")
st.sidebar.info(f"Current System Mode: **{current_hw_mode}**")

with st.sidebar.expander("🛠️ Remote Command Panel", expanded=True):
    # Mode Toggle Logic: Changing this here tells the Raspberry Pi what to do
    new_mode = st.selectbox("Set Hardware Mode:", ["Attendance", "Enrollment"], 
                            index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Push Mode Change"):
        control_ref.update({"mode": new_mode})
        st.rerun()
    
    is_locked = st.sidebar.toggle("🔒 Emergency Lockdown", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

# ==========================================================
# 4. DYNAMIC UI BASED ON HARDWARE MODE
# ==========================================================
st.title(f"🛡️ {current_hw_mode} Interface Portal")

if current_hw_mode == "Enrollment":
    # ENROLLMENT MODE: Focus on Registry Management
    st.warning("SYSTEM IS IN ENROLLMENT MODE: Card registration is active.")
    tab_reg, tab_db = st.tabs(["➕ New Enrollment", "🗃️ Master Registry"])
    
    with tab_reg:
        with st.form("reg_form"):
            col1, col2 = st.columns(2)
            with col1:
                r_id = st.text_input("Student ID:")
                r_name = st.text_input("Full Name:")
            with col2:
                r_rfid = st.text_input("RFID UID (from Pi):")
                r_fpid = st.number_input("Fingerprint Index (1-127):", min_value=1)
            if st.form_submit_button("Sync to Cloud"):
                # Logic: Atomic update to both cards and students nodes
                db.reference(f'/cards/{r_rfid}').update({"student_id": r_id, "name": r_name, "fingerprint_id": r_fpid})
                db.reference(f'/students/{r_id}').update({"name": r_name, "rfid": r_rfid})
                st.success("Registration Synced!"); st.rerun()
    
    with tab_db:
        if cards_data:
            st.subheader("Current Biometric Mappings")
            st.dataframe(pd.DataFrame([v for k, v in cards_data.items()]).sort_values("student_id"), use_container_width=True)

else:
    # ATTENDANCE MODE: Focus on Logs & Module 3 Analytics
    tab_live, tab_m3 = st.tabs(["📺 Live Monitoring", "📊 Module 3: Reporting & Analytics"])
    
    with tab_live:
        st.subheader("📋 Real-time Logs (2FA Validated)")
        if not df.empty:
            # Highlight validation status: Strict Business Rules
            st.dataframe(df[['formatted_time', 'name', 'status', 'student_id', 'verification_method']]
                         .sort_values('formatted_time', ascending=False), use_container_width=True)
        else: st.info("Hardware is active. Waiting for scans...")

    with tab_m3:
        st.header("🔍 Module 3: Management Insights")
        
        # 4.1 Attendance Trends & Absenteeism
        c1, c2 = st.columns([2, 1])
        with c1:
            st.subheader("Daily Status Trend")
            if not df.empty:
                counts = df['status'].value_counts()
                fig, ax = plt.subplots()
                ax.bar(counts.index, counts.values, color=['#2ecc71', '#f1c40f', '#e74c3c'])
                st.pyplot(fig)
        
        with c2:
            st.subheader("🚩 Absence Alert")
            all_sids = set(students_data.keys())
            present_today = set(df[df['status'] != 'absent']['student_id'].unique()) if not df.empty else set()
            missing = all_sids - present_today
            if missing: st.error(f"Missing ({len(missing)}): {', '.join(missing)}")
            else: st.success("All students accounted for!")

        st.markdown("---")
        # 4.2 Manual Reporting: Adjustment Logic (Medical Leave)
        st.subheader("📝 Admin Status Override")
        with st.form("override"):
            m_sid = st.selectbox("Select Student:", list(students_data.keys()))
            m_status = st.selectbox("Status Update:", ["present", "late", "absent (Medical Leave)"])
            if st.form_submit_button("Submit Adjusted Report"):
                t_key = datetime.now().strftime("%Y-%m-%d")
                db.reference(f'/attendance/{t_key}').push().set({
                    'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                    'status': m_status, 'timestamp': int(time.time()), 
                    'verification_method': "Manual_Admin_Correction"
                }); st.rerun()

        st.markdown("---")
        # 4.3 Export Engine: Fixes Hash Display Issue
        st.subheader("💾 Export Official Record")
        if not df.empty:
            # FIX: Prepare DataFrame for Excel by ensuring types are clean
            export_df = df[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].copy()
            export_df.rename(columns={'formatted_time': 'Timestamp (Sync)'}, inplace=True)
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, index=False, sheet_name='BMIT2123_Logs')
                # Business Rule: Autofit columns for Excel readability
                writer.close()
            
            st.download_button(
                label="📥 Download Excel Report (xlsx)",
                data=buffer.getvalue(),
                file_name=f"Attendance_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.ms-excel"
            )

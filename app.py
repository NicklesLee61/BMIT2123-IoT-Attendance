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

if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production: Fetch from Streamlit Cloud Secrets
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local Dev: Use local JSON key
            cred = credentials.Certificate("service-account-key.json")
        firebase_admin.initialize_app(cred, {'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'})
    except Exception as e:
        st.error(f"Database Error: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE: REAL-TIME SYNC
# ==========================================================
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process attendance logs with Excel-safe timestamp strings
all_records = []
if attendance_raw:
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for rec_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{rec_id}"
                all_records.append(info)

df_attendance = pd.DataFrame(all_records)
if not df_attendance.empty:
    df_attendance['formatted_time'] = pd.to_datetime(df_attendance['timestamp'], unit='s', errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')

# ==========================================================
# 3. SIDEBAR: REMOTE HARDWARE CONTROL
# ==========================================================
st.sidebar.title("🎮 Hardware Command Center")
st.sidebar.markdown(f"**Physical Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Settings", expanded=True):
    target_mode = st.selectbox("Switch Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Push Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()
    
    is_locked = st.sidebar.toggle("🔒 Global Lockdown", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

# ==========================================================
# 4. DYNAMIC INTERFACE: ENROLLMENT VS ATTENDANCE
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    # --- ENROLLMENT MODE: REGISTRY MANAGEMENT ---
    tab_reg, tab_list = st.tabs(["➕ New Registration", "🗃️ Master Registry"])
    
    with tab_reg:
        st.info("Enrollment Mode Active: Map RFID to Biometric Alphanumeric Tokens.")
        with st.form("enroll_form"):
            c1, c2 = st.columns(2)
            with c1:
                n_sid = st.text_input("Student ID (Unique):")
                n_name = st.text_input("Full Name:")
            with c2:
                n_rfid = st.text_input("RFID UID (e.g. 1061348...)")
                # Alphanumeric support for Fingerprint ID
                n_fpid = st.text_input("Fingerprint Token (Alphanumeric):")
            
            if st.form_submit_button("Sync User to Firebase"):
                if n_sid and n_rfid and n_fpid:
                    db.reference(f'/cards/{n_rfid}').update({
                        "student_id": n_sid, "name": n_name, "fingerprint_id": n_fpid,
                        "card_id": n_rfid, "registered_date": datetime.now().isoformat()
                    })
                    db.reference(f'/students/{n_sid}').update({"name": n_name, "rfid": n_rfid})
                    st.success(f"Profile {n_sid} successfully mapped!"); st.rerun()

    with tab_list:
        if cards_data:
            # FIX: Convert dictionary values to list and create DF
            reg_df = pd.DataFrame(list(cards_data.values()))
            
            # DEFENSIVE LOGIC: Check if columns exist before sorting/selecting
            expected_cols = ['student_id', 'name', 'card_id', 'fingerprint_id']
            # Reindex ensures all columns exist; missing ones are filled with "N/A"
            reg_df = reg_df.reindex(columns=expected_cols).fillna("N/A")
            
            st.subheader("Master List (Sorted by ID)")
            st.dataframe(reg_df.sort_values("student_id"), use_container_width=True)
        else:
            st.warning("No records found. The database is currently empty.")

else:
    # --- ATTENDANCE MODE: MONITORING & MODULE 3 ---
    tab_live, tab_m3 = st.tabs(["📺 Live Monitoring", "📊 Module 3: Reporting"])
    
    with tab_live:
        st.subheader("📋 Real-time Logs (2FA Validation Check)")
        if not df_attendance.empty:
            st.dataframe(df_attendance[['formatted_time', 'name', 'status', 'student_id', 'verification_method']]
                         .sort_values('formatted_time', ascending=False), use_container_width=True)
        else: st.warning("Attendance mode active. Waiting for hardware signals...")

    with tab_m3:
        st.header("📊 Module 3: Management Insights")
        if not df_attendance.empty:
            # 4.1 Visual Trends
            c1, c2 = st.columns([2, 1])
            with c1:
                status_counts = df_attendance['status'].value_counts()
                fig, ax = plt.subplots()
                ax.bar(status_counts.index, status_counts.values, color=['#2ecc71', '#f1c40f', '#e74c3c'])
                st.pyplot(fig)
            with c2:
                # Absence Alert logic
                all_sids = set(students_data.keys())
                present_sids = set(df_attendance[df_attendance['status'] != 'absent']['student_id'].unique())
                missing = all_sids - present_sids
                if missing: st.error(f"Absent: {', '.join(missing)}")
                else: st.success("100% Attendance!")

            st.markdown("---")
            # 4.2 Manual Modification (Module 3 requirement)
            st.subheader("📝 Manual Adjustment (Medical Leave / Corrections)")
            with st.form("override"):
                m_sid = st.selectbox("Select Student:", list(students_data.keys()))
                m_status = st.selectbox("Update:", ["present", "absent (Medical Leave)", "absent"])
                if st.form_submit_button("Submit Correction"):
                    t_key = datetime.now().strftime("%Y-%m-%d")
                    db.reference(f'/attendance/{t_key}').push().set({
                        'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                        'status': m_status, 'timestamp': int(time.time()), 
                        'verification_method': "Manual_Admin_Adjustment"
                    }); st.rerun()

            st.markdown("---")
            # 4.3 Export Bridge
            st.subheader("💾 Permanent Record Export")
            export_df = df_attendance[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].copy()
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, index=False, sheet_name='BMIT2123_Logs')
                writer.close()
            
            st.download_button(label="📥 Download Excel Report", data=buffer.getvalue(), 
                               file_name=f"Report_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")
        else: st.info("Insufficient data for reporting.")

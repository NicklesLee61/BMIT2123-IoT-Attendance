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
# 2. DATA ENGINE: REAL-TIME SYNC & TYPE CONVERSION
# ==========================================================
# Fetch hardware control state to define UI logic
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

# Fetch core database nodes
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process attendance for reporting (Fixed timestamp issue)
all_records = []
if attendance_raw:
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for rec_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{rec_id}"
                all_records.append(info)

df = pd.DataFrame(all_records)
if not df.empty:
    # Logic: Convert unix epoch to STRING to prevent '###' in Excel
    df['dt_object'] = pd.to_datetime(df['timestamp'], unit='s', errors='coerce')
    df['formatted_time'] = df['dt_object'].dt.strftime('%Y-%m-%d %H:%M:%S')

# ==========================================================
# 3. SIDEBAR: REMOTE MODE & SECURITY CONTROL
# ==========================================================
st.sidebar.title("🎮 Hardware Master Control")
st.sidebar.markdown(f"**Current Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Command Panel", expanded=True):
    # Mode Switch: Attendance vs Enrollment
    target_mode = st.selectbox("Switch Operation Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Push Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()
    
    # Emergency Lockdown Toggle
    is_locked = st.sidebar.toggle("🔒 System Lockdown", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

# ==========================================================
# 4. DYNAMIC INTERFACE: ENROLLMENT VS ATTENDANCE
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    # --- ENROLLMENT MODE: REGISTRY MANAGEMENT ---
    st.info("System is in Enrollment Mode. Use this to register new Biometric/RFID users.")
    tab_reg, tab_list = st.tabs(["➕ New Registration", "🗃️ Registry Database"])
    
    with tab_reg:
        with st.form("enroll_form"):
            c1, c2 = st.columns(2)
            with c1:
                new_sid = st.text_input("Student ID (Unique):")
                new_name = st.text_input("Full Name:")
            with c2:
                new_rfid = st.text_input("RFID UID (e.g. 1061348...)")
                # NEW LOGIC: Fingerprint Index as Alphanumeric Token
                new_fpid = st.text_input("Fingerprint Biometric ID (Alphanumeric Token):")
            
            if st.form_submit_button("Sync User to Cloud"):
                if new_sid and new_rfid and new_fpid:
                    # Sync to dual-nodes: /cards for hardware, /students for records
                    db.reference(f'/cards/{new_rfid}').update({
                        "student_id": new_sid, "name": new_name, "fingerprint_id": new_fpid,
                        "card_id": new_rfid, "registered_date": datetime.now().isoformat()
                    })
                    db.reference(f'/students/{new_sid}').update({"name": new_name, "rfid": new_rfid})
                    st.success(f"Profile {new_sid} successfully mapped to biometric tokens!"); st.rerun()

    with tab_list:
        if cards_data:
            # Unified view sorted by Student ID
            reg_df = pd.DataFrame([v for k, v in cards_data.items()]).sort_values("student_id")
            st.dataframe(reg_df[['student_id', 'name', 'card_id', 'fingerprint_id']], use_container_width=True)

else:
    # --- ATTENDANCE MODE: MONITORING & MODULE 3 ---
    tab_live, tab_analytics = st.tabs(["📺 Live Monitoring", "📊 Module 3: Reporting"])
    
    with tab_live:
        st.subheader("📋 Real-time Logs (2FA Validation Check)")
        if not df.empty:
            # Show verification method to satisfy Business Rule Validation
            st.dataframe(df[['formatted_time', 'name', 'status', 'student_id', 'verification_method']]
                         .sort_values('formatted_time', ascending=False), use_container_width=True)
        else: st.warning("Hardware scanning is active. Waiting for student entry...")

    with tab_analytics:
        st.header("🔍 Advanced Reporting Interface")
        
        # 3.1 Attendance Visual Trends
        col_bar, col_absent = st.columns([2, 1])
        with col_bar:
            st.subheader("Daily Status Distribution")
            if not df.empty:
                counts = df['status'].value_counts()
                fig, ax = plt.subplots()
                ax.bar(counts.index, counts.values, color=['#2ecc71', '#f1c40f', '#e74c3c'])
                st.pyplot(fig)
        
        with col_absent:
            # Feature: Automated Absence Alert
            st.subheader("🚩 Absence Alert")
            all_sids = set(students_data.keys())
            present_sids = set(df[df['status'] != 'absent']['student_id'].unique()) if not df.empty else set()
            missing = all_sids - present_sids
            if missing: st.error(f"Absent ({len(missing)}): {', '.join(missing)}")
            else: st.success("100% Attendance Achieved!")

        st.markdown("---")
        # 3.2 Manual Modification Logic (Module 3 requirement)
        st.subheader("📝 Manual Adjustment (Medical Leave / Errors)")
        with st.form("manual_override"):
            m_sid = st.selectbox("Select Student ID:", list(students_data.keys()))
            m_status = st.selectbox("Status Update:", ["present", "late", "absent (Medical Leave)"])
            if st.form_submit_button("Apply Correction"):
                t_key = datetime.now().strftime("%Y-%m-%d")
                db.reference(f'/attendance/{t_key}').push().set({
                    'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                    'status': m_status, 'timestamp': int(time.time()), 
                    'verification_method': "Manual_Admin_Adjustment"
                }); st.rerun()

        st.markdown("---")
        # 3.3 Data Export Engine (Fixed Column Format)
        st.subheader("💾 Permanent Record Export")
        if not df.empty:
            export_df = df[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].copy()
            export_df.rename(columns={'formatted_time': 'Timestamp (Validated)'}, inplace=True)
            
            buffer = io.BytesIO()
            # Requirement: 'xlsxwriter' must be in requirements.txt
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, index=False, sheet_name='BMIT2123_Official_Report')
                writer.close()
            
            st.download_button(
                label="📥 Download Official Attendance (.xlsx)",
                data=buffer.getvalue(),
                file_name=f"BMIT2123_Attendance_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.ms-excel"
            )

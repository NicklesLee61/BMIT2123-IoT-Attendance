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

# Initialize Firebase with Streamlit Secrets for cloud deployment
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
        st.error(f"Database Initialization Failed: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE: REAL-TIME SYNC & PROCESSING
# ==========================================================
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

# Fetch core database nodes
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process raw attendance logs
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
    # Ensure time is converted to string for Excel and clear UI display
    df_attendance['formatted_time'] = pd.to_datetime(df_attendance['timestamp'], unit='s', errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')

# ==========================================================
# 3. SIDEBAR: MASTER CONTROL & MODE SWITCHING
# ==========================================================
st.sidebar.title("🎮 Master Control Center")
st.sidebar.markdown(f"**Current System Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Operations", expanded=True):
    # Mode Toggle Logic: Distinctly separates Enrollment from Attendance
    target_mode = st.selectbox("Switch Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Apply Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()
    
    # Emergency Lockdown Toggle
    is_locked = st.sidebar.toggle("🔒 Sensor Lockdown", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

# ==========================================================
# 4. DYNAMIC INTERFACE: MODE-AWARE UI
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    # --- ENROLLMENT MODE: REGISTRY & BULK OPERATIONS ---
    st.info("System is in Enrollment Mode. Link RFID to Alphanumeric Biometric Tokens.")
    tab_bulk, tab_single, tab_mgmt = st.tabs(["📂 Bulk Import", "👤 Single Enrollment", "🗃️ Registry Management"])
    
    with tab_bulk:
        # FEATURE: Bulk Student Import via Excel (Logic 2)
        st.subheader("Excel Student List Import")
        uploaded_file = st.file_uploader("Upload Master Student List (.xlsx)", type=["xlsx"])
        if uploaded_file:
            bulk_df = pd.read_excel(uploaded_file)
            st.write("Preview:")
            st.dataframe(bulk_df.head())
            if st.button("Bulk Populate Student Profiles"):
                for _, row in bulk_df.iterrows():
                    sid = str(row['student_id'])
                    db.reference(f'/students/{sid}').update({"name": row['name'], "course": row.get('course', 'N/A')})
                st.success("Bulk import complete!"); st.rerun()

    with tab_single:
        # FEATURE: Single Registration with Slot Conflict Check (Logic 6)
        with st.form("single_enroll"):
            col1, col2 = st.columns(2)
            with col1:
                n_id = st.text_input("Student ID:")
                n_name = st.text_input("Full Name:")
            with col2:
                n_rfid = st.text_input("RFID UID (12-digit):")
                n_fpid = st.text_input("Biometric Token (Alphanumeric):")
            
            # Conflict Check Logic
            existing_fpids = [v.get('fingerprint_id') for v in cards_data.values()]
            if n_fpid in existing_fpids:
                st.error(f"⚠️ Slot Conflict: Token '{n_fpid}' is already assigned to another student!")
            
            if st.form_submit_button("Sync Profile"):
                if n_id and n_rfid and n_fpid not in existing_fpids:
                    db.reference(f'/cards/{n_rfid}').update({
                        "student_id": n_id, "name": n_name, "fingerprint_id": n_fpid,
                        "card_id": n_rfid, "is_active": True, "registered_date": datetime.now().isoformat()
                    })
                    db.reference(f'/students/{n_id}').update({"name": n_name, "rfid": n_rfid})
                    st.success("Mapping established!"); st.rerun()

    with tab_mgmt:
        # FEATURE: Card Suspension & Sorted Registry (Logic 3)
        if cards_data:
            reg_df = pd.DataFrame(list(cards_data.values()))
            # Ensure columns exist
            reg_df = reg_df.reindex(columns=['student_id', 'name', 'card_id', 'fingerprint_id', 'is_active']).fillna("N/A")
            st.subheader("Master Registry (Sorted by ID)")
            st.dataframe(reg_df.sort_values("student_id"), use_container_width=True)

            st.markdown("---")
            # FEATURE: Card Status Toggle & Delete
            sel_sid = st.selectbox("Select Student to Modify:", reg_df['student_id'].tolist())
            c1, c2 = st.columns(2)
            with c1:
                current_status = next(v.get('is_active', True) for v in cards_data.values() if v.get('student_id') == sel_sid)
                if st.button(f"{'Disable' if current_status else 'Enable'} Access for {sel_sid}"):
                    card_key = next(k for k, v in cards_data.items() if v.get('student_id') == sel_sid)
                    db.reference(f'/cards/{card_key}').update({"is_active": not current_status})
                    st.rerun()
            with c2:
                if st.button("🗑️ Permanently Delete Record"):
                    card_key = next((k for k, v in cards_data.items() if v.get('student_id') == sel_sid), None)
                    if card_key: db.reference(f'/cards/{card_key}').delete()
                    db.reference(f'/students/{sel_sid}').delete()
                    st.warning("Record cleared."); st.rerun()

else:
    # --- ATTENDANCE MODE: MONITORING & MODULE 3 ANALYTICS ---
    tab_live, tab_report = st.tabs(["📺 Live Monitoring", "📊 Module 3: Reporting"])
    
    with tab_live:
        st.subheader("📋 Real-time Logs (Business Rule Validation)")
        if not df_attendance.empty:
            # Displays verification_method to satisfy Validation audit requirements
            st.dataframe(df_attendance[['formatted_time', 'name', 'status', 'student_id', 'verification_method']]
                         .sort_values('formatted_time', ascending=False), use_container_width=True)
        else: st.warning("Attendance scanning is active. Waiting for entries...")

    with tab_report:
        st.header("🔍 Advanced Reporting Interface")
        
        # FEATURE: Visual Trends & Auto-Absence (Logic 5)
        col_viz, col_alert = st.columns([2, 1])
        with col_viz:
            st.subheader("Attendance Distribution")
            if not df_attendance.empty:
                counts = df_attendance['status'].value_counts()
                fig, ax = plt.subplots()
                ax.bar(counts.index, counts.values, color=['#2ecc71', '#f1c40f', '#e74c3c'])
                st.pyplot(fig)
        
        with col_alert:
            # FEATURE: Real-time Absence Alert via Set Difference logic
            st.subheader("🚩 Absence Alert")
            all_sids = set(students_data.keys())
            present_sids = set(df_attendance[df_attendance['status'] != 'absent']['student_id'].unique()) if not df_attendance.empty else set()
            missing = all_sids - present_sids
            if missing:
                st.error(f"Missing ({len(missing)}): {', '.join(missing)}")
                if st.button("🏁 Close Session & Mark Absent"):
                    # Logic 5: Automatically write absence status to Firebase for trends
                    today_key = datetime.now().strftime("%Y-%m-%d")
                    for m_id in missing:
                        db.reference(f'/attendance/{today_key}').push().set({
                            'student_id': m_id, 'name': students_data[m_id].get('name', 'N/A'),
                            'status': "absent", 'timestamp': int(time.time()), 
                            'verification_method': "Auto_System_Closing"
                        })
                    st.success("Session closed. Missing students recorded."); st.rerun()
            else: st.success("All students accounted for!")

        st.markdown("---")
        # 4.2 Manual Reporting: Admin Overrides (Module 3)
        st.subheader("📝 Manual Report Adjustment (Medical Leave)")
        with st.form("manual_override"):
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
        # 4.3 Firebase to Excel Sync Bridge
        st.subheader("💾 Permanent Record Export")
        if not df_attendance.empty:
            export_df = df_attendance[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].copy()
            buffer = io.BytesIO()
            # Requirement: 'xlsxwriter' must be in requirements.txt
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Official_Logs')
                writer.close()
            st.download_button(label="📥 Download Official Report (.xlsx)", data=buffer.getvalue(), 
                               file_name=f"BMIT2123_Report_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")

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
st.set_page_config(page_title="IoT Command Center", layout="wide", page_icon="🛡️")

# Initialize Firebase with Streamlit Secrets for cloud deployment
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production environment: Fetch from Streamlit Cloud Secrets
            cred_dict = dict(st.secrets["firebase"])
            # Handle newline character in the private key string
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local development environment
            cred = credentials.Certificate("service-account-key.json")
        firebase_admin.initialize_app(cred, {'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'})
    except Exception as e:
        st.error(f"Database Error: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE: REAL-TIME SYNC & LOGIC PROCESSING
# ==========================================================
# Fetch current hardware state and database nodes
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process logs for display and duration calculation
all_records = []
if attendance_raw:
    for date_key, daily_data in attendance_raw.items():
        if isinstance(daily_data, dict):
            for rec_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{rec_id}"
                info['record_date'] = date_key
                all_records.append(info)

df_all = pd.DataFrame(all_records)
if not df_all.empty:
    # Convert timestamps into datetime objects for logical calculations
    df_all['dt_obj'] = pd.to_datetime(df_all['timestamp'], unit='s', errors='coerce')
    df_all['formatted_time'] = df_all['dt_obj'].dt.strftime('%Y-%m-%d %H:%M:%S')

# ==========================================================
# 3. SIDEBAR: REMOTE MASTER CONTROL
# ==========================================================
st.sidebar.title("🎮 Master Control Center")
st.sidebar.markdown(f"**Current Hardware Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Operations", expanded=True):
    # Mode switching logic: Enrollment vs Attendance
    target_mode = st.selectbox("Switch Operation Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Apply Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()
    
    # Emergency global sensor lock
    is_locked = st.sidebar.toggle("🔒 Sensor Lockdown", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

# ==========================================================
# 4. MAIN INTERFACE: MODE-AWARE DYNAMIC UI
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    # --- ENROLLMENT MODE: REGISTRY & SECURITY MAPPING ---
    tab_reg, tab_mgmt = st.tabs(["➕ Single Enrollment", "🗃️ Registry Management"])
    
    with tab_reg:
        st.info("System is in Enrollment Mode. Use this to link RFID cards to Biometric Tokens.")
        with st.form("enroll_form"):
            c1, c2 = st.columns(2)
            with c1:
                n_id = st.text_input("Student ID (Unique):")
                n_name = st.text_input("Full Name:")
            with c2:
                n_rfid = st.text_input("RFID UID (Scan on Pi first):")
                # Alphanumeric support to avoid 'garbled' simple number IDs
                n_fpid = st.text_input("Fingerprint Token (Alphanumeric):")
            
            # --- Logic: Slot Conflict Check ---
            existing_fpids = [v.get('fingerprint_id') for v in cards_data.values()]
            if n_fpid in existing_fpids:
                st.error(f"⚠️ Conflict: Biometric Token '{n_fpid}' is already assigned!")
            
            if st.form_submit_button("Sync Mapping to Cloud"):
                if n_id and n_rfid and n_fpid not in existing_fpids:
                    # Sync to dual nodes: /cards for hardware and /students for records
                    db.reference(f'/cards/{n_rfid}').update({"student_id": n_id, "name": n_name, "fingerprint_id": n_fpid, "is_active": True})
                    db.reference(f'/students/{n_id}').update({"name": n_name, "rfid": n_rfid})
                    st.success("Mapping established!"); st.rerun()

    with tab_mgmt:
        # --- Logic: Card Suspension & Sorted Display ---
        if cards_data:
            reg_df = pd.DataFrame(list(cards_data.values()))
            # Defensive reindexing to handle missing columns
            reg_df = reg_df.reindex(columns=['student_id', 'name', 'card_id', 'fingerprint_id', 'is_active']).fillna("N/A")
            st.subheader("Master Registry (Sorted by Student ID)")
            st.dataframe(reg_df.sort_values("student_id"), use_container_width=True)

            st.markdown("---")
            # --- Feature: Suspend card access or delete record ---
            sel_sid = st.selectbox("Select Student for Modification:", reg_df['student_id'].tolist())
            col_a, col_b = st.columns(2)
            with col_a:
                current_active = next(v.get('is_active', True) for v in cards_data.values() if v.get('student_id') == sel_sid)
                if st.button(f"{'Disable' if current_active else 'Enable'} Card for {sel_sid}"):
                    card_key = next(k for k, v in cards_data.items() if v.get('student_id') == sel_sid)
                    db.reference(f'/cards/{card_key}').update({"is_active": not current_active})
                    st.rerun()
            with col_b:
                if st.button("🗑️ Permanently Remove Student"):
                    # Logic: Find linked card to clean both Firebase nodes
                    card_key = next((k for k, v in cards_data.items() if v.get('student_id') == sel_sid), None)
                    if card_key: db.reference(f'/cards/{card_key}').delete()
                    db.reference(f'/students/{sel_sid}').delete(); st.rerun()

else:
    # --- ATTENDANCE MODE: MONITORING & SMART DURATION ---
    tab_live, tab_m3 = st.tabs(["📺 Live Monitoring", "📊 Module 3: Reporting & Duration"])
    
    with tab_live:
        st.subheader("📋 Real-time Smart Logs (2FA Validated)")
        if not df_all.empty:
            # Displays verification method to satisfy audit validation requirements
            st.dataframe(df_all[['formatted_time', 'name', 'status', 'student_id', 'verification_method']]
                         .sort_values('formatted_time', ascending=False), use_container_width=True)
        else: st.warning("Attendance scanning is active. Waiting for student signals...")

    with tab_m3:
        st.header("🔍 Module 3: Advanced Duration Analytics")
        if not df_all.empty:
            # --- Logic: Second Scan identification & Duration Calculation ---
            st.subheader("⏱️ Daily Stay Duration Analysis")
            duration_data = []
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            for sid in students_data.keys():
                # Filter records for the specific student today
                personal_today = df_all[(df_all['student_id'] == sid) & (df_all['record_date'] == today_str)].sort_values('dt_obj')
                
                if len(personal_today) >= 1:
                    check_in = personal_today.iloc[0]
                    # Logic: Second or subsequent tik is identified as 'Leave'
                    leave_time = personal_today.iloc[-1]['formatted_time'] if len(personal_today) >= 2 else "No Leave Recorded"
                    
                    # Calculate hours if both scans exist
                    total_hrs = 0
                    if len(personal_today) >= 2:
                        duration = personal_today.iloc[-1]['dt_obj'] - personal_today.iloc[0]['dt_obj']
                        total_hrs = round(duration.total_seconds() / 3600, 2)

                    duration_data.append({
                        "Student ID": sid, "Name": students_data[sid].get('name'),
                        "Check-in": check_in['formatted_time'].split()[-1],
                        "Latest Tik (Leave)": leave_time.split()[-1] if len(personal_today) >= 2 else "N/A",
                        "Total Hours": total_hrs
                    })
            
            st.table(pd.DataFrame(duration_data))

            st.markdown("---")
            # --- Logic: Manual Status Modification (Medical Leave / Adjustment) ---
            c_viz, c_edit = st.columns(2)
            with c_viz:
                st.subheader("Attendance Distribution")
                counts = df_all['status'].value_counts()
                fig, ax = plt.subplots()
                ax.bar(counts.index, counts.values, color=['#2ecc71', '#f1c40f', '#e74c3c'])
                st.pyplot(fig)
            with c_edit:
                st.subheader("📝 Manual Status Correction")
                with st.form("manual_correction"):
                    m_sid = st.selectbox("Select Student:", list(students_data.keys()))
                    m_status = st.selectbox("Set Status:", ["present", "absent (Medical Leave)", "absent", "leave"])
                    if st.form_submit_button("Submit Adjusted Report"):
                        t_key = datetime.now().strftime("%Y-%m-%d")
                        db.reference(f'/attendance/{t_key}').push().set({
                            'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                            'status': m_status, 'timestamp': int(time.time()), 
                            'verification_method': "Manual_Admin_Adjustment"
                        }); st.rerun()

            st.markdown("---")
            # --- Logic: Firebase to Excel Bridge (Permanent Archival) ---
            st.subheader("💾 Export Official Report")
            export_df = df_all[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].copy()
            buffer = io.BytesIO()
            # Requirement: 'xlsxwriter' must be in requirements.txt
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Official_Attendance')
                writer.close()
            st.download_button(label="📥 Download Excel Sync (.xlsx)", data=buffer.getvalue(), 
                               file_name=f"BMIT2123_Sync_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")
        else: st.info("Insufficient data for reporting.")

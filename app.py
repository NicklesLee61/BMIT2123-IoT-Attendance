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
# 2. DATA ENGINE: SMART PROCESSING & DURATION LOGIC
# ==========================================================
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

students_data = db.reference('/students').get() or {} 
cards_raw = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process raw logs for calculation and display
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
    df_all['dt_obj'] = pd.to_datetime(df_all['timestamp'], unit='s', errors='coerce')
    df_all['formatted_time'] = df_all['dt_obj'].dt.strftime('%Y-%m-%d %H:%M:%S')
    # Rank taps to identify Check-in vs Leave
    df_all = df_all.sort_values('dt_obj')
    df_all['tap_rank'] = df_all.groupby(['student_id', 'record_date']).cumcount() + 1
    df_all['flow_type'] = df_all['tap_rank'].apply(lambda x: "Check-in" if x == 1 else "Leave")

# ==========================================================
# 3. SIDEBAR: REMOTE MASTER CONTROL
# ==========================================================
st.sidebar.title("🎮 Master Control Center")
st.sidebar.markdown(f"**Current Hardware Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Operations", expanded=True):
    target_mode = st.selectbox("Switch Operation Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Apply Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()
    
    is_locked = st.sidebar.toggle("🔒 Sensor Lockdown", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

# ==========================================================
# 4. MAIN INTERFACE: DYNAMIC UI BASED ON MODE
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    # --- ENROLLMENT MODE: REGISTRY & STUDENT INFORMATION ---
    tab_reg, tab_mgmt = st.tabs(["➕ Student Registration", "🗃️ Registry Management"])
    
    with tab_reg:
        st.info("Enrollment Mode: 请填写完整的学生信息以完成硬件关联。")
        with st.form("student_registration"):
            c1, c2 = st.columns(2)
            with c1:
                n_id = st.text_input("Student ID (e.g., 24WMR15298):")
                n_name = st.text_input("Full Name:")
                n_course = st.selectbox("Course:", ["Bachelor in Data Science", "IoT Engineering", "Computer Science"])
            with c2:
                n_rfid = st.text_input("RFID UID (Scan on Pi first):")
                n_fpid = st.text_input("Fingerprint Token (Alphanumeric):")
                n_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            
            # Logic: Conflict Check
            existing_fpids = [v.get('fingerprint_id') for v in cards_raw.values()] if isinstance(cards_raw, dict) else []
            if n_fpid in existing_fpids:
                st.error(f"⚠️ Conflict: Biometric Token '{n_fpid}' is already assigned!")

            if st.form_submit_button("Sync Profile to Cloud"):
                if n_id and n_rfid and n_fpid not in existing_fpids:
                    # Sync to /cards (for Hardware Auth)
                    db.reference('/cards').push().set({
                        "student_id": n_id, "name": n_name, "card_id": n_rfid, 
                        "course": n_course, "fingerprint_id": n_fpid, "registered_date": n_date
                    })
                    # Sync to /students (for Administrative Records)
                    db.reference(f'/students/{n_id}').update({
                        "student_id": n_id, "name": n_name, "rfid": n_rfid, 
                        "course": n_course, "attendance_count": 0, "registered_date": n_date
                    })
                    st.success(f"Profile {n_id} fully synchronized!"); st.rerun()

    with tab_mgmt:
        # FEATURE: Sorted registry with suspension and deletion logic
        if cards_raw:
            reg_df = pd.DataFrame(list(cards_raw.values()))
            reg_df = reg_df.reindex(columns=['student_id', 'name', 'card_id', 'fingerprint_id', 'course']).fillna("N/A")
            st.subheader("Master Student Registry (Sorted by ID)")
            st.dataframe(reg_df.sort_values("student_id"), use_container_width=True)

            st.markdown("---")
            sel_sid = st.selectbox("Select Student for Removal:", sorted(students_data.keys()))
            if st.button("🗑️ Permanently Delete Student"):
                db.reference(f'/students/{sel_sid}').delete()
                # Manual cleanup recommendation for cards push IDs
                st.warning(f"Student {sel_sid} removed from database."); st.rerun()

else:
    # --- ATTENDANCE MODE: MONITORING & SMART DURATION ---
    tab_live, tab_m3 = st.tabs(["📺 Live Monitoring", "📊 Module 3: Reporting & Duration"])
    
    with tab_live:
        st.subheader("📋 Real-time Logs (Business Rule Validation)")
        if not df_all.empty:
            st.dataframe(df_all[['formatted_time', 'name', 'flow_type', 'status', 'student_id', 'verification_method']]
                         .sort_values('formatted_time', ascending=False), use_container_width=True)
        else: st.info("Waiting for hardware signals...")

    with tab_m3:
        st.header("🔍 Module 3: Advanced Reporting & Analytics")
        if not df_all.empty:
            # FEATURE: Duration calculation directly in Web App
            st.subheader("⏱️ Total Stay Duration (Check-in vs Leave)")
            duration_data = []
            today_str = datetime.now().strftime("%Y-%m-%d")
            for sid in students_data.keys():
                personal_today = df_all[(df_all['student_id'] == sid) & (df_all['record_date'] == today_str)].sort_values('dt_obj')
                if len(personal_today) >= 2:
                    start, end = personal_today.iloc[0]['dt_obj'], personal_today.iloc[-1]['dt_obj']
                    diff = end - start
                    hrs = round(diff.total_seconds() / 3600, 2)
                    duration_data.append({"ID": sid, "Name": students_data[sid].get('name'), "In": start.strftime('%H:%M'), "Out": end.strftime('%H:%M'), "Duration (Hrs)": hrs})
            
            if duration_data: st.table(pd.DataFrame(duration_data))
            else: st.info("需至少两次打卡（进与出）以计算出席时长。")

            st.markdown("---")
            # FEATURE: Manual Status Override & Log Deletion
            c_del, c_edit = st.columns(2)
            with c_del:
                st.subheader("🗑️ Delete Attendance Log")
                log_labels = df_all['formatted_time'] + " | " + df_all['name']
                to_del = st.selectbox("Select record to erase:", log_labels.tolist())
                if st.button("Confirm Delete Log"):
                    path = df_all[log_labels == to_del]['firebase_path'].values[0]
                    db.reference(f'/attendance/{path}').delete(); st.rerun()
            with c_edit:
                st.subheader("📝 Manual Status Modification")
                with st.form("manual_correction"):
                    m_sid = st.selectbox("Select Student:", list(students_data.keys()))
                    m_status = st.selectbox("Set Status:", ["present", "absent (Medical Leave)", "absent"])
                    if st.form_submit_button("Submit Adjusted Report"):
                        t_key = datetime.now().strftime("%Y-%m-%d")
                        db.reference(f'/attendance/{t_key}').push().set({
                            'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                            'status': m_status, 'timestamp': int(time.time()), 
                            'verification_method': "Manual_Admin_Adjustment"
                        }); st.rerun()

            st.markdown("---")
            # FEATURE: Data Export bridge (Excel formatting fixed)
            st.subheader("💾 Export Official Report")
            export_df = df_all[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].copy()
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Logs')
                writer.close()
            st.download_button(label="📥 Download Excel Sync (.xlsx)", data=buffer.getvalue(), 
                               file_name=f"Report_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")

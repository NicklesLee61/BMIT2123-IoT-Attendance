import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, time as dt_time
import time
import io

# ==========================================================
# 1. SYSTEM INITIALIZATION & SECURE CLOUD AUTHENTICATION
# ==========================================================
st.set_page_config(page_title="IoT Master Command", layout="wide", page_icon="🛡️")

# Initialize Firebase with Streamlit Secrets for cloud deployment
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production environment: Fetch credentials from Streamlit Cloud
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local development fallback
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Database Initialization Failed: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE: SMART PROCESSING & DURATION LOGIC
# ==========================================================
# Fetch current hardware state and primary database nodes
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

students_data = db.reference('/students').get() or {} 
cards_raw = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process raw logs for identification and duration calculation
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
    # Logic: Convert unix timestamps for calculations
    df_all['dt_obj'] = pd.to_datetime(df_all['timestamp'], unit='s', errors='coerce')
    df_all['formatted_time'] = df_all['dt_obj'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Logic: Identify tap sequence (1st = Check-in, >=2nd = Leave)
    df_all = df_all.sort_values('dt_obj')
    df_all['tap_rank'] = df_all.groupby(['student_id', 'record_date']).cumcount() + 1
    df_all['flow_type'] = df_all['tap_rank'].apply(lambda x: "Check-in" if x == 1 else "Leave")

# ==========================================================
# 3. SIDEBAR: REMOTE HARDWARE COMMAND CENTER
# ==========================================================
st.sidebar.title("🎮 Master Control Center")
st.sidebar.markdown(f"**Physical System Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Operations", expanded=True):
    # Mode selection: Enrollment vs Attendance
    target_mode = st.selectbox("Switch Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Apply Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()

    st.markdown("---")
    if st.sidebar.button("🔔 Trigger Remote Buzzer"):
        # Set to True to alert the hardware
        control_ref.update({"trigger_buzzer": True})
        # Wait for 1 second so the Pi has time to catch the signal
        time.sleep(1) 
        # Set back to False to stop the buzzer
        control_ref.update({"trigger_buzzer": False})
        st.sidebar.success("Buzzer signal sent!")
        
    # Global lockdown toggle
    is_locked = st.sidebar.toggle("🔒 Sensor Lockdown", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

# ==========================================================
# 4. DYNAMIC INTERFACE: MODE-AWARE DASHBOARD
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    # --- ENROLLMENT MODE: REGISTRY & PROFILE MGMT ---
    tab_reg, tab_list = st.tabs(["➕ Student Registration", "🗃️ Master Registry"])
    
    with tab_reg:
        st.subheader("Student Personal Information Registry")
        with st.form("enroll_form"):
            c1, c2 = st.columns(2)
            with c1:
                n_id = st.text_input("Student ID (Unique):")
                n_name = st.text_input("Full Name:")
                n_course = st.text_input("Academic Program (Manual Input):") 
            with c2:
                n_rfid = st.text_input("RFID UID (Optional):")
                n_fpid = st.text_input("Biometric Token (Alphanumeric):")
                n_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            # Conflict check for fingerprint slot
            existing_fpids = [v.get('fingerprint_id') for v in cards_raw.values()] if isinstance(cards_raw, dict) else []
            if n_fpid and n_fpid in existing_fpids:
                st.error(f"⚠️ Biometric ID '{n_fpid}' is already occupied!")

            if st.form_submit_button("Finalize Cloud Registration"):
                if n_id and n_name:
                    # Sync to /students as primary record
                    db.reference(f'/students/{n_id}').update({
                        "student_id": n_id, "name": n_name, "rfid": n_rfid if n_rfid else "Unlinked", 
                        "course": n_course, "attendance_count": 0, "registered_date": n_date
                    })
                    # Sync to /cards only if hardware data is provided
                    if n_rfid and n_fpid and n_fpid not in existing_fpids:
                        db.reference('/cards').push().set({
                            "student_id": n_id, "name": n_name, "card_id": n_rfid, 
                            "course": n_course, "fingerprint_id": n_fpid, "registered_date": n_date
                        })
                    st.success(f"Profile {n_id} established!"); st.rerun()

    with tab_list:
        # LOGICAL FIX: Pull from /students to show ALL users immediately
        if students_data:
            master_registry = []
            for sid, info in students_data.items():
                card_info = next((v for v in cards_raw.values() if v.get('student_id') == sid), {}) if isinstance(cards_raw, dict) else {}
                master_registry.append({
                    "student_id": sid, "name": info.get('name', 'N/A'), "course": info.get('course', 'N/A'),
                    "card_id": info.get('rfid', 'Unlinked'), "fingerprint_id": card_info.get('fingerprint_id', 'N/A')
                })
            reg_df = pd.DataFrame(master_registry)
            st.subheader("Master Student Registry (Sorted by ID)")
            st.dataframe(reg_df.sort_values("student_id"), use_container_width=True)
            
            st.markdown("---")
            del_id = st.selectbox("Select Student Profile to remove:", sorted(students_data.keys()))
            if st.button("🗑️ Permanently Delete Student Profile"):
                db.reference(f'/students/{del_id}').delete()
                st.warning(f"Profile {del_id} erased from cloud database."); st.rerun()

else:
    # --- ATTENDANCE MODE: MONITORING, MANAGEMENT & ANALYTICS ---
    tab_live, tab_console, tab_m3 = st.tabs(["📺 Live Monitoring", "🛠️ Manual Record Console", "📊 Module 3: Reporting"])
    
    with tab_live:
        st.subheader("📋 Real-time Smart Attendance Feed")
        if not df_all.empty:
            # Displays smart flow_type to satisfy Check-in/Leave logic
            st.dataframe(df_all[['formatted_time', 'name', 'flow_type', 'status', 'student_id', 'verification_method']]
                         .sort_values('formatted_time', ascending=False), use_container_width=True)
        else: st.info("Waiting for hardware synchronization...")

    with tab_console:
        # FEATURE: MANUALLY ADD/EDIT/DELETE LOGS REGARDLESS OF SCAN
        st.header("🛠️ Attendance Management Console")
        c_add, c_mod = st.columns(2)
        
        with c_add:
            st.subheader("➕ Create Manual Record")
            with st.form("force_add_form"):
                m_sid = st.selectbox("Target Profile:", sorted(students_data.keys()))
                m_date = st.date_input("Date:", datetime.now())
                m_time = st.time_input("Time:", dt_time(9, 0))
                m_status = st.selectbox("Status:", ["present", "absent", "late", "absent (Medical Leave)"])
                if st.form_submit_button("Force Sync Record"):
                    dt_combined = datetime.combine(m_date, m_time)
                    unix_ts = int(dt_combined.timestamp())
                    date_key = m_date.strftime("%Y-%m-%d")
                    db.reference(f'/attendance/{date_key}').push().set({
                        'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                        'status': m_status, 'timestamp': unix_ts, 'verification_method': "Manual_Admin_Creation"
                    })
                    st.success("Record created!"); st.rerun()

        with c_mod:
            st.subheader("📝 Modify or Delete Entries")
            if not df_all.empty:
                log_labels = df_all['formatted_time'] + " | " + df_all['name'] + " (" + df_all['status'] + ")"
                to_manage = st.selectbox("Select Entry:", log_labels.tolist())
                row = df_all[log_labels == to_manage].iloc[0]
                
                with st.expander("Update Status"):
                    new_stat = st.selectbox("Change to:", ["present", "absent", "late", "absent (Medical Leave)"])
                    if st.button("Update This Specific Entry"):
                        db.reference(f'/attendance/{row["firebase_path"]}').update({'status': new_stat, 'verification_method': "Admin_Manual_Update"})
                        st.success("Record updated!"); st.rerun()
                
                if st.button("🗑️ Permanently Delete This Entry", key="del_entry"):
                    db.reference(f'/attendance/{row["firebase_path"]}').delete()
                    st.warning("Entry removed."); st.rerun()

    with tab_m3:
        # MODULE 3 ANALYTICS: Visualizations as per assignment rules
        st.header("📊 Module 3: Advanced Analytics Interface")
        if not df_all.empty:
            # 4.1 STAY DURATION BAR CHART
            st.subheader("⏱️ Daily Attendance Duration Analysis")
            duration_data = []
            today_str = datetime.now().strftime("%Y-%m-%d")
            for sid in students_data.keys():
                p_today = df_all[(df_all['student_id'] == sid) & (df_all['record_date'] == today_str)].sort_values('dt_obj')
                if len(p_today) >= 2:
                    # Duration Logic: Last tap - First tap of the day
                    hrs = round((p_today.iloc[-1]['dt_obj'] - p_today.iloc[0]['dt_obj']).total_seconds() / 3600, 2)
                    duration_data.append({"ID": sid, "Name": students_data[sid].get('name'), "Duration_Hrs": hrs})
            
            if duration_data:
                viz_df = pd.DataFrame(duration_data)
                fig_dur, ax_dur = plt.subplots(figsize=(10, 4))
                sns.barplot(x="ID", y="Duration_Hrs", data=viz_df, palette="viridis", ax=ax_dur)
                st.pyplot(fig_dur)
            else: st.info("Requires both Check-in & Leave scans for duration plotting.")

            # 4.2 STATUS DISTRIBUTION PIE CHART
            st.subheader("Lecture Status Distribution")
            status_counts = df_all['status'].value_counts()
            fig_pie, ax_pie = plt.subplots()
            ax_pie.pie(status_counts, labels=status_counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#f1c40f', '#e74c3c'])
            st.pyplot(fig_pie)

            st.markdown("---")
            # 4.3 PERMANENT RECORD BRIDGE (Excel archival)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df_all[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].to_excel(writer, index=False)
                writer.close()
            st.download_button("📥 Download Official Report (.xlsx)", data=buffer.getvalue(), file_name="Report.xlsx", mime="application/vnd.ms-excel")

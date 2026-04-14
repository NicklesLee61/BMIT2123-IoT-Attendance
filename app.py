import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import time
import io

# ==========================================================
# 1. SYSTEM INITIALIZATION & SECURE CLOUD AUTHENTICATION
# ==========================================================
st.set_page_config(page_title="IoT Master Command", layout="wide", page_icon="🛡️")

# Initialize Firebase using Streamlit Secrets for production-grade security
if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            # Production environment: Secrets from Streamlit Cloud TOML
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            # Local development environment fallback
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
    except Exception as e:
        st.error(f"Database Initialization Failed: {e}"); st.stop()

# ==========================================================
# 2. DATA ENGINE: REAL-TIME SYNC & LOGIC PROCESSING
# ==========================================================
# Fetch hardware state to drive dynamic mode-aware UI
control_ref = db.reference('/control')
hw_state = control_ref.get() or {"mode": "Attendance", "is_locked": False}
current_hw_mode = hw_state.get('mode', 'Attendance')

# Fetch core database nodes
students_data = db.reference('/students').get() or {} 
cards_data = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Process logs for display and stay duration analysis
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
    # Logic: Convert unix timestamps for precise duration calculations
    df_all['dt_obj'] = pd.to_datetime(df_all['timestamp'], unit='s', errors='coerce')
    df_all['formatted_time'] = df_all['dt_obj'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Logic: Tap Rank identification (1st = In/Check-in, 2nd+ = Out/Leave)
    df_all = df_all.sort_values('dt_obj')
    df_all['tap_rank'] = df_all.groupby(['student_id', 'record_date']).cumcount() + 1
    df_all['flow_type'] = df_all['tap_rank'].apply(lambda x: "Check-in" if x == 1 else "Leave")

# ==========================================================
# 3. SIDEBAR: REMOTE HARDWARE COMMAND CENTER
# ==========================================================
st.sidebar.title("🎮 Master Control Center")
st.sidebar.markdown(f"**Current Hardware State:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Operations", expanded=True):
    # Mode selection logic to distinguish Enrollment and Attendance interfaces
    target_mode = st.selectbox("Set System Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Push Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()
    
    # Emergency Global Sensor Lockdown
    is_locked = st.sidebar.toggle("🔒 Sensor Lockdown", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

# ==========================================================
# 4. MAIN INTERFACE: DYNAMIC MODE-AWARE DASHBOARD
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    # --- ENROLLMENT MODE: REGISTRY & PROFILE MANAGEMENT ---
    tab_reg, tab_list = st.tabs(["➕ Student Registration", "🗃️ Master Registry"])
    
    with tab_reg:
        st.subheader("Comprehensive Student Information Form")
        st.info("Enrollment Mode: Link physical RFID and Biometric tokens to student profiles.")
        with st.form("enroll_form"):
            col1, col2 = st.columns(2)
            with col1:
                n_sid = st.text_input("Student ID (Unique):")
                n_name = st.text_input("Full Name:")
                n_course = st.selectbox("Academic Program:", 
                                         ["Bachelor in Data Science", "IoT Engineering", "Computer Science"])
            with col2:
                n_rfid = st.text_input("RFID UID (from Pi):")
                # Alphanumeric biometric token to fix 'garbled' requirement
                n_fpid = st.text_input("Biometric Token (Alphanumeric):")
                n_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            # Logic: Conflict check before establishing mappings
            existing_fpids = [v.get('fingerprint_id') for v in cards_data.values()] if isinstance(cards_data, dict) else []
            if n_fpid in existing_fpids:
                st.error(f"⚠️ Biometric Token '{n_fpid}' is already assigned to a student!")

            if st.form_submit_button("Finalize Cloud Registration"):
                if n_sid and n_rfid and n_fpid not in existing_fpids:
                    # Sync to /students (Administrative) and /cards (Hardware Auth) nodes
                    db.reference(f'/students/{n_id}').update({
                        "student_id": n_sid, "name": n_name, "rfid": n_rfid, 
                        "course": n_course, "attendance_count": 0, "registered_date": n_date
                    })
                    db.reference('/cards').push().set({
                        "student_id": n_sid, "name": n_name, "card_id": n_rfid, 
                        "course": n_course, "fingerprint_id": n_fpid, "registered_date": n_date
                    })
                    st.success("Student records successfully synchronized!"); st.rerun()

    with tab_list:
        if cards_data:
            # Registry display sorted by Student ID
            reg_df = pd.DataFrame(list(cards_data.values()))
            reg_df = reg_df.reindex(columns=['student_id', 'name', 'course', 'card_id', 'fingerprint_id']).fillna("N/A")
            st.subheader("Master Registry (Sorted by ID)")
            st.dataframe(reg_df.sort_values("student_id"), use_container_width=True)
            
            # Profile deletion logic
            st.markdown("---")
            del_id = st.selectbox("Select Student ID to remove:", sorted(students_data.keys()))
            if st.button("🗑️ Permanently Delete Student"):
                db.reference(f'/students/{del_id}').delete()
                st.warning(f"Profile {del_id} erased from cloud database."); st.rerun()

else:
    # --- ATTENDANCE MODE: MONITORING & MODULE 3 ANALYTICS ---
    tab_live, tab_m3 = st.tabs(["📺 Live Monitoring", "📊 Module 3: Reporting & Visualization"])
    
    with tab_live:
        st.subheader("📋 Real-time Smart Attendance Logs")
        if not df_all.empty:
            # Audit trail showing verification_method and flow_type
            st.dataframe(df_all[['formatted_time', 'name', 'flow_type', 'status', 'student_id', 'verification_method']]
                         .sort_values('formatted_time', ascending=False), use_container_width=True)
        else: st.info("Hardware active. Waiting for student entry signals...")

    with tab_m3:
        st.header("📈 Advanced Analytics (Module 3 Compliance)")
        
        if not df_all.empty:
            # 4.1 STAY DURATION CALCULATION
            st.subheader("⏱️ Daily Attendance Duration Analysis")
            duration_data = []
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            for sid in students_data.keys():
                personal_today = df_all[(df_all['student_id'] == sid) & (df_all['record_date'] == today_str)].sort_values('dt_obj')
                if len(personal_today) >= 2:
                    # Logic: Duration = Last tap minus First tap of the day
                    start, end = personal_today.iloc[0]['dt_obj'], personal_today.iloc[-1]['dt_obj']
                    hrs = round((end - start).total_seconds() / 3600, 2)
                    duration_data.append({"ID": sid, "Name": students_data[sid].get('name'), "Duration_Hrs": hrs})
            
            if duration_data:
                viz_df = pd.DataFrame(duration_data)
                st.table(viz_df)
                
                # --- VIZ 1: STAY DURATION BAR CHART (Web App Analytics) ---
                st.subheader("Stay Duration Visualization")
                fig_dur, ax_dur = plt.subplots(figsize=(10, 4))
                sns.barplot(x="ID", y="Duration_Hrs", data=viz_df, palette="magma", ax=ax_dur)
                st.pyplot(fig_dur)
            else:
                st.info("Insufficient data for duration calculation (Requires Check-in & Leave scans).")

            st.markdown("---")
            # 4.2 STATUS DISTRIBUTION & MANUAL MGMT
            c_pie, c_ops = st.columns([1, 1])
            with c_pie:
                # --- VIZ 2: STATUS PIE CHART (Web App Analytics) ---
                st.subheader("Overall Status Distribution")
                status_counts = df_all['status'].value_counts()
                fig_pie, ax_pie = plt.subplots()
                ax_pie.pie(status_counts, labels=status_counts.index, autopct='%1.1f%%', startangle=90, colors=['#2ecc71', '#f1c40f', '#e74c3c'])
                st.pyplot(fig_pie)
                
            with c_ops:
                st.subheader("📝 Manual Record Management")
                with st.form("manual_adj"):
                    m_sid = st.selectbox("Select Student:", list(students_data.keys()))
                    m_status = st.selectbox("Manual Adjustment:", ["present", "absent (Medical Leave)", "absent"])
                    if st.form_submit_button("Update Report"):
                        t_key = datetime.now().strftime("%Y-%m-%d")
                        db.reference(f'/attendance/{t_key}').push().set({
                            'student_id': m_sid, 'name': students_data[m_sid].get('name', 'N/A'),
                            'status': m_status, 'timestamp': int(time.time()), 
                            'verification_method': "Manual_Admin_Adjustment"
                        }); st.rerun()
                
                # FEATURE: LOG DELETION
                st.markdown("---")
                log_labels = df_all['formatted_time'] + " | " + df_all['name']
                to_del = st.selectbox("Erase specific attendance entry:", log_labels.tolist())
                if st.button("🗑️ Confirm Erase Entry"):
                    path = df_all[log_labels == to_del]['firebase_path'].values[0]
                    db.reference(f'/attendance/{path}').delete(); st.rerun()

            st.markdown("---")
            # 4.3 PERMANENT RECORD BRIDGE (Excel Export)
            st.subheader("💾 Export Official Data Report")
            st.write("Bridging Firebase data to Excel for permanent archival.")
            export_df = df_all[['formatted_time', 'name', 'student_id', 'status', 'verification_method']].copy()
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Official_Attendance')
                writer.close()
            st.download_button(label="📥 Download Excel Sync (.xlsx)", data=buffer.getvalue(), 
                               file_name=f"BMIT2123_Report_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")
        else: st.info("No analytics available yet.")

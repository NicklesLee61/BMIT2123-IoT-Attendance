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

if not firebase_admin._apps:
    try:
        if "firebase" in st.secrets:
            cred_dict = dict(st.secrets["firebase"])
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        else:
            cred = credentials.Certificate("service-account-key.json")
            
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
        })
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

if isinstance(cards_raw, dict):
    for push_id, card_info in cards_raw.items():
        sid = card_info.get('student_id')
        if sid and sid not in students_data:
            students_data[sid] = {
                "name": card_info.get('name', 'Unknown'),
                "course": card_info.get('course', 'Unknown'),
                "student_id": sid
            }

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
    df_all = df_all.sort_values('dt_obj')
    df_all['tap_rank'] = df_all.groupby(['student_id', 'record_date']).cumcount() + 1
    
    def determine_flow(row):
        stat = str(row.get('status', '')).lower()
        if 'absent' in stat: return "--"
        if stat == 'leave': return "Check-out (Early)"
        return "Check-in" if row['tap_rank'] % 2 != 0 else "Check-out"
            
    df_all['flow_type'] = df_all.apply(determine_flow, axis=1)

# ==========================================================
# 3. SIDEBAR: REMOTE HARDWARE COMMAND CENTER
# ==========================================================
st.sidebar.title("🎮 Master Control Center")
st.sidebar.markdown(f"**Physical System Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Operations", expanded=True):
    target_mode = st.selectbox("Switch Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Apply Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()

    st.markdown("---")
    if st.sidebar.button("🔔 Trigger Remote Buzzer"):
        control_ref.update({"trigger_buzzer": True})
        time.sleep(1) 
        control_ref.update({"trigger_buzzer": False})
        st.sidebar.success("Buzzer signal sent!")
        
    is_locked = st.sidebar.toggle("🔒 Sensor Lockdown", value=hw_state.get('is_locked', False))
    control_ref.update({"is_locked": is_locked})

with st.sidebar.expander("🔍 System ID & Hardware Check", expanded=False):
    st.markdown("**1. Hardware Sensor Check**")
    if st.button("🔍 Query Sensor FP IDs"):
        control_ref.update({"request_id_list": True})
        st.toast("Requesting hardware data...")

    fp_status = db.reference('/system_status/fp_ids').get()
    if fp_status: st.info(f"Sensor Occupied FP IDs: \n{fp_status}")
    st.markdown("---")
    st.markdown("**2. Quick Lookup (RFID & Fingerprint)**")
    lookup_list = ["-- Select Profile --"] + sorted(list(students_data.keys()))
    selected_lookup = st.selectbox("Search Student ID:", lookup_list)
    
    if selected_lookup != "-- Select Profile --":
        # Find ID in /cards
        c_info = next((v for v in cards_raw.values() if v.get('student_id') == selected_lookup), None)
        r_id = c_info.get('card_id', 'Unlinked') if c_info else "No Record"
        f_id = c_info.get('fingerprint_id', 'Unlinked') if c_info else "No Record"
        st.success(f"💳 **RFID:** `{r_id}`\n\n👆 **FP ID:** `{f_id}`")

# ==========================================================
# 4. DYNAMIC INTERFACE: MODE-AWARE DASHBOARD
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    tab_reg, tab_list = st.tabs(["➕ Student Registration / Re-bind", "🗃️ Master Registry"])
    
    with tab_reg:
        st.subheader("Student Registry & Smart Re-binding")
        st.info("💡 To **re-bind a lost card**, enter the existing Student ID and fill in the new RFID UID.")
        with st.form("enroll_form"):
            c1, c2 = st.columns(2)
            with c1:
                n_id = st.text_input("Student ID (Matches existing for re-bind):")
                n_name = st.text_input("Full Name:")
                n_course = st.text_input("Academic Program:") 
            with c2:
                n_rfid = st.text_input("New RFID UID:")
                n_fpid = st.text_input("Fingerprint Token (Slot ID):")
                n_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            if st.form_submit_button("Finalize Registration / Update"):
                if n_id and n_name:
                    db.reference(f'/students/{n_id}').update({
                        "student_id": n_id, "name": n_name, "rfid": n_rfid if n_rfid else "Unlinked", 
                        "course": n_course, "registered_date": n_date
                    })
                    # Re-bind logic for /cards
                    existing_key = next((k for k, v in cards_raw.items() if v.get('student_id') == n_id), None)
                    card_payload = {
                        "student_id": n_id, "name": n_name, "card_id": n_rfid, 
                        "course": n_course, "fingerprint_id": n_fpid, "registered_date": n_date
                    }
                    if existing_key:
                        db.reference(f'/cards/{existing_key}').update(card_payload)
                    else:
                        db.reference('/cards').push().set(card_payload)
                    st.success(f"Profile {n_id} updated successfully!"); st.rerun()

    with tab_list:
        if students_data:
            master_registry = []
            for sid, info in students_data.items():
                card_info = next((v for v in cards_raw.values() if v.get('student_id') == sid), {})
                master_registry.append({
                    "student_id": sid, "name": info.get('name', 'N/A'), "course": info.get('course', 'N/A'),
                    "RFID_UID": card_info.get('card_id', 'Unlinked'), "FP_ID": card_info.get('fingerprint_id', 'N/A')
                })
            st.dataframe(pd.DataFrame(master_registry).sort_values("student_id"), use_container_width=True)

else:
    tab_live, tab_console, tab_m3 = st.tabs(["📺 Live Monitoring", "🛠️ Manual Record Console", "📊 Module 3: Reporting"])
    
    with tab_live:
        st.subheader("📋 Real-time Smart Attendance Feed")
        if not df_all.empty:
            display_df = df_all[['formatted_time', 'name', 'flow_type', 'status', 'student_id', 'verification_method']].sort_values('formatted_time', ascending=False)
            display_df = display_df.reset_index(drop=True)
            display_df.index = display_df.index + 1
            st.dataframe(display_df, use_container_width=True)
        else: st.info("Waiting for hardware synchronization...")

    with tab_console:
        st.header("🛠️ Attendance Management Console")
        c_add, c_mod = st.columns(2)
        with c_add:
            st.subheader("➕ Create Manual Record")
            with st.form("force_add_form"):
                m_sid = st.selectbox("Target Profile:", sorted(students_data.keys()))
                m_date = st.date_input("Date:", datetime.now())
                m_time = st.time_input("Time:", dt_time(9, 0))
                m_status = st.selectbox("Status:", ["present", "absent", "late", "absent (Medical Leave)", "leave"])
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
                    new_stat = st.selectbox("Change to:", ["present", "absent", "late", "absent (Medical Leave)", "leave"])
                    if st.button("Update Entry"):
                        db.reference(f'/attendance/{row["firebase_path"]}').update({'status': new_stat, 'verification_method': "Admin_Manual_Update"})
                        st.success("Updated!"); st.rerun()
                if st.button("🗑️ Delete Entry", key="del_entry"):
                    db.reference(f'/attendance/{row["firebase_path"]}').delete()
                    st.warning("Removed."); st.rerun()

    with tab_m3:
        st.header("📊 Module 3: Advanced Analytics Interface")
        if not df_all.empty:
            st.subheader("⏱️ Daily Attendance Duration Analysis")
            duration_data = []
            today_str = datetime.now().strftime("%Y-%m-%d")
            valid_df = df_all[~df_all['status'].astype(str).str.contains('absent', case=False, na=False)]
            for sid in students_data.keys():
                p_today = valid_df[(valid_df['student_id'] == sid) & (valid_df['record_date'] == today_str)].sort_values('dt_obj')
                if len(p_today) >= 2:
                    hrs = round((p_today.iloc[-1]['dt_obj'] - p_today.iloc[0]['dt_obj']).total_seconds() / 3600, 2)
                    duration_data.append({"ID": sid, "Name": students_data[sid].get('name'), "Duration_Hrs": hrs})
            
            if duration_data:
                sns.barplot(x="ID", y="Duration_Hrs", data=pd.DataFrame(duration_data), palette="viridis")
                st.pyplot(plt.gcf()); plt.clf()
            else: st.info("Requires check-in/out logs.")

            st.subheader("Lecture Status Distribution")
            status_counts = df_all['status'].value_counts()
            plt.pie(status_counts, labels=status_counts.index, autopct='%1.1f%%', colors=['#2ecc71', '#f1c40f', '#e74c3c', '#95a5a6'])
            st.pyplot(plt.gcf()); plt.clf()
            
            st.markdown("---")
            st.subheader("📈 Daily Attendance Trend (Interactive)")
            unique_daily = df_all.drop_duplicates(subset=['record_date', 'student_id', 'status'])
            if not unique_daily.empty:
                daily_trend = unique_daily.groupby(['record_date', 'status']).size().reset_index(name='Count')
                chart_data = daily_trend.pivot(index='record_date', columns='status', values='Count').fillna(0)
                st.bar_chart(chart_data, use_container_width=True)

            st.markdown("---")
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df_all[['formatted_time', 'name', 'student_id', 'status', 'flow_type', 'verification_method']].to_excel(writer, index=False)
            st.download_button("📥 Download Report (.xlsx)", data=buffer.getvalue(), file_name="Report.xlsx", mime="application/vnd.ms-excel")

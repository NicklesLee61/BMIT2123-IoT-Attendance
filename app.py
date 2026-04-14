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

profile_mapping = {}
for sid, info in students_data.items():
    display_name = f"{info.get('name', 'Unknown')} ({sid})"
    profile_mapping[display_name] = sid

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
# 🚀 GLOBAL UI HELPER: Emoji Formatters
# ==========================================================
def display_status_emoji(s):
    s_lower = str(s).lower()
    if 'present' in s_lower: return f"🟢 {s}"
    elif 'absent' in s_lower: return f"🔴 {s}"
    elif 'late' in s_lower: return f"🟠 {s}"
    elif 'leave' in s_lower: return f"🔵 {s}"
    return s
    
def display_flow_emoji(f):
    if 'Check-in' in str(f): return f"🟢 {f}"
    elif 'Check-out' in str(f): return f"🔵 {f}"
    elif f == '--': return f"⚪ {f}"
    return f

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

# ==========================================================
# 4. DYNAMIC INTERFACE: MODE-AWARE DASHBOARD
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    tab_reg, tab_list, tab_diag = st.tabs(["➕ Student Registration / Re-bind", "🗃️ Master Registry", "⚙️ Hardware Diagnostics"])
    
    with tab_reg:
        st.subheader("Student Registry & Smart Re-binding")
        st.info("💡 To **re-bind a lost card**, enter the existing Student ID and fill in the new RFID UID.")
        with st.form("enroll_form"):
            c1, c2 = st.columns(2)
            with c1:
                n_id = st.text_input("Student ID (Required):").strip()
                n_name = st.text_input("Full Name:").strip()
                n_course = st.text_input("Academic Program:").strip()
            with c2:
                n_rfid = st.text_input("New RFID UID:").strip()
                n_fpid = st.text_input("Fingerprint Token (Slot ID):").strip()
                n_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            if st.form_submit_button("Finalize Registration / Update"):
                if n_id:
                    rfid_owners = {v.get('card_id'): v.get('student_id') for v in cards_raw.values() if str(v.get('card_id')) not in ['Unlinked', '', 'None']}
                    fpid_owners = {v.get('fingerprint_id'): v.get('student_id') for v in cards_raw.values() if str(v.get('fingerprint_id')) not in ['Unlinked', '', 'None']}
                    has_conflict = False
                    if n_rfid and n_rfid in rfid_owners and rfid_owners[n_rfid] != n_id:
                        st.error(f"❌ **Hardware Conflict:** RFID UID `{n_rfid}` is already in use by ID: {rfid_owners[n_rfid]}提升"); has_conflict = True
                    if n_fpid and n_fpid in fpid_owners and fpid_owners[n_fpid] != n_id:
                        st.error(f"❌ **Hardware Conflict:** FP Token `{n_fpid}` is already in use by ID: {fpid_owners[n_fpid]}"); has_conflict = True
                    if n_id in students_data and n_name:
                        existing_name = students_data[n_id].get('name', '')
                        if existing_name and n_name.lower() != existing_name.lower():
                            st.error(f"❌ **ID Conflict:** Student ID `{n_id}` is already registered."); has_conflict = True

                    if not has_conflict:
                        exist_stu = students_data.get(n_id, {})
                        exist_card_key = next((k for k, v in cards_raw.items() if v.get('student_id') == n_id), None)
                        exist_card = cards_raw.get(exist_card_key, {}) if exist_card_key else {}
                        db.reference(f'/students/{n_id}').update({
                            "student_id": n_id, "name": n_name if n_name else exist_stu.get('name', 'Unknown'),
                            "rfid": n_rfid if n_rfid else exist_card.get('card_id', 'Unlinked'), 
                            "course": n_course if n_course else exist_stu.get('course', 'Unknown'), "registered_date": n_date
                        })
                        card_payload = {
                            "student_id": n_id, "name": n_name if n_name else exist_stu.get('name', 'Unknown'),
                            "card_id": n_rfid if n_rfid else exist_card.get('card_id', 'Unlinked'), 
                            "course": n_course if n_course else exist_stu.get('course', 'Unknown'),
                            "fingerprint_id": n_fpid if n_fpid else exist_card.get('fingerprint_id', 'Unlinked'), "registered_date": n_date
                        }
                        if exist_card_key: db.reference(f'/cards/{exist_card_key}').update(card_payload)
                        else: db.reference('/cards').push().set(card_payload)
                        st.success(f"Profile {n_id} established!"); st.rerun()
                else: st.error("⚠️ Student ID is required.")

    with tab_list:
        if students_data:
            master_registry = []
            for sid, info in students_data.items():
                card_info = next((v for v in cards_raw.values() if v.get('student_id') == sid), {})
                master_registry.append({"student_id": sid, "name": info.get('name', 'N/A'), "course": info.get('course', 'N/A'), "RFID_UID": card_info.get('card_id', 'Unlinked'), "FP_ID": card_info.get('fingerprint_id', 'N/A')})
            reg_df = pd.DataFrame(master_registry).sort_values("student_id")
            search_query = st.text_input("🔍 Search Student (by ID, Name, or Course):")
            if search_query:
                reg_df = reg_df[reg_df[['student_id', 'name', 'course']].apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)]
            reg_df = reg_df.reset_index(drop=True); reg_df.index += 1
            st.dataframe(reg_df, use_container_width=True)
            st.markdown("---")
            st.subheader("⚠️ Danger Zone: Remove Student")
            if profile_mapping:
                del_disp = st.selectbox("Select Student Profile to remove:", sorted(profile_mapping.keys()))
                if 'delete_target' not in st.session_state: st.session_state['delete_target'] = None
                if st.session_state['delete_target'] != del_disp: st.session_state['delete_target'] = None
                if st.session_state['delete_target'] != del_disp:
                    if st.button("🗑️ Request Profile Deletion"): st.session_state['delete_target'] = del_disp; st.rerun()
                else:
                    st.error(f"🛑 ARE YOU SURE? Erase **{del_disp}**?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ Yes, Erase", type="primary"):
                            del_id = profile_mapping[del_disp]
                            db.reference(f'/students/{del_id}').delete()
                            card_key = next((k for k, v in cards_raw.items() if v.get('student_id') == del_id), None)
                            if card_key: db.reference(f'/cards/{card_key}').delete()
                            st.session_state['delete_target'] = None; st.rerun()
                    with c2:
                        if st.button("❌ Cancel"): st.session_state['delete_target'] = None; st.rerun()

    # ==========================================================
    # ⚙️ CLEANER tab_diag: AUTOMATED MONITORING ONLY
    # ==========================================================
    with tab_diag:
        st.subheader("⚙️ Real-time System Monitoring")
        st.write("Live status tracking for the physical IoT hardware.")

        # --- Automated Metrics ---
        m1, m2, m3 = st.columns(3)
        
        last_seen_ts = db.reference('/system_status/last_seen').get() or 0
        is_online = (time.time() - last_seen_ts) < 60 
        m1.metric("Hardware Status", "ONLINE 🟢" if is_online else "OFFLINE 🔴")
        
        fp_list_raw = db.reference('/system_status/fp_ids').get() or []
        used_slots = len(fp_list_raw) if isinstance(fp_list_raw, list) else 0
        m2.metric("FP Storage Usage", f"{used_slots} / 127 Slots")
        
        m3.metric("Network Stability", "Stable ✅" if is_online else "Check Connection ⚠️")

        st.write("---")

        # --- Live Logs (Terminal Style) ---
        with st.container(border=True):
            st.markdown("#### 📟 Live Hardware Event Log")
            # This proves the system is "talking" to the cloud
            raw_logs = db.reference('/system_status/logs').get() or ["System waiting for hardware heartbeat..."]
            log_box = ""
            log_entries = list(raw_logs.values()) if isinstance(raw_logs, dict) else list(raw_logs)
            for entry in log_entries[-8:]: 
                log_box += f"> {entry}\n"
            st.code(log_box, language="bash")
            
            # Visual storage bar
            st.progress(min(used_slots / 127, 1.0), text=f"Fingerprint memory: {round((used_slots/127)*100, 1)}%")

        st.caption(f"Last heartbeat from Raspberry Pi: {datetime.fromtimestamp(last_seen_ts).strftime('%Y-%m-%d %H:%M:%S') if last_seen_ts else 'Waiting...'}")

else:
    tab_live, tab_console, tab_m3 = st.tabs(["📺 Live Monitoring", "🛠️ Manual Record Console", "📊 Module 3: Reporting"])
    
    with tab_live:
        st.subheader("📋 Real-time Smart Attendance Feed")
        if not df_all.empty:
            c1, c2 = st.columns(2)
            with c1: selected_date = st.date_input("📅 Filter by Date:", datetime.now(), key="live_date")
            with c2: search_log = st.text_input("🔍 Search Record:", key="search_log_monitoring")
            view_df = df_all[df_all['record_date'] == selected_date.strftime("%Y-%m-%d")]
            if not view_df.empty:
                latest_daily = view_df.drop_duplicates(subset=['student_id'], keep='last')
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("🟢 Present", len(latest_daily[latest_daily['status'] == 'present']))
                k2.metric("🔴 Absent", len(latest_daily[latest_daily['status'].astype(str).str.contains('absent', case=False)]))
                k3.metric("🟠 Late", len(latest_daily[latest_daily['status'] == 'late']))
                k4.metric("🔵 Leave", len(latest_daily[latest_daily['status'] == 'leave']))
                st.markdown("---")
                display_df = view_df[['formatted_time', 'name', 'flow_type', 'status', 'student_id', 'verification_method']].sort_values('formatted_time', ascending=False).copy()
                if search_log: display_df = display_df[display_df[['student_id', 'name']].apply(lambda row: row.astype(str).str.contains(search_log, case=False).any(), axis=1)]
                display_df['status'] = display_df['status'].apply(display_status_emoji)
                display_df['flow_type'] = display_df['flow_type'].apply(display_flow_emoji)
                display_df = display_df.reset_index(drop=True); display_df.index += 1
                st.dataframe(display_df, use_container_width=True)
            else: st.info("No records found.")
        else: st.info("Waiting for hardware synchronization...")

    with tab_console:
        st.header("🛠️ Attendance Management Console")
        st.write("---")
        st.markdown("<br>", unsafe_allow_html=True) 
        c_add, c_mod = st.columns(2, gap="large") 
        with c_add:
            with st.container(border=True):
                st.markdown("### ➕ Create Manual Record")
                sc = st.text_input("🔍 Search Profile:", key="sc_create", label_visibility="collapsed")
                with st.form("force_add_form", clear_on_submit=True):
                    if profile_mapping:
                        opts = sorted(profile_mapping.keys())
                        if sc: opts = [p for p in opts if sc.lower() in p.lower()]
                        if opts:
                            m_disp = st.selectbox("Select Student:", opts)
                            dc, tc = st.columns(2)
                            m_date = dc.date_input("Date:", datetime.now(), key="ma_date")
                            m_time = tc.time_input("Time:", dt_time(9, 0))
                            m_status = st.selectbox("Status:", ["present", "absent", "late", " MEDICAL absent", "leave"], format_func=display_status_emoji)
                            if st.form_submit_button("Force Sync New Record", type="primary"):
                                m_sid = profile_mapping[m_disp]
                                db.reference(f'/attendance/{m_date.strftime("%Y-%m-%d")}').push().set({'student_id': m_sid, 'name': students_data[m_sid].get('name'), 'status': m_status, 'timestamp': int(datetime.combine(m_date, m_time).timestamp()), 'verification_method': "Manual_Admin"})
                                st.rerun()
        with c_mod:
            with st.container(border=True):
                st.markdown("### 📝 Modify or Delete Entries")
                if not df_all.empty:
                    sa = st.checkbox("🕰️ View All History")
                    f1, f2 = st.columns([1.5, 2])
                    md = f1.date_input("Filter Date:", datetime.now(), disabled=sa)
                    fo = ["-- All Students --"] + sorted(profile_mapping.keys())
                    ms = f2.selectbox("Filter Student:", fo)
                    f_df = df_all.copy() if sa else df_all[df_all['record_date'] == md.strftime("%Y-%m-%d")]
                    if ms != "-- All Students --": f_df = f_df[f_df['student_id'] == profile_mapping[ms]]
                    if not f_df.empty:
                        lbls = f_df['formatted_time'] + " | " + f_df['name'] + " (" + f_df['status'].apply(display_status_emoji) + ")"
                        to_m = st.selectbox("Records Selector:", lbls.tolist(), label_visibility="collapsed")
                        row = f_df[lbls == to_m].iloc[0]
                        with st.expander("✏️ Update status", expanded=True):
                            ns = st.selectbox("Change to:", ["present", "absent", "late", " MEDICAL absent", "leave"], format_func=display_status_emoji)
                            if st.button("Submit Status Update", type="secondary"): 
                                db.reference(f'/attendance/{row["firebase_path"]}').update({'status': ns, 'verification_method': "Admin_Manual"})
                                st.rerun()
                        if st.button("🗑️ Permanently Delete Entry", key="del_ent"): 
                            db.reference(f'/attendance/{row["firebase_path"]}').delete()
                            st.rerun()
                    else: st.info("No records match filters.")
                else: st.info("No attendance records available.")

    with tab_m3:
        st.header("📊 Module 3: Advanced Analytics Interface")
        if not df_all.empty:
            with st.container(border=True):
                st.subheader("📈 Daily Attendance Trend (Interactive)")
                unique_daily = df_all.drop_duplicates(subset=['record_date', 'student_id', 'status'])
                if not unique_daily.empty:
                    daily_trend = unique_daily.groupby(['record_date', 'status']).size().reset_index(name='Count')
                    chart_data = daily_trend.pivot(index='record_date', columns='status', values='Count').fillna(0)
                    st.area_chart(chart_data, use_container_width=True)

            col_a, col_b = st.columns(2, gap="medium")
            with col_a:
                with st.container(border=True):
                    st.subheader("⏱️ Stay Duration Analysis")
                    duration_data = []
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    valid_df = df_all[~df_all['status'].astype(str).str.contains('absent', case=False, na=False)]
                    for sid in students_data.keys():
                        p_today = valid_df[(valid_df['student_id'] == sid) & (valid_df['record_date'] == today_str)].sort_values('dt_obj')
                        if len(p_today) >= 2:
                            hrs = round((p_today.iloc[-1]['dt_obj'] - p_today.iloc[0]['dt_obj']).total_seconds() / 3600, 2)
                            duration_data.append({"ID": sid, "Hrs": hrs})
                    if duration_data: st.bar_chart(pd.DataFrame(duration_data).set_index('ID'), use_container_width=True)
                    else: st.info("Requires multiple logs for today.")

            with col_b:
                with st.container(border=True):
                    st.subheader("🍕 Status Composition")
                    status_counts = df_all['status'].value_counts()
                    fig_pie, ax_pie = plt.subplots(figsize=(5, 5))
                    fig_pie.patch.set_facecolor('#0e1117') 
                    status_counts.plot.pie(autopct='%1.1f%%', colors=['#2ecc71', '#e74c3c', '#f1c40f', '#3498db', '#95a5a6'], ax=ax_pie, textprops={'color':"w"}, startangle=90, wedgeprops={'edgecolor': '#0e1117'})
                    ax_pie.set_ylabel(''); st.pyplot(fig_pie)

            with st.container(border=True):
                st.subheader("📥 Data Export Center")
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_all[['formatted_time', 'name', 'student_id', 'status', 'flow_type', 'verification_method']].to_excel(writer, index=False)
                st.download_button(label="📂 Download Full Attendance Report (.xlsx)", data=buffer.getvalue(), file_name=f"Report_{datetime.now().strftime('%Y%m%d')}.xlsx", use_container_width=True)
        else: st.warning("No analytics available yet.")

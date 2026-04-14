import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import plotly.express as px
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
# 3. SIDEBAR: PURE REMOTE HARDWARE COMMAND CENTER
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
    # 🚀 UPDATED: Removed tab_diag
    tab_reg, tab_list = st.tabs(["➕ Student Registration / Re-bind", "🗃️ Master Registry"])
    
    with tab_reg:
        st.subheader("Student Registry & Smart Re-binding")
        st.info("💡 To **re-bind a lost card**, enter the existing Student ID and fill in the new RFID UID. Leave other fields blank to keep existing data.")
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
                        st.error(f"❌ **Hardware Conflict:** RFID UID `{n_rfid}` is already in use by Student ID: {rfid_owners[n_rfid]}"); has_conflict = True
                    if n_fpid and n_fpid in fpid_owners and fpid_owners[n_fpid] != n_id:
                        st.error(f"❌ **Hardware Conflict:** FP Token `{n_fpid}` is already in use by Student ID: {fpid_owners[n_fpid]}"); has_conflict = True
                    if n_id in students_data and n_name:
                        existing_name = students_data[n_id].get('name', '')
                        if existing_name and n_name.lower() != existing_name.lower():
                            st.error(f"❌ **ID Conflict:** Student ID `{n_id}` is already registered. If you meant to re-bind their card, leave 'Full Name' blank."); has_conflict = True

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
                        st.success(f"Profile {n_id} successfully updated!"); st.rerun()
                else: st.error("⚠️ Student ID is required.")

    with tab_list:
        if students_data:
            master_registry = []
            for sid, info in students_data.items():
                card_info = next((v for v in cards_raw.values() if v.get('student_id') == sid), {})
                master_registry.append({"student_id": sid, "name": info.get('name', 'N/A'), "course": info.get('course', 'N/A'), "RFID_UID": card_info.get('card_id', 'Unlinked'), "FP_ID": card_info.get('fingerprint_id', 'N/A')})
            reg_df = pd.DataFrame(master_registry).sort_values("student_id")
            search_query = st.text_input("🔍 Search Student (by ID, Name, or Course):", placeholder="e.g. 2413458, Sakiko...")
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
                    st.error(f"🛑 ARE YOU SURE? This will permanently erase **{del_disp}**.")
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if st.button("✅ Yes, Delete", type="primary"):
                            del_id = profile_mapping[del_disp]
                            db.reference(f'/students/{del_id}').delete()
                            ckey = next((k for k, v in cards_raw.items() if v.get('student_id') == del_id), None)
                            if ckey: db.reference(f'/cards/{ckey}').delete()
                            st.session_state['delete_target'] = None; st.rerun()
                    with cc2:
                        if st.button("❌ Cancel"): st.session_state['delete_target'] = None; st.rerun()

else:
    tab_live, tab_console, tab_m3 = st.tabs(["📺 Live Monitoring", "🛠️ Manual Record Console", "📊 Module 3: Reporting"])
    
    with tab_live:
        st.subheader("📋 Real-time Smart Attendance Feed")
        if not df_all.empty:
            c1, c2 = st.columns(2)
            with c1: sel_date = st.date_input("📅 Date:", datetime.now(), key="l_date")
            with c2: search_l = st.text_input("🔍 Search Record (by ID or Name):", key="l_search")
            view_df = df_all[df_all['record_date'] == sel_date.strftime("%Y-%m-%d")]
            if not view_df.empty:
                latest = view_df.drop_duplicates(subset=['student_id'], keep='last')
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("🟢 Present", len(latest[latest['status'] == 'present']))
                k2.metric("🔴 Absent", len(latest[latest['status'].astype(str).str.contains('absent', case=False)]))
                k3.metric("🟠 Late", len(latest[latest['status'] == 'late']))
                k4.metric("🔵 Leave", len(latest[latest['status'] == 'leave']))
                st.write("---")
                disp = view_df[['formatted_time', 'name', 'flow_type', 'status', 'student_id', 'verification_method']].sort_values('formatted_time', ascending=False).copy()
                if search_l: disp = disp[disp[['student_id', 'name']].apply(lambda row: row.astype(str).str.contains(search_l, case=False).any(), axis=1)]
                
                if not disp.empty:
                    disp['status'] = disp['status'].apply(display_status_emoji); disp['flow_type'] = disp['flow_type'].apply(display_flow_emoji)
                    disp = disp.reset_index(drop=True); disp.index += 1
                    st.dataframe(disp, use_container_width=True)
                else: st.warning(f"No matching records found for '{search_l}'.")
            else: st.info(f"No records for {sel_date.strftime('%Y-%m-%d')}.")
        else: st.info("Waiting for hardware synchronization...")

    with tab_console:
        st.header("🛠️ Attendance Management Console")
        st.write("---")
        ca, cm = st.columns(2, gap="large")
        
        with ca:
            with st.container(border=True):
                st.markdown("### ➕ Create Manual Record")
                st.write("Forbid hardware and manually force a log.")
                st.write("<br>", unsafe_allow_html=True)
                sc = st.text_input("🔍 Search Profile (by ID or Name):", key="m_sc", label_visibility="collapsed", placeholder="e.g. Sakiko...")
                with st.form("add_form", clear_on_submit=True):
                    if profile_mapping:
                        opts = sorted([p for p in profile_mapping.keys() if sc.lower() in p.lower()]) if sc else sorted(profile_mapping.keys())
                        if opts:
                            m_disp = st.selectbox("Selected Student Profile:", opts)
                            st.write("<br>", unsafe_allow_html=True)
                            d1, t1 = st.columns(2)
                            md = d1.date_input("Date:", datetime.now(), key="m_d")
                            mt = t1.time_input("Time:", dt_time(9, 0))
                            st.write("<br>", unsafe_allow_html=True)
                            ms = st.selectbox("Status:", ["present", "absent", "late", "absent (Medical Leave)", "leave"], format_func=display_status_emoji)
                            st.write("<br>", unsafe_allow_html=True)
                            if st.form_submit_button("Force Sync New Record", type="primary"):
                                m_sid = profile_mapping[m_disp]
                                db.reference(f'/attendance/{md.strftime("%Y-%m-%d")}').push().set({'student_id': m_sid, 'name': students_data[m_sid].get('name'), 'status': ms, 'timestamp': int(datetime.combine(md, mt).timestamp()), 'verification_method': "Manual_Admin"})
                                st.toast(f"✅ Record created!")
                                time.sleep(1); st.rerun()
                        else:
                            st.warning("No matches found. Clear search box.")
                            st.form_submit_button("Force Sync", disabled=True)
                            
        with cm:
            with st.container(border=True):
                st.markdown("### 📝 Modify or Delete Entries")
                st.write("Manage historical database records.")
                st.write("<br>", unsafe_allow_html=True)
                if not df_all.empty:
                    st.markdown("##### 1. Find the Record")
                    sa = st.checkbox("🕰️ View All History (Disable Date Filter)", key="m_sa")
                    f1, f2 = st.columns([1.5, 2])
                    fd = f1.date_input("Filter Date:", datetime.now(), disabled=sa, key="m_fd")
                    fo = ["-- All Students --"] + sorted(profile_mapping.keys())
                    fs = f2.selectbox("Filter Student:", fo, key="m_fs")
                    f_df = df_all.copy() if sa else df_all[df_all['record_date'] == fd.strftime("%Y-%m-%d")]
                    if fs != "-- All Students --": f_df = f_df[f_df['student_id'] == profile_mapping[fs]]
                    
                    st.write("---")
                    if not f_df.empty:
                        lbls = f_df['formatted_time'] + " | " + f_df['name'] + " (" + f_df['status'].apply(display_status_emoji) + ")"
                        st.markdown("##### 2. Select entry to manage:")
                        to_m = st.selectbox("Records Selector:", lbls.tolist(), label_visibility="collapsed")
                        row = f_df[lbls == to_m].iloc[0]
                        with st.expander("✏️ Update status for this entry", expanded=True):
                            ns = st.selectbox("Change status to:", ["present", "absent", "late", "absent (Medical Leave)", "leave"], format_func=display_status_emoji)
                            if st.button("Submit Status Update", type="secondary"): 
                                db.reference(f'/attendance/{row["firebase_path"]}').update({'status': ns, 'verification_method': "Admin_Manual_Update"})
                                st.toast("✅ Record updated!")
                                time.sleep(1); st.rerun()
                        st.write("<br>", unsafe_allow_html=True)
                        if st.button("🗑️ Permanently Delete Entry", key="m_del"): 
                            db.reference(f'/attendance/{row["firebase_path"]}').delete()
                            st.toast("🗑️ Record erased.")
                            time.sleep(1); st.rerun()
                    else: st.info("No records match your filters.")
                else: st.info("No attendance records in database.")

    # ==========================================================
    # 📊 tab_m3: ADVANCED ANALYTICS INTERFACE
    # ==========================================================
    with tab_m3:
        st.header("📊 Advanced Analytics Dashboard")
        st.write("Real-time behavioral insights and comprehensive student performance tracking.")
        
        if not df_all.empty:
            # 🎨 Theme Settings for Plotly
            color_map = {
                'present': '#2ecc71',
                'absent': '#e74c3c',
                'absent (Medical Leave)': '#e74c3c',
                'late': '#f39c12',
                'leave': '#3498db'
            }

            # 🚀 1. TREND CHART (NATIVE BAR CHART)
            with st.container(border=True):
                st.subheader("📈 Daily Attendance Trend")
                unique_daily = df_all.drop_duplicates(subset=['record_date', 'student_id', 'status'])
                if not unique_daily.empty:
                    daily_trend = unique_daily.groupby(['record_date', 'status']).size().reset_index(name='Count')
                    chart_data = daily_trend.pivot(index='record_date', columns='status', values='Count').fillna(0)
                    st.bar_chart(chart_data, use_container_width=True)
                    
            # 🚀 2. COLUMNS (DURATION & COMPOSITION)
            cola, colb = st.columns(2, gap="large")
            
            with cola:
                with st.container(border=True):
                    st.subheader("⏱️ Stay Duration Analysis")
                    st.caption("Active hours spent in today's session")
                    dur_data = []
                    today_s = datetime.now().strftime("%Y-%m-%d")
                    valid_df = df_all[~df_all['status'].astype(str).str.contains('absent', case=False, na=False)]
                    
                    for sid in students_data.keys():
                        p_t = valid_df[(valid_df['student_id'] == sid) & (valid_df['record_date'] == today_s)].sort_values('dt_obj')
                        if len(p_t) >= 2: 
                            hrs = round((p_t.iloc[-1]['dt_obj'] - p_t.iloc[0]['dt_obj']).total_seconds() / 3600, 2)
                            dur_data.append({"ID": sid, "Hrs": hrs}) 
                            
                    if dur_data: 
                        dur_df = pd.DataFrame(dur_data)
                        st.bar_chart(dur_df.set_index('ID'), use_container_width=True)
                    else: 
                        st.info("💡 Check-in and Check-out logs needed for today to calculate duration.")
                        
            with colb:
                with st.container(border=True):
                    st.subheader("🍩 Status Composition")
                    st.caption("Overall class participation distribution")
                    
                    s_c = df_all['status'].value_counts().reset_index()
                    s_c.columns = ['Status', 'Count']
                    
                    fig_pie = px.pie(
                        s_c, values="Count", names="Status",
                        hole=0.45, 
                        color="Status", color_discrete_map=color_map
                    )
                    fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                    fig_pie.update_layout(
                        showlegend=False,
                        margin=dict(l=0, r=0, t=20, b=0),
                        paper_bgcolor="rgba(0,0,0,0)"
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)
                    
            # 🚀 3. EXPORT
            with st.container(border=True):
                st.subheader("📥 Data Export Center")
                st.write("Generate and download the official lecture attendance report.")
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as wr:
                    df_all[['formatted_time', 'name', 'student_id', 'status', 'flow_type', 'verification_method']].to_excel(wr, index=False)
                st.download_button("📂 Download Full Attendance Report (.xlsx)", data=buf.getvalue(), file_name=f"Smart_Campus_Report_{datetime.now().strftime('%Y%m%d')}.xlsx", use_container_width=True)
        else: 
            st.warning("⚠️ No analytics available yet. Synchronize hardware logs first.")

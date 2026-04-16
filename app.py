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
hw_state = control_ref.get() or {"mode": "Attendance"}
current_hw_mode = hw_state.get('mode', 'Attendance')

# Fetch Main Data Nodes from Firebase
students_data = db.reference('/students').get() or {} 
cards_raw = db.reference('/cards').get() or {}       
attendance_raw = db.reference('/attendance').get() or {}

# Cross-reference students and cards for mapping
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
# 3. SIDEBAR: REMOTE CONTROL
# ==========================================================
st.sidebar.title("🎮 Master Control Center")
st.sidebar.markdown(f"**Physical System Mode:** `{current_hw_mode}`")

with st.sidebar.expander("🛠️ Remote Operations", expanded=True):
    target_mode = st.selectbox("Switch Mode:", ["Attendance", "Enrollment"], 
                               index=0 if current_hw_mode == "Attendance" else 1)
    if st.sidebar.button("Apply Mode Update"):
        control_ref.update({"mode": target_mode})
        st.rerun()

# ==========================================================
# 4. DYNAMIC INTERFACE: MODE-AWARE DASHBOARD
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    st.subheader("Student Enrollment & Management Hub")
    
    # 📡 CLOUD SYNC: Fetch IDs from hardware's last scan
    pending_reg = db.reference('/pending_registration').get()
    scanned_rfid = str(pending_reg.get('rfid', '')) if pending_reg else ""
    scanned_fpid = str(pending_reg.get('fp_id', '')) if pending_reg else ""
    
    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        if st.button("🔄 Fetch Scanned Card", type="primary", use_container_width=True):
            st.rerun()
            
    if pending_reg:
        st.success(f"✅ Hardware scan captured! RFID: `{scanned_rfid}` | FP Slot: `{scanned_fpid}`")
        if st.button("🗑️ Clear Scan Data"):
            db.reference('/pending_registration').delete(); st.rerun()
    else:
        st.info("💡 Tip: Scan a card on the Raspberry Pi first, then click 'Fetch' to auto-fill details.")

    # --- TABS FOR DIFFERENT FUNCTIONS ---
    tab_reg, tab_update, tab_list = st.tabs(["➕ New Registration", "🔄 Update / Re-bind", "🗃️ Master Registry"])
    
    # --- TAB 1: REGISTER NEW STUDENT ---
    with tab_reg:
        st.markdown("### 📝 Create New Profile")
        with st.form("new_student_form"):
            c1, c2 = st.columns(2)
            with c1:
                n_id = st.text_input("Student ID:").strip()
                n_name = st.text_input("Full Name:").strip()
                n_course = st.text_input("Academic Program:").strip()
            with c2:
                # Auto-fills if scanned card is fetched
                n_rfid = st.text_input("RFID UID (Auto-fillable):", value=scanned_rfid).strip()
                n_fpid = st.text_input("Fingerprint Slot (Auto-fillable):", value=scanned_fpid).strip()
            
            if st.form_submit_button("Finalize New Registration"):
                if not n_id or not n_name:
                    st.error("⚠️ Student ID and Name are required!")
                elif n_id in students_data:
                    st.error(f"❌ ID `{n_id}` already exists. Please use the 'Update' tab.")
                else:
                    # Update Firebase
                    payload = {
                        "student_id": n_id, "name": n_name, "course": n_course,
                        "rfid": n_rfid if n_rfid else "Unlinked", 
                        "registered_date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    }
                    db.reference(f'/students/{n_id}').set(payload)
                    db.reference('/cards').push().set({**payload, "card_id": n_rfid, "fingerprint_id": n_fpid})
                    
                    if pending_reg: db.reference('/pending_registration').delete()
                    st.success(f"🎉 Student {n_name} registered successfully!"); time.sleep(1); st.rerun()

    # --- TAB 2: UPDATE OR RE-BIND (補辦卡/修改) ---
    with tab_update:
        st.markdown("### 🔄 Update Student Details or Re-bind Card")
        if profile_mapping:
            u_search = st.text_input("🔍 Search Student to Update (ID or Name):")
            u_opts = sorted([p for p in profile_mapping.keys() if u_search.lower() in p.lower()]) if u_search else sorted(profile_mapping.keys())
            
            if u_opts:
                u_selected = st.selectbox("Select Student Profile:", u_opts)
                u_sid = profile_mapping[u_selected]
                
                # Fetch EXISTING data from Firebase
                curr_stu = students_data.get(u_sid, {})
                # Find their card details in the /cards node
                card_node_key = next((k for k, v in cards_raw.items() if v.get('student_id') == u_sid), None)
                curr_card = cards_raw.get(card_node_key, {}) if card_node_key else {}

                with st.form("update_student_form"):
                    st.write(f"**Target Student:** {curr_stu.get('name')} ({u_sid})")
                    uc1, uc2 = st.columns(2)
                    with uc1:
                        u_name = st.text_input("Update Name:", value=curr_stu.get('name', ''))
                        u_course = st.text_input("Update Course:", value=curr_stu.get('course', ''))
                    with uc2:
                        # LOGIC: Use newly scanned ID if available, otherwise show existing one from Firebase
                        final_rfid = scanned_rfid if scanned_rfid else curr_card.get('card_id', '')
                        final_fpid = scanned_fpid if scanned_fpid else curr_card.get('fingerprint_id', '')
                        
                        u_rfid = st.text_input("RFID UID (Update if scanned):", value=final_rfid)
                        u_fpid = st.text_input("FP Slot (Update if scanned):", value=final_fpid)

                    if st.form_submit_button("Save Changes / Apply Re-bind"):
                        # Update student info
                        db.reference(f'/students/{u_sid}').update({
                            "name": u_name, "course": u_course, "rfid": u_rfid
                        })
                        # Update/Add card info
                        card_data = {
                            "student_id": u_sid, "name": u_name, "course": u_course,
                            "card_id": u_rfid, "fingerprint_id": u_fpid,
                            "registered_date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                        }
                        if card_node_key:
                            db.reference(f'/cards/{card_node_key}').update(card_data)
                        else:
                            db.reference('/cards').push().set(card_data)

                        if pending_reg: db.reference('/pending_registration').delete()
                        st.success("✅ Student profile and hardware IDs updated!"); time.sleep(1); st.rerun()
            else:
                st.warning("No students found matching your search.")
        else:
            st.info("Registry is empty. Register a student first.")

    # --- TAB 3: MASTER REGISTRY (DELETE/VIEW) ---
    with tab_list:
        if students_data:
            master_list = []
            for sid, info in students_data.items():
                # Try to find corresponding card info
                c_info = next((v for v in cards_raw.values() if v.get('student_id') == sid), {})
                master_list.append({
                    "Student ID": sid, "Name": info.get('name'), "Course": info.get('course'),
                    "Current RFID": c_info.get('card_id', 'Unlinked'),
                    "FP Slot": c_info.get('fingerprint_id', 'N/A')
                })
            reg_df = pd.DataFrame(master_list).sort_values("Student ID")
            st.dataframe(reg_df, use_container_width=True, hide_index=True)
            
            st.write("---")
            st.subheader("⚠️ Danger Zone")
            del_target = st.selectbox("Select Profile to Permanently REMOVE:", ["-- Select --"] + sorted(profile_mapping.keys()))
            if del_target != "-- Select --":
                if st.button("🗑️ Delete Student Profile", type="primary"):
                    sid_to_del = profile_mapping[del_target]
                    # Delete from both nodes
                    db.reference(f'/students/{sid_to_del}').delete()
                    ckey = next((k for k, v in cards_raw.items() if v.get('student_id') == sid_to_del), None)
                    if ckey: db.reference(f'/cards/{ckey}').delete()
                    st.error(f"Erased {del_target}"); time.sleep(1); st.rerun()

else:
    # ==========================================================
    # 5. ATTENDANCE TABS (LIVE / CONSOLE / REPORTING)
    # ==========================================================
    tab_live, tab_console, tab_m3 = st.tabs(["📺 Live Monitoring", "🛠️ Manual Record Console", "📊 Module 3: Reporting"])
    
    with tab_live:
        st.subheader("📋 Real-time Smart Attendance Feed")
        if not df_all.empty:
            lc1, lc2 = st.columns(2)
            with lc1: l_date = st.date_input("📅 Date:", datetime.now())
            with lc2: l_search = st.text_input("🔍 Search Record (ID/Name):")
            
            view_df = df_all[df_all['record_date'] == l_date.strftime("%Y-%m-%d")]
            if not view_df.empty:
                latest = view_df.drop_duplicates(subset=['student_id'], keep='last')
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("🟢 Present", len(latest[latest['status'] == 'present']))
                k2.metric("🔴 Absent", len(latest[latest['status'].astype(str).str.contains('absent', case=False)]))
                k3.metric("🟠 Late", len(latest[latest['status'] == 'late']))
                k4.metric("🔵 Leave", len(latest[latest['status'] == 'leave']))
                st.write("---")
                
                disp = view_df[['formatted_time', 'name', 'flow_type', 'status', 'student_id', 'verification_method']].sort_values('formatted_time', ascending=False).copy()
                if l_search: disp = disp[disp[['student_id', 'name']].apply(lambda r: r.astype(str).str.contains(l_search, case=False).any(), axis=1)]
                
                if not disp.empty:
                    disp['status'] = disp['status'].apply(display_status_emoji); disp['flow_type'] = disp['flow_type'].apply(display_flow_emoji)
                    st.dataframe(disp, use_container_width=True, hide_index=True)
                else: st.warning("No records match your search.")
            else: st.info(f"No records for {l_date}.")
        else: st.info("Waiting for hardware synchronization...")

    with tab_console:
        st.header("🛠️ Attendance Management Console")
        st.write("---")
        ca, cm = st.columns(2, gap="large")
        with ca:
            with st.container(border=True):
                st.markdown("### ➕ Create Manual Record")
                sc = st.text_input("🔍 Search Profile (ID/Name):", placeholder="e.g. Sakiko...")
                with st.form("manual_add", clear_on_submit=True):
                    opts = sorted([p for p in profile_mapping.keys() if sc.lower() in p.lower()]) if sc else sorted(profile_mapping.keys())
                    m_sel = st.selectbox("Target Student:", opts) if opts else None
                    d1, t1 = st.columns(2)
                    md = d1.date_input("Date:", datetime.now())
                    mt = t1.time_input("Time:", dt_time(9, 0))
                    ms = st.selectbox("Status:", ["present", "absent", "late", "leave"])
                    if st.form_submit_button("Force Sync Record", type="primary") and m_sel:
                        m_sid = profile_mapping[m_sel]
                        db.reference(f'/attendance/{md.strftime("%Y-%m-%d")}').push().set({
                            'student_id': m_sid, 'name': students_data[m_sid].get('name'), 
                            'status': ms, 'timestamp': int(datetime.combine(md, mt).timestamp()), 
                            'verification_method': "Manual_Admin"
                        })
                        st.success("Record created!"); time.sleep(1); st.rerun()

        with cm:
            with st.container(border=True):
                st.markdown("### 📝 Modify / Delete Records")
                if not df_all.empty:
                    sa = st.checkbox("🕰️ View All History")
                    f1, f2 = st.columns(2)
                    fd = f1.date_input("Filter Date:", datetime.now(), disabled=sa)
                    fs = f2.selectbox("Filter Student:", ["-- All Students --"] + sorted(profile_mapping.keys()))
                    f_df = df_all.copy() if sa else df_all[df_all['record_date'] == fd.strftime("%Y-%m-%d")]
                    if fs != "-- All Students --": f_df = f_df[f_df['student_id'] == profile_mapping[fs]]
                    
                    if not f_df.empty:
                        lbls = f_df['formatted_time'] + " | " + f_df['name'] + " (" + f_df['status'] + ")"
                        to_m = st.selectbox("Select Entry:", lbls.tolist())
                        row = f_df[lbls == to_m].iloc[0]
                        if st.button("🗑️ Delete This Record", use_container_width=True):
                            db.reference(f'/attendance/{row["firebase_path"]}').delete()
                            st.error("Record deleted."); time.sleep(1); st.rerun()
                    else: st.info("No records found.")

    with tab_m3:
        st.header("📊 Advanced Analytics Dashboard")
        if not df_all.empty:
            color_map = {'present': '#2ecc71', 'absent': '#e74c3c', 'late': '#f39c12', 'leave': '#3498db'}
            sub1, sub2, sub3 = st.tabs(["📑 Overview", "📈 Trends", "📥 Export"])
            
            with sub1:
                kcol1, kcol2 = st.columns(2)
                kcol1.metric("Active Students Tracked", df_all['student_id'].nunique())
                kcol2.metric("Days Tracked", df_all['record_date'].nunique())
                s_c = df_all['status'].value_counts().reset_index()
                s_c.columns = ['Status', 'Count']
                fig_pie = px.pie(s_c, values="Count", names="Status", hole=0.45, color="Status", color_discrete_map=color_map)
                st.plotly_chart(fig_pie, use_container_width=True)

            with sub2:
                unique_daily = df_all.drop_duplicates(subset=['record_date', 'student_id', 'status'])
                daily_trend = unique_daily.groupby(['record_date', 'status']).size().reset_index(name='Count')
                chart_data = daily_trend.pivot(index='record_date', columns='status', values='Count').fillna(0)
                st.bar_chart(chart_data)

            with sub3:
                st.markdown("#### 📥 Data Export Center")
                ex_filter = st.radio("Range:", ["All Time", "Specific Date"], horizontal=True)
                if ex_filter == "Specific Date":
                    ex_d = st.date_input("Select Date:", datetime.now())
                    ex_df = df_all[df_all['record_date'] == ex_d.strftime("%Y-%m-%d")]
                else: ex_df = df_all.copy()
                
                if not ex_df.empty:
                    st.dataframe(ex_df[['formatted_time', 'name', 'student_id', 'status', 'flow_type']].sort_values('formatted_time', ascending=False), use_container_width=True, hide_index=True)
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='xlsxwriter') as wr:
                        ex_df[['formatted_time', 'name', 'student_id', 'status', 'flow_type', 'verification_method']].to_excel(wr, index=False)
                    st.download_button("📂 Download Excel Report", data=buf.getvalue(), file_name=f"Report_{ex_filter}.xlsx", type="primary", use_container_width=True)
                else: st.info("No data to export.")
        else: st.warning("No analytics available yet.")

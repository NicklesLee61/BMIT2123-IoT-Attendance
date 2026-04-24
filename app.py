import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import plotly.express as px
from datetime import datetime, time as dt_time
import time
import io

# ==========================================================
# 🚀 GLOBAL FACULTY LIST
# ==========================================================
FACULTIES = [
    "FAFB (Faculty of Accountancy, Finance and Business)",
    "FOAS (Faculty of Applied Sciences)",
    "FOBE (Faculty of Built Environment)",
    "FCCI (Faculty of Communication and Creative Industries)",
    "FOCS (Faculty of Computing and Information Technology)",
    "FOET (Faculty of Engineering and Technology)",
    "FSSH (Faculty of Social Science and Humanities)",
    "Unknown / Other"
]

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# 🧠 SMART CLEANSING ENGINE
def clean_course_name(c):
    c_upper = str(c).upper()
    if 'FAFB' in c_upper: return 'FAFB'
    if 'FOAS' in c_upper: return 'FOAS'
    if 'FOBE' in c_upper: return 'FOBE'
    if 'FCCI' in c_upper or 'MUSIC' in c_upper: return 'FCCI'
    if 'FOCS' in c_upper or 'COMPUTER' in c_upper: return 'FOCS'
    if 'FOET' in c_upper: return 'FOET'
    if 'FSSH' in c_upper: return 'FSSH'
    return 'UNKNOWN / OTHER'

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
                "course": card_info.get('course', 'Unknown / Other'),
                "student_id": sid,
                "schedule": card_info.get('schedule', ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
            }

profile_mapping = {}
for sid, info in students_data.items():
    display_name = f"{info.get('name', 'Unknown')} ({sid})"
    profile_mapping[display_name] = sid

all_records = []
active_dates = set()

if attendance_raw:
    for date_key, daily_data in attendance_raw.items():
        active_dates.add(date_key)
        if isinstance(daily_data, dict):
            for rec_id, info in daily_data.items():
                info['firebase_path'] = f"{date_key}/{rec_id}"
                info['record_date'] = date_key
                all_records.append(info)

# 🚀 NEW: SMART AUTO-ABSENCE INJECTION ENGINE
# Automatically detects if a student missed their custom scheduled class day!
if students_data and active_dates:
    scanned_lookup = {}
    for r in all_records:
        dk = r['record_date']
        sid = r.get('student_id')
        if dk not in scanned_lookup: scanned_lookup[dk] = set()
        if sid: scanned_lookup[dk].add(sid)
        
    for d_str in active_dates:
        try:
            d_day = datetime.strptime(d_str, "%Y-%m-%d").strftime("%A")
            scanned_sids = scanned_lookup.get(d_str, set())
            
            for sid, info in students_data.items():
                # Get student's custom schedule (default Mon-Fri)
                stu_schedule = info.get('schedule', ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
                
                # If today is their class day AND they didn't scan any card today -> Mark Absent
                if d_day in stu_schedule and sid not in scanned_sids:
                    all_records.append({
                        'student_id': sid,
                        'name': info.get('name', 'Unknown'),
                        'course': info.get('course', 'Unknown / Other'),
                        'record_date': d_str,
                        'timestamp': int(datetime.strptime(f"{d_str} 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()),
                        'status': 'absent (Auto)',
                        'verification_method': 'System Auto-Generated',
                        'firebase_path': f"auto_generated/{d_str}/{sid}"
                    })
        except Exception:
            pass

df_all = pd.DataFrame(all_records)

if not df_all.empty:
    if 'verification_method' not in df_all.columns:
        df_all['verification_method'] = 'RFID + FP 2FA'
        
    df_all['timestamp'] = pd.to_numeric(df_all.get('timestamp'), errors='coerce')
    df_all['dt_obj'] = pd.to_datetime(df_all['timestamp'], unit='s', errors='coerce')
    df_all['dt_obj'] = df_all['dt_obj'].fillna(pd.to_datetime(df_all['record_date'], errors='coerce'))
    
    df_all['formatted_time'] = df_all['dt_obj'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df_all = df_all.sort_values('dt_obj')
    
    df_all['status'] = df_all['status'].apply(lambda x: 'present' if 'check' in str(x).lower() else str(x))
    df_all['tap_rank'] = df_all.groupby(['student_id', 'record_date']).cumcount() + 1
    
    def determine_flow(row):
        stat = str(row.get('status', '')).lower()
        if 'absent' in stat: return "--"
        if stat == 'leave': return "Check-out (Early)"
        return "Check-in" if row['tap_rank'] % 2 != 0 else "Check-out"
            
    df_all['flow_type'] = df_all.apply(determine_flow, axis=1)
    
    course_map = {k: clean_course_name(v.get('course', '')) for k, v in students_data.items()}
    df_all['course'] = df_all['student_id'].map(course_map).fillna('UNKNOWN / OTHER')

# ==========================================================
# 🚀 GLOBAL UI HELPER: Emoji Formatters
# ==========================================================
def display_status_emoji(s):
    s_lower = str(s).lower()
    if 'present' in s_lower: return f"🟢 {s.title()}"
    elif 'absent' in s_lower: return f"🔴 {s.title()}"
    elif 'late' in s_lower: return f"🟠 {s.title()}"
    elif 'leave' in s_lower: return f"🔵 {s.title()}"
    return s.title()
    
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
st.sidebar.markdown("---")

next_mode = "Enrollment" if current_hw_mode == "Attendance" else "Attendance"
if st.sidebar.button(f"🔄 Switch to {next_mode} Mode", type="primary", use_container_width=True):
    control_ref.update({"mode": next_mode})
    st.rerun()

# ==========================================================
# 4. DYNAMIC INTERFACE: MODE-AWARE DASHBOARD
# ==========================================================
st.title(f"🛡️ Smart Campus Portal: {current_hw_mode}")

if current_hw_mode == "Enrollment":
    st.subheader("Student Enrollment & Management Hub")
    
    pending_reg = db.reference('/pending_registration').get()
    scanned_rfid = str(pending_reg.get('rfid', '')) if pending_reg else ""
    scanned_fpid = str(pending_reg.get('fp_id', '')) if pending_reg else ""

    tab_reg, tab_update, tab_list = st.tabs(["➕ New Registration", "🔄 Update Student Details", "🗃️ Master Registry"])
    
    # ---------------------------------------------------------
    # TAB 1: PURE NEW REGISTRATION
    # ---------------------------------------------------------
    with tab_reg:
        st.markdown("### 📝 Register New Student")
        
        col_btn1, col_btn2 = st.columns([1, 4])
        with col_btn1:
            if st.button("🔄 Fetch Scanned Card", key="fetch_new", type="primary"):
                st.rerun()
                
        hw_sync_active = False
        if pending_reg and pending_reg.get('status') != 'ready_to_enroll':
            hw_sync_active = True
            st.success(f"✅ Hardware scan captured! Ready to register.")
            r_status = "🟢 Fetched from Scanner"
            f_status = "🟢 Fetched from Scanner"
            if st.button("🗑️ Clear Scan Data", key="clear_new"):
                db.reference('/pending_registration').delete(); st.rerun()
        else:
            st.info("💡 Scan a card on the hardware, then click 'Fetch Scanned Card' above.")
            r_status = "⚪ Waiting for Scan"
            f_status = "⚪ Waiting for Scan"

        with st.form("enroll_form_new"):
            c1, c2 = st.columns(2)
            with c1:
                n_id = st.text_input("Student ID (Required):").strip()
                n_name = st.text_input("Full Name:").strip()
                n_course = st.selectbox("Academic Faculty / Program:", FACULTIES)
                # 🚀 ADDED MULTI-SELECT FOR SCHEDULING
                n_schedule = st.multiselect("📅 Mandatory Class Days:", DAYS_OF_WEEK, default=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
            with c2:
                n_rfid = st.text_input(f"RFID UID ({r_status}):", value=scanned_rfid).strip()
                n_fpid = st.text_input(f"Fingerprint Token ({f_status}):", value=scanned_fpid).strip()
                n_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            if st.form_submit_button("Finalize New Registration"):
                if not n_id or not n_name:
                    st.error("⚠️ Student ID and Name are required for new registration.")
                elif n_id in students_data:
                    st.error(f"❌ **ID Conflict:** Student ID `{n_id}` already exists. Use the 'Update Student Details' tab instead.")
                elif not n_schedule:
                    st.error("⚠️ Please select at least one Mandatory Class Day.")
                else:
                    rfid_owners = {str(v.get('card_id')).strip(): v.get('student_id') for v in cards_raw.values() if str(v.get('card_id')).strip() not in ['Unlinked', '', 'None']}
                    fpid_owners = {str(v.get('fingerprint_id')).strip(): v.get('student_id') for v in cards_raw.values() if str(v.get('fingerprint_id')).strip() not in ['Unlinked', '', 'None']}
                    has_conflict = False
                    
                    if n_rfid and n_rfid in rfid_owners:
                        st.error(f"❌ **Hardware Conflict:** RFID UID `{n_rfid}` is already in use by {rfid_owners[n_rfid]}."); has_conflict = True
                    if n_fpid and n_fpid in fpid_owners:
                        st.error(f"❌ **Hardware Conflict:** Fingerprint Token `{n_fpid}` is already in use by {fpid_owners[n_fpid]}."); has_conflict = True

                    if not has_conflict:
                        db.reference(f'/students/{n_id}').update({
                            "student_id": n_id, "name": n_name, "course": n_course, "registered_date": n_date,
                            "rfid": n_rfid if n_rfid else "Unlinked",
                            "schedule": n_schedule
                        })
                        
                        if hw_sync_active:
                            db.reference('/pending_registration').update({
                                "status": "ready_to_enroll",
                                "name": n_name,
                                "student_id": n_id,
                                "course": n_course,
                                "rfid": n_rfid,
                                "fp_id": n_fpid
                            })
                            st.success("✅ Details sent to Hardware! Waiting for Raspberry Pi to finalize...")
                        else:
                            db.reference('/cards').push().set({
                                "student_id": n_id, "name": n_name, "course": n_course, "registered_date": n_date,
                                "card_id": n_rfid if n_rfid else "Unlinked",
                                "fingerprint_id": n_fpid if n_fpid else "Unlinked",
                                "schedule": n_schedule
                            })
                            st.success(f"Profile {n_name} ({n_id}) successfully created!")
                            
                        time.sleep(1); st.rerun()

    # ---------------------------------------------------------
    # TAB 2: UPDATE / RE-BIND 
    # ---------------------------------------------------------
    with tab_update:
        st.markdown("### 🔄 Update Student Details / Re-bind Card")
        
        ucol_btn1, ucol_btn2 = st.columns([1, 4])
        with ucol_btn1:
            if st.button("🔄 Fetch Scanned Card", key="fetch_update", type="primary"):
                st.rerun()

        if profile_mapping:
            u_search = st.text_input("🔍 Search Student to Update (by ID or Name):", placeholder="e.g. 24WMR...")
            u_opts = sorted([p for p in profile_mapping.keys() if u_search.lower() in p.lower()]) if u_search else sorted(profile_mapping.keys())
            
            if u_opts:
                u_disp = st.selectbox("Select Student Profile:", u_opts)
                u_sid = profile_mapping[u_disp]
                
                exist_stu = students_data.get(u_sid, {})
                exist_card_key = next((k for k, v in cards_raw.items() if v.get('student_id') == u_sid), None)
                exist_card = cards_raw.get(exist_card_key, {}) if exist_card_key else {}
                
                if pending_reg:
                    display_rfid = scanned_rfid
                    display_fpid = scanned_fpid
                    ur_status = "🟢 New Scan Ready to Bind"
                    uf_status = "🟢 New Scan Ready to Bind"
                    st.success(f"✅ New hardware scan detected! Auto-filled below ready for re-binding.")
                    if st.button("🗑️ Clear Scan Data", key="clear_update"):
                        db.reference('/pending_registration').delete(); st.rerun()
                else:
                    display_rfid = exist_card.get('card_id', '')
                    display_fpid = exist_card.get('fingerprint_id', '')
                    ur_status = "🔵 Current Bound ID"
                    uf_status = "🔵 Current Bound Slot"

                with st.form("update_form"):
                    st.info("💡 Edit the details below. Unmodified fields will retain their existing data.")
                    c1, c2 = st.columns(2)
                    with c1:
                        u_name = st.text_input("Full Name:", value=exist_stu.get('name', '')).strip()
                        
                        exist_course = exist_stu.get('course', 'Unknown / Other')
                        c_index = FACULTIES.index(exist_course) if exist_course in FACULTIES else len(FACULTIES)-1
                        u_course = st.selectbox("Academic Faculty / Program:", FACULTIES, index=c_index)
                        
                        # 🚀 ADDED MULTI-SELECT FOR SCHEDULING UPDATE
                        exist_schedule = exist_stu.get('schedule', ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
                        u_schedule = st.multiselect("📅 Mandatory Class Days:", DAYS_OF_WEEK, default=exist_schedule)

                    with c2:
                        u_rfid = st.text_input(f"RFID UID ({ur_status}):", value=display_rfid).strip()
                        u_fpid = st.text_input(f"Fingerprint Token ({uf_status}):", value=display_fpid).strip()

                    if st.form_submit_button("Save Updates / Apply Re-bind"):
                        rfid_owners = {str(v.get('card_id')).strip(): v.get('student_id') for v in cards_raw.values() if str(v.get('card_id')).strip() not in ['Unlinked', '', 'None']}
                        fpid_owners = {str(v.get('fingerprint_id')).strip(): v.get('student_id') for v in cards_raw.values() if str(v.get('fingerprint_id')).strip() not in ['Unlinked', '', 'None']}
                        has_conflict = False
                        
                        if not u_schedule:
                            st.error("⚠️ Please select at least one Mandatory Class Day."); has_conflict = True
                        if u_rfid and u_rfid in rfid_owners and rfid_owners[u_rfid] != u_sid:
                            st.error(f"❌ **Hardware Conflict:** RFID UID `{u_rfid}` belongs to {rfid_owners[u_rfid]}."); has_conflict = True
                        if u_fpid and u_fpid in fpid_owners and fpid_owners[u_fpid] != u_sid:
                            st.error(f"❌ **Hardware Conflict:** Fingerprint Token `{u_fpid}` belongs to {fpid_owners[u_fpid]}."); has_conflict = True

                        if not has_conflict:
                            db.reference(f'/students/{u_sid}').update({
                                "name": u_name, "course": u_course, "rfid": u_rfid if u_rfid else "Unlinked",
                                "schedule": u_schedule
                            })
                            
                            card_payload = {
                                "student_id": u_sid, "name": u_name, "course": u_course,
                                "card_id": u_rfid if u_rfid else "Unlinked", 
                                "fingerprint_id": u_fpid if u_fpid else "Unlinked", 
                                "schedule": u_schedule,
                                "registered_date": exist_stu.get('registered_date', datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
                            }
                            
                            if exist_card_key: db.reference(f'/cards/{exist_card_key}').update(card_payload)
                            else: db.reference('/cards').push().set(card_payload)
                            
                            if pending_reg: db.reference('/pending_registration').delete()
                            st.success(f"Profile {u_sid} successfully updated!"); time.sleep(1); st.rerun()
            else:
                st.info("No matching students found.")
        else:
            st.info("Registry is empty. Register a student in the New Registration tab first.")

    # ---------------------------------------------------------
    # TAB 3: MASTER REGISTRY
    # ---------------------------------------------------------
    with tab_list:
        if students_data:
            master_registry = []
            for sid, info in students_data.items():
                card_info = next((v for v in cards_raw.values() if v.get('student_id') == sid), {})
                short_course = clean_course_name(info.get('course', 'N/A'))
                
                # Format schedule for display
                stu_sched = info.get('schedule', ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
                short_sched = ", ".join([d[:3] for d in stu_sched]) if stu_sched else "None"
                
                master_registry.append({
                    "student_id": sid, 
                    "name": info.get('name', 'N/A'), 
                    "course": short_course, 
                    "class_days": short_sched,
                    "RFID_UID": card_info.get('card_id', 'Unlinked'), 
                    "FP_ID": card_info.get('fingerprint_id', 'N/A')
                })
                
            reg_df = pd.DataFrame(master_registry).sort_values("student_id")
            search_query = st.text_input("🔍 Search Student (by ID, Name, or Course):", placeholder="e.g. 2413458, Sakiko...")
            if search_query:
                reg_df = reg_df[reg_df[['student_id', 'name', 'course']].apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)]
            reg_df = reg_df.reset_index(drop=True); reg_df.index += 1
            
            reg_disp = reg_df.rename(columns={
                'student_id': 'Student ID',
                'name': 'Full Name',
                'course': 'Faculty',
                'class_days': 'Class Days',
                'RFID_UID': 'RFID Tag',
                'FP_ID': 'FP Slot'
            })
            st.dataframe(reg_disp, use_container_width=True)
            
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
            # 🚀 ADDED FACULTY FILTER HERE
            c1, c2, c3 = st.columns([1, 1.5, 1.5])
            with c1: sel_date = st.date_input("📅 Date:", datetime.now(), key="l_date")
            with c2: fac_filter = st.selectbox("🎓 Filter by Faculty:", ["-- All Faculties --"] + FACULTIES, key="l_fac")
            with c3: search_l = st.text_input("🔍 Search Record (by ID/Name):", key="l_search")
            
            view_df = df_all[df_all['record_date'] == sel_date.strftime("%Y-%m-%d")]
            
            # 🚀 BUG FIX: USE clean_course_name TO MATCH DATABASE SHORT CODES
            if fac_filter != "-- All Faculties --":
                view_df = view_df[view_df['course'] == clean_course_name(fac_filter)]

            if not view_df.empty:
                latest = view_df.drop_duplicates(subset=['student_id'], keep='last')
                k1, k2, k3, k4 = st.columns(4)
                
                present_count = len(latest[latest['status'].isin(['present', 'checked_in'])])
                k1.metric("🟢 Present / In", present_count)
                k2.metric("🔴 Absent", len(latest[latest['status'].astype(str).str.contains('absent', case=False)]))
                k3.metric("🟠 Late", len(latest[latest['status'] == 'late']))
                k4.metric("🔵 Leave / Out", len(latest[latest['status'].isin(['leave', 'checked_out'])]))
                
                st.write("---")
                
                # Added 'course' to the display so the teacher can see the faculty column!
                disp = view_df[['formatted_time', 'name', 'student_id', 'course', 'flow_type', 'status', 'verification_method']].sort_values('formatted_time', ascending=False).copy()
                
                if search_l: disp = disp[disp[['student_id', 'name']].apply(lambda row: row.astype(str).str.contains(search_l, case=False).any(), axis=1)]
                
                if not disp.empty:
                    disp['status'] = disp['status'].apply(display_status_emoji); disp['flow_type'] = disp['flow_type'].apply(display_flow_emoji)
                    disp = disp.reset_index(drop=True); disp.index += 1
                    
                    disp = disp.rename(columns={
                        'formatted_time': 'Timestamp',
                        'name': 'Student Name',
                        'student_id': 'Student ID',
                        'course': 'Faculty',
                        'flow_type': 'Log Type',
                        'status': 'Status',
                        'verification_method': 'Verification'
                    })
                    st.dataframe(disp, use_container_width=True)
                else: st.warning(f"No matching records found for '{search_l}'.")
            else: 
                if fac_filter != "-- All Faculties --":
                    st.info(f"No records found for {fac_filter} on {sel_date.strftime('%Y-%m-%d')}.")
                else:
                    st.info(f"No records for {sel_date.strftime('%Y-%m-%d')}.")
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
                            ms = st.selectbox("Status:", ["present", "absent", "late", "leave"], format_func=display_status_emoji)
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
                            ns = st.selectbox("Change status to:", ["present", "absent", "late", "leave"], format_func=display_status_emoji)
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
    # 📊 tab_m3: REDESIGNED MULTI-PAGE ANALYTICS 
    # ==========================================================
    with tab_m3:
        st.header("📊 Advanced Analytics Dashboard")
        st.write("Real-time behavioral insights and comprehensive student performance tracking.")
        
        if not df_all.empty:
            color_map = {
                'Present': '#2ecc71',
                'Absent': '#e74c3c',
                'Absent (Auto)': '#e74c3c',
                'Late': '#f39c12',
                'Leave': '#3498db'
            }

            sub_tab1, sub_tab2, sub_tab3 = st.tabs(["📑 Executive Summary", "📈 Behavioral Analytics", "📥 Report Generation"])
            
            with sub_tab1:
                st.markdown("##### 📌 High-Level KPIs")
                a_col1, a_col2 = st.columns(2)
                a_col1.metric("Active Students Tracked", df_all['student_id'].nunique())
                a_col2.metric("Days Tracked", df_all['record_date'].nunique())
                st.write("---")
                
                with st.container(border=True):
                    st.subheader("🍩 Status Composition")
                    st.caption("Overall class participation distribution")
                    
                    s_c = df_all['status'].value_counts().reset_index()
                    s_c.columns = ['Status', 'Count']
                    s_c['Status'] = s_c['Status'].astype(str).str.title()
                    s_c = s_c.groupby('Status', as_index=False).sum() 
                    
                    fig_pie = px.pie(s_c, values="Count", names="Status", hole=0.45, color="Status", color_discrete_map=color_map)
                    fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                    fig_pie.update_layout(showlegend=True, margin=dict(l=0, r=0, t=20, b=0), paper_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig_pie, use_container_width=True)

            with sub_tab2:
                with st.container(border=True):
                    st.subheader("🏛️ Daily Faculty Attendance Rates")
                    
                    fac_date = st.date_input("Select Date for Faculty Analytics:", datetime.now(), key="fac_date_picker")
                    selected_date_str = fac_date.strftime("%Y-%m-%d")
                    selected_date_day = fac_date.strftime("%A")
                    st.caption(f"Attendance rate based on total enrolled students per faculty for {selected_date_str}")
                    
                    stu_list = []
                    for sid_reg, info_reg in students_data.items():
                        # Only count students whose schedule includes this day for accurate rate calculation!
                        stu_sched = info_reg.get('schedule', ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
                        if selected_date_day in stu_sched:
                            clean_c = clean_course_name(info_reg.get('course', ''))
                            stu_list.append({'student_id': sid_reg, 'Clean_Faculty': clean_c})
                    
                    df_stu = pd.DataFrame(stu_list)
                    
                    if not df_stu.empty:
                        fac_totals = df_stu.groupby('Clean_Faculty').size().reset_index(name='Total_Enrolled')
                        
                        day_records = df_all[df_all['record_date'] == selected_date_str]
                        
                        if not day_records.empty:
                            day_records = day_records.copy()
                            day_records['Clean_Faculty'] = day_records['course'].apply(lambda x: str(x).split('(')[0].split(':')[0].strip().upper())
                            day_unique = day_records.drop_duplicates(subset=['student_id'], keep='last')
                            
                            day_present = day_unique[day_unique['status'].astype(str).str.lower().isin(['present', 'late', 'checked_in'])]
                            fac_present = day_present.groupby('Clean_Faculty').size().reset_index(name='Attended')
                        else:
                            fac_present = pd.DataFrame(columns=['Clean_Faculty', 'Attended'])
                        
                        fac_rate = pd.merge(fac_totals, fac_present, on='Clean_Faculty', how='left').fillna(0)
                        fac_rate['Rate (%)'] = fac_rate.apply(lambda row: round((row['Attended'] / row['Total_Enrolled']) * 100, 1) if row['Total_Enrolled'] > 0 else 0, axis=1)
                        
                        fig_fac = px.bar(fac_rate, x='Clean_Faculty', y='Rate (%)', text='Rate (%)', 
                                         color='Clean_Faculty', 
                                         hover_data={'Total_Enrolled': True, 'Attended': True, 'Clean_Faculty': False},
                                         labels={'Clean_Faculty': 'Faculty', 'Rate (%)': 'Attendance Rate (%)', 'Total_Enrolled': 'Registered Students', 'Attended': 'Attended Today'})
                        fig_fac.update_traces(textposition='outside')
                        fig_fac.update_layout(showlegend=False, xaxis_title="", yaxis_range=[0, 110], margin=dict(t=30, b=0))
                        st.plotly_chart(fig_fac, use_container_width=True)
                    else:
                        st.info(f"No students have classes scheduled on {selected_date_day}s.")

                st.write("<br>", unsafe_allow_html=True)

                with st.container(border=True):
                    st.subheader("📈 Daily Attendance Trend")
                    st.caption("Tracking daily attendance variations over time")
                    unique_daily = df_all.drop_duplicates(subset=['record_date', 'student_id', 'status'])
                    if not unique_daily.empty:
                        daily_trend = unique_daily.groupby(['record_date', 'status']).size().reset_index(name='Count')
                        chart_data = daily_trend.pivot(index='record_date', columns='status', values='Count').fillna(0)
                        st.bar_chart(chart_data, use_container_width=True)
                st.write("<br>", unsafe_allow_html=True)
                
                with st.container(border=True):
                    st.subheader("⏱️ Stay Duration Analysis")
                    
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        dur_date = st.date_input("Select Date for Duration:", datetime.now(), key="dur_date_picker")
                    with dc2:
                        dur_stu = st.selectbox("Filter by Specific Student:", ["-- All Students --"] + sorted(profile_mapping.keys()), key="dur_stu_picker")
                        
                    dur_date_str = dur_date.strftime("%Y-%m-%d")
                    st.caption(f"Active hours spent in session (Check-in to Check-out) for {dur_date_str}")
                    
                    dur_data = []
                    valid_df = df_all[~df_all['status'].astype(str).str.contains('absent', case=False, na=False)]
                    
                    target_sids = students_data.keys() if dur_stu == "-- All Students --" else [profile_mapping[dur_stu]]
                    
                    for sid in target_sids:
                        p_t = valid_df[(valid_df['student_id'] == sid) & (valid_df['record_date'] == dur_date_str)].sort_values('dt_obj')
                        if len(p_t) >= 2: 
                            hrs = round((p_t.iloc[-1]['dt_obj'] - p_t.iloc[0]['dt_obj']).total_seconds() / 3600, 2)
                            dur_data.append({"ID": sid, "Hrs": hrs}) 
                            
                    if dur_data: 
                        dur_df = pd.DataFrame(dur_data)
                        st.bar_chart(dur_df.set_index('ID'), use_container_width=True)
                    else: 
                        st.info(f"💡 Insufficient data for {dur_date_str} (Requires both Check-in and Check-out logs).")

            with sub_tab3:
                with st.container(border=True):
                    st.subheader("📥 Data Export Center")
                    st.write("Filter, review the raw dataset, and generate the official Excel report.")
                    
                    export_filter = st.radio("Select Export Range:", ["All Time (Full History)", "Specific Date"], horizontal=True)
                    
                    ex_c1, ex_c2 = st.columns(2)
                    
                    if export_filter == "Specific Date":
                        with ex_c1: export_date = st.date_input("Select Date to Export:", datetime.now(), key="export_date_input")
                        export_df = df_all[df_all['record_date'] == export_date.strftime("%Y-%m-%d")]
                        with ex_c2: export_fac = st.selectbox("Filter by Faculty (Export):", ["-- All Faculties --"] + FACULTIES, key="ex_fac")
                    else:
                        export_df = df_all.copy()
                        with ex_c1: export_fac = st.selectbox("Filter by Faculty (Export):", ["-- All Faculties --"] + FACULTIES, key="ex_fac")
                    
                    if export_fac != "-- All Faculties --":
                        export_df = export_df[export_df['course'] == clean_course_name(export_fac)]
                        
                    st.write("---")
                    
                    if not export_df.empty:
                        cols_to_show = ['formatted_time', 'name', 'student_id', 'course', 'status', 'flow_type', 'verification_method']
                        existing_cols = [c for c in cols_to_show if c in export_df.columns]
                        export_disp = export_df[existing_cols].sort_values('formatted_time', ascending=False)
                        
                        export_disp = export_disp.rename(columns={
                            'formatted_time': 'Timestamp',
                            'name': 'Student Name',
                            'student_id': 'Student ID',
                            'course': 'Faculty',
                            'status': 'Status',
                            'flow_type': 'Log Type',
                            'verification_method': 'Verification'
                        })
                        
                        st.dataframe(export_disp, height=300, use_container_width=True)
                        st.write("<br>", unsafe_allow_html=True)
                        
                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf, engine='xlsxwriter') as wr:
                            export_disp.to_excel(wr, index=False)
                        
                        file_suffix = "All_Time" if export_filter == "All Time (Full History)" else export_date.strftime("%Y%m%d")
                        file_name = f"Smart_Campus_Report_{file_suffix}.xlsx"
                        
                        st.download_button("📂 Download Official Attendance Report (.xlsx)", data=buf.getvalue(), file_name=file_name, use_container_width=True, type="primary")
                    else:
                        st.info("⚠️ No records found for the selected filter.")
                        
        else: 
            st.warning("⚠️ No analytics available yet. Synchronize hardware logs first.")

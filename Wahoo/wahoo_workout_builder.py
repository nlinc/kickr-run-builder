import streamlit as st
import requests
import json
import base64
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
import extra_streamlit_components as stx

# ==========================================
# 1. CONFIGURATION
# ==========================================
st.set_page_config(page_title="Wahoo KICKR RUN Builder", page_icon="🏃", layout="centered")

# Load Secrets
try:
    CLIENT_ID = st.secrets["WAHOO_CLIENT_ID"]
    CLIENT_SECRET = st.secrets["WAHOO_CLIENT_SECRET"]
    REDIRECT_URI = st.secrets["WAHOO_REDIRECT_URI"]
except (FileNotFoundError, KeyError):
    st.error("❌ Missing Secrets! Please create a `.streamlit/secrets.toml` file.")
    st.stop()

SCOPES = "power_zones_read power_zones_write workouts_read workouts_write plans_read plans_write user_read"

# ==========================================
# 2. AUTHENTICATION
# ==========================================

cookie_manager = stx.CookieManager()

def get_auth_url():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "response_type": "code"
    }
    return f"https://api.wahooligan.com/oauth/authorize?{urllib.parse.urlencode(params)}"

def refresh_access_token(refresh_token):
    url = "https://api.wahooligan.com/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "redirect_uri": REDIRECT_URI
    }
    try:
        res = requests.post(url, data=payload)
        if res.status_code == 200:
            tokens = res.json()
            cookie_manager.set('wahoo_refresh_token', tokens['refresh_token'], key="set_ref")
            return tokens['access_token']
        else:
            return None
    except:
        return None

def exchange_code_for_token(code):
    url = "https://api.wahooligan.com/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI
    }
    try:
        res = requests.post(url, data=payload)
        if res.status_code == 200:
            tokens = res.json()
            st.session_state['access_token'] = tokens['access_token']
            cookie_manager.set('wahoo_refresh_token', tokens['refresh_token'], key="set_init")
            return tokens['access_token']
        else:
            st.error(f"Auth Failed: {res.text}")
            return None
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

# ==========================================
# 3. API LOGIC
# ==========================================

def upload_plan_to_wahoo(token, plan_json, plan_name):
    json_str = json.dumps(plan_json)
    b64_file = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
    
    payload = {
        "plan[file]": f"data:application/json;base64,{b64_file}",
        "plan[filename]": "kickr_run.json",
        "plan[external_id]": f"RUN_{int(time.time())}", 
        "plan[provider_updated_at]": datetime.now(timezone.utc).isoformat()
    }
    
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.post("https://api.wahooligan.com/v1/plans", headers=headers, data=payload)
    
    if res.status_code in [200, 201]:
        return res.json()['id']
    else:
        st.error(f"Plan Upload Error: {res.text}")
        return None

def schedule_workout(token, plan_id, plan_name, duration_sec):
    headers = {"Authorization": f"Bearer {token}"}
    start_time = datetime.now(timezone.utc).isoformat()
    minutes_int = int(duration_sec / 60)
    
    payload = {
        "workout": {
            "name": plan_name,
            "starts": start_time,
            "plan_id": plan_id,
            "workout_type_id": 1,
            "workout_token": str(uuid.uuid4()),
            "minutes": minutes_int
        }
    }
    
    res = requests.post("https://api.wahooligan.com/v1/workouts", headers=headers, json=payload)
    if res.status_code in [200, 201]:
        return res.json()['id']
    else:
        st.error(f"Schedule Error: {res.text}")
        return None

# ==========================================
# 4. HELPER FUNCTIONS
# ==========================================

def move_interval(index, direction):
    if direction == -1 and index > 0:
        st.session_state.intervals[index], st.session_state.intervals[index-1] = st.session_state.intervals[index-1], st.session_state.intervals[index]
    elif direction == 1 and index < len(st.session_state.intervals) - 1:
        st.session_state.intervals[index], st.session_state.intervals[index+1] = st.session_state.intervals[index+1], st.session_state.intervals[index]

def get_target_pct(mode, zone_key, slider_val, zone_map):
    if mode == "Select Zone":
        low, high = zone_map[zone_key]
        return (low + high) / 2, low, high, zone_key
    else:
        pct = slider_val / 100.0
        return pct, pct - 0.02, pct + 0.02, f"{slider_val}%"

def determine_type(pct, name):
    if pct < 0.69:
        return "wu" if "Warm" in name else "recover"
    elif pct > 1.05:
        return "active"
    else:
        return "active"

# ==========================================
# 5. AUTH FLOW
# ==========================================

st.title("🏃 KICKR RUN Builder")

active_token = None
if 'access_token' in st.session_state:
    active_token = st.session_state['access_token']

if not active_token and 'code' in st.query_params:
    code = st.query_params['code']
    with st.spinner("Authenticating..."):
        token = exchange_code_for_token(code)
        if token:
            active_token = token
            time.sleep(1)
            st.query_params.clear()
            st.rerun()

if not active_token:
    time.sleep(0.1)
    stored_refresh = cookie_manager.get('wahoo_refresh_token')
    if stored_refresh:
        with st.spinner("Resuming..."):
            token = refresh_access_token(stored_refresh)
            if token:
                st.session_state['access_token'] = token
                active_token = token
                st.rerun()
            else:
                cookie_manager.delete('wahoo_refresh_token')

if not active_token:
    st.info("Please log in to Wahoo Cloud.")
    st.link_button("Login with Wahoo", get_auth_url())
    st.stop()
else:
    if st.sidebar.button("Logout"):
        cookie_manager.delete('wahoo_refresh_token')
        if 'access_token' in st.session_state:
            del st.session_state['access_token']
        st.rerun()

# ==========================================
# 6. UI LOGIC
# ==========================================

# --- SETTINGS ---
with st.expander("⚙️ Workout Settings", expanded=True):
    col1, col2 = st.columns([2, 1])
    with col1:
        workout_name = st.text_input("Workout Name", "Zone Run")
    with col2:
        st.write("Threshold Pace")
        t_col1, t_col2 = st.columns(2)
        with t_col1: p_min = st.number_input("Min", 4, 15, 8, label_visibility="collapsed")
        with t_col2: p_sec = st.number_input("Sec", 0, 59, 39, label_visibility="collapsed")
        threshold_pace_mps = 1609.34 / ((p_min * 60) + p_sec)

st.divider()

if 'intervals' not in st.session_state:
    st.session_state.intervals = []

ZONES = {
    "Zone 1 (Recovery)": (0.50, 0.69),
    "Zone 2 (Endurance)": (0.69, 0.83),
    "Zone 3 (Tempo)": (0.83, 0.91),
    "Zone 4 (Threshold)": (0.91, 1.05),
    "Zone 5 (VO2 Max)": (1.05, 1.18),
    "Zone 6 (Anaerobic)": (1.18, 1.33),
    "Zone 7 (Neuromus)": (1.33, 1.50)
}

# --- BUILDER TABS ---
tab1, tab2 = st.tabs(["Single Interval", "🔁 Repeat Set"])

# TAB 1: SINGLE ADD
with tab1:
    st.subheader("Add Single Step")
    r1a, r1b = st.columns([1.5, 1])
    with r1a: s_name = st.text_input("Label", value="Interval", key="s_name")
    with r1b:
        st.caption("Duration")
        d1, d2 = st.columns(2)
        with d1: s_min = st.number_input("Min", 0, 120, 5, key="s_min")
        with d2: s_sec = st.number_input("Sec", 0, 59, 0, key="s_sec")
    
    r2a, r2b = st.columns([1, 2])
    with r2a: s_mode = st.radio("Target", ["Select Zone", "Custom %"], key="s_mode")
    with r2b:
        if s_mode == "Select Zone":
            s_zone = st.selectbox("Zone", list(ZONES.keys()), key="s_zone")
            s_slider = 100
        else:
            s_zone = list(ZONES.keys())[0]
            s_slider = st.slider("Percent", 50, 150, 100, key="s_slider")

    if st.button("➕ Add Single Step", type="primary"):
        dur = (s_min * 60) + s_sec
        if dur > 0:
            tpct, tlow, thigh, tname = get_target_pct(s_mode, s_zone, s_slider, ZONES)
            st.session_state.intervals.append({
                "name": s_name, "duration": dur, "type_code": determine_type(tpct, s_name),
                "target_low": tlow, "target_high": thigh, "zone_name": tname, "mode": s_mode
            })
            st.rerun()

# TAB 2: LOOP / REPEAT
with tab2:
    st.subheader("🔁 Add Repeat Set")
    st.info("Example: Run Zone 4 (30s) + Recover Zone 1 (90s) -> Repeat 3x")
    
    # WORK Part
    st.markdown("#### 1. Work Interval")
    w_col1, w_col2 = st.columns([1.5, 1])
    with w_col1:
        w_mode = st.radio("Work Target", ["Select Zone", "Custom %"], horizontal=True, key="w_mode")
        if w_mode == "Select Zone":
            w_zone = st.selectbox("Zone", list(ZONES.keys()), index=3, key="w_zone") # Default Zone 4
            w_slider = 100
        else:
            w_zone = list(ZONES.keys())[0]
            w_slider = st.slider("%", 50, 150, 105, key="w_slider")
            
    with w_col2:
        st.caption("Duration")
        wd1, wd2 = st.columns(2)
        with wd1: w_min = st.number_input("Min", 0, 60, 0, key="w_min")
        with wd2: w_sec = st.number_input("Sec", 0, 59, 30, key="w_sec")

    st.divider()
    
    # REST Part
    st.markdown("#### 2. Rest Interval")
    r_col1, r_col2 = st.columns([1.5, 1])
    with r_col1:
        r_mode = st.radio("Rest Target", ["Select Zone", "Custom %"], horizontal=True, key="r_mode")
        if r_mode == "Select Zone":
            r_zone = st.selectbox("Zone", list(ZONES.keys()), index=0, key="r_zone") # Default Zone 1
            r_slider = 100
        else:
            r_zone = list(ZONES.keys())[0]
            r_slider = st.slider("%", 50, 150, 65, key="r_slider")
            
    with r_col2:
        st.caption("Duration")
        rd1, rd2 = st.columns(2)
        with rd1: r_min = st.number_input("Min", 0, 60, 1, key="r_min")
        with rd2: r_sec = st.number_input("Sec", 0, 59, 30, key="r_sec")

    st.divider()
    
    # LOOPS
    l_col1, l_col2 = st.columns([1, 2])
    with l_col1:
        loops = st.number_input("🔁 How many times?", 1, 20, 3)
    with l_col2:
        st.write("")
        st.write("")
        if st.button("➕ Add Repeat Set", type="primary", use_container_width=True):
            w_dur = (w_min * 60) + w_sec
            r_dur = (r_min * 60) + r_sec
            
            if w_dur == 0 and r_dur == 0:
                st.error("Duration required.")
            else:
                for i in range(loops):
                    # Add Work
                    if w_dur > 0:
                        wpct, wlow, whigh, wname = get_target_pct(w_mode, w_zone, w_slider, ZONES)
                        st.session_state.intervals.append({
                            "name": "Work", "duration": w_dur, "type_code": "active",
                            "target_low": wlow, "target_high": whigh, "zone_name": wname, "mode": w_mode
                        })
                    # Add Rest
                    if r_dur > 0:
                        rpct, rlow, rhigh, rname = get_target_pct(r_mode, r_zone, r_slider, ZONES)
                        st.session_state.intervals.append({
                            "name": "Rest", "duration": r_dur, "type_code": "recover",
                            "target_low": rlow, "target_high": rhigh, "zone_name": rname, "mode": r_mode
                        })
                st.success(f"Added {loops} sets!")
                time.sleep(0.5)
                st.rerun()

# --- PREVIEW LIST (MOBILE FRIENDLY CARDS) ---
if st.session_state.intervals:
    st.write("### Plan Preview")
    total_time = 0
    
    for idx, interval in enumerate(st.session_state.intervals):
        total_time += interval['duration']
        
        # CARD CONTAINER
        with st.container(border=True):
            # Layout: Text on Left, Delete/Move on Bottom Row
            
            # Format Data
            m = interval['duration'] // 60
            s = interval['duration'] % 60
            dur_str = f"{m}m {s}s" if s > 0 else f"{m}m"
            
            p_min = (1609.34 / (threshold_pace_mps * interval['target_high'])) / 60
            p_max = (1609.34 / (threshold_pace_mps * interval['target_low'])) / 60
            pace_str = f"{int(p_min)}:{int((p_min%1)*60):02d}-{int(p_max)}:{int((p_max%1)*60):02d}"
            
            # Row 1: Content
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**{idx+1}. {interval['name']}**")
                st.caption(f"⏱️ {dur_str}  |  🎯 {interval['zone_name']} ({pace_str}/mi)")
            
            # Row 2: Big Mobile Buttons
            b1, b2, b3 = st.columns(3)
            
            # Up
            if b1.button("⬆️ Up", key=f"u{idx}", disabled=(idx==0), use_container_width=True):
                move_interval(idx, -1)
                st.rerun()
            
            # Down
            if b2.button("⬇️ Dn", key=f"d{idx}", disabled=(idx==len(st.session_state.intervals)-1), use_container_width=True):
                move_interval(idx, 1)
                st.rerun()
                
            # Delete
            if b3.button("❌ Del", key=f"x{idx}", type="secondary", use_container_width=True):
                st.session_state.intervals.pop(idx)
                st.rerun()

    st.markdown(f"**Total Duration:** {int(total_time/60)} minutes")
    
    if st.button("🚀 Upload & Schedule", type="primary", use_container_width=True):
        with st.spinner("Uploading..."):
            plan_json = {
                "header": {
                    "name": workout_name, "version": "1.0.0", "description": "Streamlit Builder Plan",
                    "workout_type_family": 1, "workout_type_location": 0, "threshold_speed": threshold_pace_mps
                },
                "intervals": []
            }
            for i in st.session_state.intervals:
                plan_json["intervals"].append({
                    "name": i['name'], "exit_trigger_type": "time", "exit_trigger_value": i['duration'],
                    "intensity_type": i['type_code'], 
                    "targets": [{"type": "threshold_speed", "low": i['target_low'], "high": i['target_high']}]
                })
            
            pid = upload_plan_to_wahoo(active_token, plan_json, workout_name)
            if pid:
                wid = schedule_workout(active_token, pid, workout_name, total_time)
                if wid:
                    st.success("Scheduled! 🎉")
                    st.balloons()

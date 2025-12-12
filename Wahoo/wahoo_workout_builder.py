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
st.set_page_config(page_title="Wahoo KICKR RUN Builder", page_icon="🏃")

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
# 4. AUTH FLOW EXECUTION
# ==========================================

st.title("🏃 KICKR RUN Workout Builder")
st.divider()

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
        with st.spinner("Resuming session..."):
            token = refresh_access_token(stored_refresh)
            if token:
                st.session_state['access_token'] = token
                active_token = token
                st.rerun()
            else:
                cookie_manager.delete('wahoo_refresh_token')

# ==========================================
# 5. UI LOGIC
# ==========================================

if not active_token:
    st.info("Please log in to Wahoo Cloud to enable uploading.")
    st.link_button("Login with Wahoo", get_auth_url())
    st.stop()
else:
    st.success("✅ Connected to Wahoo Cloud")
    if st.button("Logout"):
        cookie_manager.delete('wahoo_refresh_token')
        if 'access_token' in st.session_state:
            del st.session_state['access_token']
        st.rerun()

# --- WORKOUT BUILDER ---
col1, col2 = st.columns(2)
with col1:
    workout_name = st.text_input("Workout Name", "Zone Run")
with col2:
    st.write("**Threshold Pace (min/mile)**")
    p_col1, p_col2 = st.columns(2)
    # ⬇️ UPDATED: Default set to 8:39
    with p_col1:
        p_min = st.number_input("Minutes", 4, 15, 8, key="p_min")
    with p_col2:
        p_sec = st.number_input("Seconds", 0, 59, 39, key="p_sec")
    
    total_seconds_per_mile = (p_min * 60) + p_sec
    threshold_pace_mps = 1609.34 / total_seconds_per_mile

st.subheader("🛠️ Build Intervals")

if 'intervals' not in st.session_state:
    st.session_state.intervals = []

# --- CUSTOM ZONE DEFINITIONS ---
# Calculated based on user's 8:39 Threshold
ZONES = {
    "Zone 1 (Recovery)":   (0.50, 0.69), # < 12:33 pace
    "Zone 2 (Endurance)":  (0.69, 0.83), # 10:29 - 12:32 pace
    "Zone 3 (Tempo)":      (0.83, 0.91), # 9:32 - 10:28 pace
    "Zone 4 (Threshold)":  (0.91, 1.05), # 8:14 - 9:31 pace
    "Zone 5 (VO2 Max)":    (1.05, 1.18), # 7:22 - 8:13 pace
    "Zone 6 (Anaerobic)":  (1.18, 1.33), # 6:30 - 7:21 pace
    "Zone 7 (Neuromus)":   (1.33, 1.50)  # > 6:29 pace
}

with st.form("add_interval", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    with c1: 
        i_name = st.text_input("Label", "Interval")
    with c2: 
        i_dur = st.number_input("Duration (seconds)", 30, 3600, 300, step=30)
    with c3:
        target_mode = st.radio("Target Mode", ["Select Zone", "Custom %"], horizontal=True)
        
        if target_mode == "Select Zone":
            selected_zone_name = st.selectbox("Zone", list(ZONES.keys()))
            range_low, range_high = ZONES[selected_zone_name]
            target_pct = (range_low + range_high) / 2
        else:
            user_pct = st.slider("Pace (% of Threshold)", 50, 150, 100, 1)
            target_pct = user_pct / 100.0
            range_low = target_pct - 0.02
            range_high = target_pct + 0.02

    if target_pct < 0.69:
        auto_type = "wu" if "Warm" in i_name else "recover"
    elif target_pct > 1.05:
        auto_type = "active"
    else:
        auto_type = "active"
        
    if st.form_submit_button("➕ Add Interval"):
        st.session_state.intervals.append({
            "name": i_name,
            "duration": i_dur,
            "type_code": auto_type,
            "type_label": "Zone/Custom",
            "pace_pct": target_pct,
            "target_low": range_low,
            "target_high": range_high,
            "mode": target_mode,
            "zone_name": selected_zone_name if target_mode == "Select Zone" else f"{int(target_pct*100)}%"
        })

if st.session_state.intervals:
    st.write("### Plan Preview")
    total_time = 0
    for idx, interval in enumerate(st.session_state.intervals):
        total_time += interval['duration']
        cols = st.columns([0.1, 0.4, 0.2, 0.2, 0.1])
        cols[0].write(f"#{idx+1}")
        
        # Display Pace Range for verification
        pace_min = (1609.34 / (threshold_pace_mps * interval['target_high'])) / 60
        pace_max = (1609.34 / (threshold_pace_mps * interval['target_low'])) / 60
        
        p_min_str = f"{int(pace_min)}:{int((pace_min%1)*60):02d}"
        p_max_str = f"{int(pace_max)}:{int((pace_max%1)*60):02d}"
        
        cols[1].write(f"**{interval['name']}**")
        cols[2].write(f"{interval['duration']}s")
        if interval['mode'] == 'Select Zone':
            cols[3].write(f"**{interval['zone_name']}**\n({p_min_str} - {p_max_str}/mi)")
        else:
            cols[3].write(f"**{interval['zone_name']}**")
            
        if cols[4].button("❌", key=f"del_{idx}"):
            st.session_state.intervals.pop(idx)
            st.rerun()
    
    if st.button("🚀 Upload & Schedule", type="primary"):
        with st.spinner("Talking to Wahoo..."):
            plan_json = {
                "header": {
                    "name": workout_name,
                    "version": "1.0.0",
                    "description": "Custom KICKR RUN Zone Plan",
                    "workout_type_family": 1, 
                    "workout_type_location": 0, 
                    "threshold_speed": threshold_pace_mps
                },
                "intervals": []
            }
            for i in st.session_state.intervals:
                plan_json["intervals"].append({
                    "name": i['name'],
                    "exit_trigger_type": "time",
                    "exit_trigger_value": i['duration'],
                    "intensity_type": i['type_code'],
                    "targets": [{
                        "type": "threshold_speed", 
                        "low": i['target_low'], 
                        "high": i['target_high']
                    }]
                })
            
            plan_id = upload_plan_to_wahoo(active_token, plan_json, workout_name)
            if plan_id:
                w_id = schedule_workout(active_token, plan_id, workout_name, total_time)
                if w_id:
                    st.success(f"Success! Workout scheduled (ID: {w_id})")
                    st.balloons()

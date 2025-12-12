import streamlit as st
import requests
import json
import base64
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

# ==========================================
# CONFIGURATION & SECRETS
# ==========================================
# Try to load from Streamlit Secrets (Cloud) or fallback to Sandbox (Local)
try:
    CLIENT_ID = st.secrets["WAHOO_CLIENT_ID"]
    CLIENT_SECRET = st.secrets["WAHOO_CLIENT_SECRET"]
    REDIRECT_URI = st.secrets["WAHOO_REDIRECT_URI"]
except (FileNotFoundError, KeyError):
    # 🚨 Sandbox Defaults (Only for running on your laptop)
    CLIENT_ID = 'Rn_RRKHwFLUHyYKTBq6filJo-MmPbX2h3caMwL2jOg4'
    CLIENT_SECRET = 'lEQDPbc1EySK1NT0-0ZVN6G5wyVZHiDXzfxq0NX0e1o'
    REDIRECT_URI = 'https://localhost'

SCOPES = "power_zones_read power_zones_write workouts_read workouts_write plans_read plans_write routes_read routes_write user_read"

# ==========================================
# BACKEND LOGIC
# ==========================================

def get_auth_url():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "response_type": "code"
    }
    return f"https://api.wahooligan.com/oauth/authorize?{urllib.parse.urlencode(params)}"

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
            # Store in Session State (Browser Memory)
            st.session_state['wahoo_token'] = tokens['access_token']
            return tokens['access_token']
        else:
            st.error(f"Auth Failed: {res.text}")
            return None
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

def check_token_validity(access_token):
    # Simple check to see if the token works
    try:
        res = requests.get("https://api.wahooligan.com/v1/user", headers={"Authorization": f"Bearer {access_token}"})
        return res.status_code == 200
    except:
        return False

def get_valid_token():
    # Check if we are already logged in during this session
    if 'wahoo_token' in st.session_state:
        token = st.session_state['wahoo_token']
        if check_token_validity(token):
            return token
        else:
            # Token expired or invalid
            del st.session_state['wahoo_token']
            return None
    return None

def upload_plan_to_wahoo(token, plan_json, plan_name):
    # 1. Prepare Plan File
    json_str = json.dumps(plan_json)
    b64_file = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
    
    payload = {
        "plan[file]": f"data:application/json;base64,{b64_file}",
        "plan[filename]": "kickr_run.json",
        "plan[external_id]": f"RUN_{int(time.time())}",
        "plan[provider_updated_at]": datetime.now(timezone.utc).isoformat()
    }
    
    # 2. POST to Plans Endpoint
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.post("https://api.wahooligan.com/v1/plans", headers=headers, data=payload)
    
    if res.status_code in [200, 201]:
        return res.json()['id']
    else:
        st.error(f"Plan Upload Error: {res.text}")
        return None

def schedule_workout(token, plan_id, plan_name, duration_sec):
    # 3. POST to Workouts Endpoint (Schedule for NOW)
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
# UI LOGIC
# ==========================================

st.set_page_config(page_title="Wahoo KICKR RUN Builder", page_icon="🏃")

# 1. Handle OAuth Redirect (Auto-Login logic)
if 'code' in st.query_params:
    code = st.query_params['code']
    exchange_code_for_token(code)
    # Clear URL to look clean
    st.query_params.clear()
    st.rerun()

st.title("🏃 KICKR RUN Workout Builder")

# 2. Check Connection
token = get_valid_token()

if not token:
    st.warning("⚠️ Not Connected")
    auth_url = get_auth_url()
    st.markdown("### Step 1: Login")
    # This button takes the user to Wahoo, then Wahoo sends them back here
    st.link_button("Login with Wahoo", auth_url)
    st.stop() # Stop rendering the rest until logged in

st.success("✅ Connected to Wahoo")

# --- WORKOUT SETTINGS ---
st.divider()
col1, col2 = st.columns(2)
with col1:
    workout_name = st.text_input("Workout Name", "My KICKR Run")
with col2:
    pace_min_mile = st.number_input("Threshold Pace (min/mile)", 4.0, 15.0, 8.0, 0.1, help="e.g. 8.5 for 8:30 min/mile")
    # Convert to m/s for API
    threshold_pace_mps = 1609.34 / (pace_min_mile * 60)

# --- INTERVAL BUILDER ---
st.subheader("🛠️ Build Intervals")

if 'intervals' not in st.session_state:
    st.session_state.intervals = []

# Form to add new intervals
with st.form("add_interval_form", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        i_name = st.text_input("Label", "Interval")
    with c2:
        i_dur = st.number_input("Duration (seconds)", 30, 3600, 60, step=30)
    with c3:
        i_pace_pct = st.slider("Pace (% of Threshold)", 50, 150, 100, 5)
    
    type_options = {"Warm Up": "wu", "Active": "active", "Recovery": "recover", "Cool Down": "cd"}
    i_type_label = st.selectbox("Type", list(type_options.keys()))
    i_type_code = type_options[i_type_label]
    
    if st.form_submit_button("➕ Add Interval"):
        st.session_state.intervals.append({
            "name": i_name,
            "duration": i_dur,
            "type": i_type_code,
            "type_label": i_type_label,
            "pace_pct": i_pace_pct / 100.0
        })

# --- PREVIEW & UPLOAD ---
if st.session_state.intervals:
    st.write("### Current Plan")
    total_time = 0
    for idx, interval in enumerate(st.session_state.intervals):
        total_time += interval['duration']
        cols = st.columns([0.1, 0.4, 0.2, 0.2, 0.1])
        cols[0].write(f"#{idx+1}")
        cols[1].write(f"**{interval['name']}** ({interval.get('type_label', interval['type'])})")
        cols[2].write(f"{interval['duration']}s")
        cols[3].write(f"{int(interval['pace_pct']*100)}% Pace")
        if cols[4].button("❌", key=f"del_{idx}"):
            st.session_state.intervals.pop(idx)
            st.rerun()
    
    st.caption(f"Total Duration: {int(total_time/60)} minutes")

    if st.button("🚀 Upload & Schedule for Today", type="primary"):
        with st.spinner("Uploading plan to Wahoo Cloud..."):
            # Construct JSON
            plan_json = {
                "header": {
                    "name": workout_name,
                    "version": "1.0.0",
                    "description": "Created via Streamlit Builder",
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
                    "intensity_type": i['type'],
                    "targets": [{"type": "threshold_speed", "low": i['pace_pct'] - 0.02, "high": i['pace_pct'] + 0.02}]
                })
            
            # Execute API Calls
            plan_id = upload_plan_to_wahoo(token, plan_json, workout_name)
            if plan_id:
                w_id = schedule_workout(token, plan_id, workout_name, total_time)
                if w_id:
                    st.success(f"🎉 Success! Workout Scheduled (ID: {w_id}). Check your Wahoo App!")
                    st.balloons()
else:
    st.info("Add some intervals above to begin.")
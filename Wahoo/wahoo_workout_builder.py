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

# Load Secrets securely
try:
    CLIENT_ID = st.secrets["WAHOO_CLIENT_ID"]
    CLIENT_SECRET = st.secrets["WAHOO_CLIENT_SECRET"]
    REDIRECT_URI = st.secrets["WAHOO_REDIRECT_URI"]
except (FileNotFoundError, KeyError):
    # 🚨 Stop execution if secrets are missing (prevents hardcoding risks)
    st.error("❌ Missing Secrets! Please create a `.streamlit/secrets.toml` file with your Wahoo credentials.")
    st.info("The file should look like this:\n"
            "```toml\n"
            "WAHOO_CLIENT_ID = 'your_client_id'\n"
            "WAHOO_CLIENT_SECRET = 'your_client_secret'\n"
            "WAHOO_REDIRECT_URI = 'https://localhost'\n"
            "```")
    st.stop()

# Scopes needed for plans/workouts
SCOPES = "power_zones_read power_zones_write workouts_read workouts_write plans_read plans_write user_read"

# ==========================================
# 2. AUTHENTICATION (The "Sticky" Logic)
# ==========================================

# Initialize Cookie Manager
@st.cache_resource(experimental_allow_widgets=True)
def get_manager():
    return stx.CookieManager()

cookie_manager = get_manager()

def get_auth_url():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "response_type": "code"
    }
    return f"https://api.wahooligan.com/oauth/authorize?{urllib.parse.urlencode(params)}"

def refresh_access_token(refresh_token):
    """Uses the stored refresh token to get a fresh access token silently."""
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
            # Update the refresh token in the cookie (they rotate)
            cookie_manager.set('wahoo_refresh_token', tokens['refresh_token'], key="set_ref")
            return tokens['access_token']
        else:
            return None
    except:
        return None

def exchange_code_for_token(code):
    """Exchanges the one-time auth code for tokens."""
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
            # 💾 SAVE REFRESH TOKEN TO BROWSER COOKIE
            cookie_manager.set('wahoo_refresh_token', tokens['refresh_token'], key="set_init")
            return tokens['access_token']
        else:
            st.error(f"Auth Failed: {res.text}")
            return None
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

# ==========================================
# 3. API LOGIC (Plans & Workouts)
# ==========================================

def upload_plan_to_wahoo(token, plan_json, plan_name):
    # Encode JSON file to Base64
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
            "workout_type_id": 1, # Generic Run
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
# 4. MAIN UI EXECUTION
# ==========================================

st.title("🏃 KICKR RUN Workout Builder")

# --- AUTHENTICATION HANDLER ---
access_token = None
stored_refresh_token = cookie_manager.get('wahoo_refresh_token')

# Case A: Handling Redirect from Wahoo
if 'code' in st.query_params:
    code = st.query_params['code']
    with st.spinner("Logging in..."):
        access_token = exchange_code_for_token(code)
    st.query_params.clear() # Clean URL
    st.rerun()

# Case B: We have a cookie, try to refresh silently
elif stored_refresh_token:
    if 'session_access_token' not in st.session_state:
        # Get a fresh access token using the refresh token
        new_token = refresh_access_token(stored_refresh_token)
        if new_token:
            st.session_state['session_access_token'] = new_token
            access_token = new_token
        else:
            st.warning("Session expired. Please log in again.")
            cookie_manager.delete('wahoo_refresh_token')
    else:
        access_token = st.session_state['session_access_token']

# Case C: No cookie, No code -> Show Login
if not access_token:
    st.info("Please log in to Wahoo Cloud to enable uploading.")
    st.link_button("Login with Wahoo", get_auth_url())
    st.stop()
else:
    st.success("✅ Connected to Wahoo Cloud")

st.divider()

# --- WORKOUT BUILDER UI ---

col1, col2 = st.columns(2)
with col1:
    workout_name = st.text_input("Workout Name", "Interval Run")
with col2:
    # KICKR RUN uses Speed, so we convert Min/Mile -> M/S
    pace_min_mile = st.number_input("Threshold Pace (min/mile)", 4.0, 15.0, 8.5, 0.1, help="Example: 8.5 means 8:30 min/mile")
    threshold_pace_mps = 1609.34 / (pace_min_mile * 60)

st.subheader("🛠️ Build Intervals")

if 'intervals' not in st.session_state:
    st.session_state.intervals = []

# Interval Input Form
with st.form("add_interval", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        i_name = st.text_input("Label", "Interval")
    with c2:
        i_dur = st.number_input("Duration (seconds)", 30, 3600, 60, step=30)
    with c3:
        i_pace_pct = st.slider("Pace (% of Threshold)", 50, 150, 100, 5)
    
    # Map Friendly Labels to API Codes
    type_map = {"Warm Up": "wu", "Active": "active", "Recovery": "recover", "Cool Down": "cd"}
    i_type_label = st.selectbox("Type", list(type_map.keys()))
    
    if st.form_submit_button("➕ Add Interval"):
        st.session_state.intervals.append({
            "name": i_name,
            "duration": i_dur,
            "type_code": type_map[i_type_label],
            "type_label": i_type_label,
            "pace_pct": i_pace_pct / 100.0
        })

# Preview & Upload
if st.session_state.intervals:
    st.write("### Plan Preview")
    
    total_time = 0
    for idx, interval in enumerate(st.session_state.intervals):
        total_time += interval['duration']
        # Calculate actual pace for display
        target_mps = threshold_pace_mps * interval['pace_pct']
        target_min_mile = (1609.34 / target_mps) / 60
        mins = int(target_min_mile)
        secs = int((target_min_mile - mins) * 60)
        
        cols = st.columns([0.1, 0.3, 0.2, 0.3, 0.1])
        cols[0].write(f"#{idx+1}")
        cols[1].write(f"**{interval['name']}** ({interval['type_label']})")
        cols[2].write(f"{interval['duration']}s")
        cols[3].write(f"{int(interval['pace_pct']*100)}% ({mins}:{secs:02d}/mi)")
        if cols[4].button("❌", key=f"del_{idx}"):
            st.session_state.intervals.pop(idx)
            st.rerun()
    
    st.caption(f"Total Duration: {int(total_time/60)} minutes")

    if st.button("🚀 Upload & Schedule", type="primary"):
        with st.spinner("Talking to Wahoo..."):
            
            # Construct JSON Payload
            plan_json = {
                "header": {
                    "name": workout_name,
                    "version": "1.0.0",
                    "description": "Custom KICKR RUN Interval Plan",
                    "workout_type_family": 1, # Running
                    "workout_type_location": 0, # Indoor
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
                    # IMPORTANT: API requires Low/High, but for ERG mode they can be tight
                    "targets": [{
                        "type": "threshold_speed", 
                        "low": i['pace_pct'] - 0.01, 
                        "high": i['pace_pct'] + 0.01
                    }]
                })
            
            # 1. Upload Plan
            plan_id = upload_plan_to_wahoo(access_token, plan_json, workout_name)
            
            # 2. Schedule Workout
            if plan_id:
                w_id = schedule_workout(access_token, plan_id, workout_name, total_time)
                if w_id:
                    st.success(f"Success! Workout scheduled for NOW (ID: {w_id}). Check your Wahoo Element app or KICKR.")
                    st.balloons()

else:
    st.info("Add intervals to enable uploading.")

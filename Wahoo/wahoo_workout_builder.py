import streamlit as st
import requests
import json
import base64
import time
import urllib.parse
import uuid
import os
from datetime import datetime, timezone
import extra_streamlit_components as stx

# ==========================================
# 1. CONFIGURATION
# ==========================================
st.set_page_config(page_title="Wahoo KICKR RUN Builder", page_icon="🏃", layout="centered")

# Ensure library directory exists
if not os.path.exists("saved_workouts"):
    os.makedirs("saved_workouts")

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
# 3. API & DATA LOGIC
# ==========================================

def flatten_blocks_to_intervals(blocks):
    """Converts the Block structure into the flat list Wahoo expects."""
    flat_list = []
    for block in blocks:
        # Repeat the sequence 'reps' times
        for _ in range(block['reps']):
            for interval in block['intervals']:
                # Create a copy to avoid reference issues
                flat_list.append(interval.copy())
    return flat_list

def upload_plan_to_wahoo(token, blocks, plan_name, threshold_mps):
    # Flatten the blocks first
    flat_intervals = flatten_blocks_to_intervals(blocks)
    
    plan_json = {
        "header": {
            "name": plan_name,
            "version": "1.0.0",
            "description": "Created with KICKR RUN Builder",
            "workout_type_family": 1, 
            "workout_type_location": 0, 
            "threshold_speed": threshold_mps
        },
        "intervals": []
    }

    for i in flat_intervals:
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

def schedule_workout(token, plan_id, plan_name, total_duration):
    headers = {"Authorization": f"Bearer {token}"}
    start_time = datetime.now(timezone.utc).isoformat()
    minutes_int = int(total_duration / 60)
    
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

def save_workout_locally(name, blocks, threshold_pace_min, threshold_pace_sec):
    data = {
        "name": name,
        "blocks": blocks,
        "p_min": threshold_pace_min,
        "p_sec": threshold_pace_sec,
        "saved_at": datetime.now().isoformat()
    }
    # Sanitize filename
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip()
    filename = f"saved_workouts/{safe_name}.json"
    with open(filename, 'w') as f:
        json.dump(data, f)
    return filename

def load_workout_locally(filename):
    with open(filename, 'r') as f:
        return json.load(f)

# ==========================================
# 4. HELPER FUNCTIONS
# ==========================================

def move_block(index, direction):
    if direction == -1 and index > 0:
        st.session_state.blocks[index], st.session_state.blocks[index-1] = st.session_state.blocks[index-1], st.session_state.blocks[index]
    elif direction == 1 and index < len(st.session_state.blocks) - 1:
        st.session_state.blocks[index], st.session_state.blocks[index+1] = st.session_state.blocks[index+1], st.session_state.blocks[index]

def get_target_pct(mode, zone_key, slider_val, zone_map):
    if mode == "Select Zone":
        low, high = zone_map[zone_key]
        return (low + high) / 2, low, high, zone_key
    else:
        pct = slider_val / 100.0
        return pct, pct - 0.02, pct + 0.02, f"{slider_val}%"

def determine_type(pct, name):
    if pct < 0.69: return "wu" if "Warm" in name else "recover"
    elif pct > 1.05: return "active"
    else: return "active"

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

# ==========================================
# 6. APP NAVIGATION & STATE
# ==========================================

if 'blocks' not in st.session_state:
    st.session_state.blocks = []
if 'workout_name' not in st.session_state:
    st.session_state.workout_name = "Zone Run"
if 'p_min' not in st.session_state:
    st.session_state.p_min = 8
if 'p_sec' not in st.session_state:
    st.session_state.p_sec = 39

page = st.sidebar.radio("Menu", ["Builder", "Library"])

# Logout Button in Sidebar
if st.sidebar.button("Logout"):
    cookie_manager.delete('wahoo_refresh_token')
    if 'access_token' in st.session_state:
        del st.session_state['access_token']
    st.rerun()

ZONES = {
    "Zone 1 (Recovery)": (0.50, 0.69),
    "Zone 2 (Endurance)": (0.69, 0.83),
    "Zone 3 (Tempo)": (0.83, 0.91),
    "Zone 4 (Threshold)": (0.91, 1.05),
    "Zone 5 (VO2 Max)": (1.05, 1.18),
    "Zone 6 (Anaerobic)": (1.18, 1.33),
    "Zone 7 (Neuromus)": (1.33, 1.50)
}

# ==========================================
# PAGE: LIBRARY
# ==========================================
if page == "Library":
    st.header("📂 Workout Library")
    
    files = [f for f in os.listdir("saved_workouts") if f.endswith(".json")]
    
    if not files:
        st.info("No saved workouts yet. Go to Builder to create one!")
    else:
        for f in files:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**{f.replace('.json', '')}**")
                with col2:
                    if st.button("📂 Load", key=f"load_{f}"):
                        data = load_workout_locally(f"saved_workouts/{f}")
                        st.session_state.workout_name = data['name']
                        st.session_state.blocks = data['blocks']
                        st.session_state.p_min = data['p_min']
                        st.session_state.p_sec = data['p_sec']
                        st.success(f"Loaded '{data['name']}'!")
                        time.sleep(0.5)
                        st.rerun()

# ==========================================
# PAGE: BUILDER
# ==========================================
elif page == "Builder":
    
    # --- TOP SETTINGS ---
    with st.expander("⚙️ Workout Settings", expanded=True):
        col1, col2 = st.columns([2, 1])
        with col1:
            st.session_state.workout_name = st.text_input("Workout Name", st.session_state.workout_name)
        with col2:
            st.write("Threshold Pace")
            t_col1, t_col2 = st.columns(2)
            with t_col1: 
                st.session_state.p_min = st.number_input("Min", 4, 15, st.session_state.p_min, label_visibility="collapsed")
            with t_col2: 
                st.session_state.p_sec = st.number_input("Sec", 0, 59, st.session_state.p_sec, label_visibility="collapsed")
            
            threshold_pace_mps = 1609.34 / ((st.session_state.p_min * 60) + st.session_state.p_sec)

    # --- SAVE BUTTON ---
    if st.button("💾 Save to Library"):
        if st.session_state.blocks:
            fn = save_workout_locally(st.session_state.workout_name, st.session_state.blocks, st.session_state.p_min, st.session_state.p_sec)
            st.toast(f"Saved to {fn}")
        else:
            st.error("Add blocks first!")

    st.divider()

    # --- BUILDER TABS ---
    tab1, tab2 = st.tabs(["Single Interval", "🔁 Repeat Set"])

    # TAB 1: SINGLE ADD
    with tab1:
        st.subheader("Add Single Step")
        r1a, r1b = st.columns([1.5, 1])
        with r1a: s_name = st.text_input("Label", value="Interval", key="s_name")
        with r1b:
            st.caption("Duration (Min:Sec)")
            d1, d2 = st.columns(2)
            with d1: s_min = st.number_input("Min", 0, 120, 5, key="s_min")
            # ⬇️ CHANGED: Step=15 for increments
            with d2: s_sec = st.number_input("Sec", 0, 45, 0, step=15, key="s_sec")
        
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
                # Add as a BLOCK with reps=1
                new_block = {
                    "reps": 1,
                    "intervals": [{
                        "name": s_name, "duration": dur, "type_code": determine_type(tpct, s_name),
                        "target_low": tlow, "target_high": thigh, "zone_name": tname, "mode": s_mode
                    }]
                }
                st.session_state.blocks.append(new_block)
                st.rerun()

    # TAB 2: LOOP / REPEAT
    with tab2:
        st.subheader("🔁 Add Repeat Set")
        st.info("Groups intervals into a single repeating block.")
        
        # WORK Part
        st.markdown("#### 1. Work Interval")
        w_col1, w_col2 = st.columns([1.5, 1])
        with w_col1:
            w_mode = st.radio("Work Target", ["Select Zone", "Custom %"], horizontal=True, key="w_mode")
            if w_mode == "Select Zone":
                w_zone = st.selectbox("Zone", list(ZONES.keys()), index=3, key="w_zone")
                w_slider = 100
            else:
                w_zone = list(ZONES.keys())[0]
                w_slider = st.slider("%", 50, 150, 105, key="w_slider")
                
        with w_col2:
            st.caption("Duration")
            wd1, wd2 = st.columns(2)
            with wd1: w_min = st.number_input("Min", 0, 60, 0, key="w_min")
            # ⬇️ CHANGED: Step=15
            with wd2: w_sec = st.number_input("Sec", 0, 45, 30, step=15, key="w_sec")

        st.divider()
        
        # REST Part
        st.markdown("#### 2. Rest Interval")
        r_col1, r_col2 = st.columns([1.5, 1])
        with r_col1:
            r_mode = st.radio("Rest Target", ["Select Zone", "Custom %"], horizontal=True, key="r_mode")
            if r_mode == "Select Zone":
                r_zone = st.selectbox("Zone", list(ZONES.keys()), index=0, key="r_zone")
                r_slider = 100
            else:
                r_zone = list(ZONES.keys())[0]
                r_slider = st.slider("%", 50, 150, 65, key="r_slider")
                
        with r_col2:
            st.caption("Duration")
            rd1, rd2 = st.columns(2)
            with rd1: r_min = st.number_input("Min", 0, 60, 1, key="r_min")
            # ⬇️ CHANGED: Step=15
            with rd2: r_sec = st.number_input("Sec", 0, 45, 30, step=15, key="r_sec")

        st.divider()
        
        # LOOPS
        l_col1, l_col2 = st.columns([1, 2])
        with l_col1:
            loops = st.number_input("🔁 Reps", 2, 20, 3)
        with l_col2:
            st.write("")
            st.write("")
            if st.button("➕ Add Repeat Set", type="primary", use_container_width=True):
                w_dur = (w_min * 60) + w_sec
                r_dur = (r_min * 60) + r_sec
                
                block_intervals = []
                
                # Add Work
                if w_dur > 0:
                    wpct, wlow, whigh, wname = get_target_pct(w_mode, w_zone, w_slider, ZONES)
                    block_intervals.append({
                        "name": "Work", "duration": w_dur, "type_code": "active",
                        "target_low": wlow, "target_high": whigh, "zone_name": wname, "mode": w_mode
                    })
                # Add Rest
                if r_dur > 0:
                    rpct, rlow, rhigh, rname = get_target_pct(r_mode, r_zone, r_slider, ZONES)
                    block_intervals.append({
                        "name": "Rest", "duration": r_dur, "type_code": "recover",
                        "target_low": rlow, "target_high": rhigh, "zone_name": rname, "mode": r_mode
                    })
                
                if block_intervals:
                    # Add as a REPEATING BLOCK
                    new_block = {
                        "reps": loops,
                        "intervals": block_intervals
                    }
                    st.session_state.blocks.append(new_block)
                    st.success(f"Added {loops}x Set!")
                    time.sleep(0.5)
                    st.rerun()

    # --- PREVIEW LIST (BLOCK BASED) ---
    if st.session_state.blocks:
        st.write("### Plan Preview")
        total_seconds = 0
        
        for idx, block in enumerate(st.session_state.blocks):
            
            # Calculate total duration for this block
            block_dur = 0
            for i in block['intervals']:
                block_dur += i['duration']
            total_seconds += (block_dur * block['reps'])
            
            # CARD CONTAINER
            with st.container(border=True):
                
                # ROW 1: HEADER (Reps x Details)
                c1, c2 = st.columns([4, 1])
                with c1:
                    if block['reps'] > 1:
                        st.markdown(f"**🔁 {block['reps']}x Set**")
                    else:
                        st.markdown(f"**{block['intervals'][0]['name']}**")
                
                # ROW 2: CONTENTS
                for sub_i in block['intervals']:
                    m = sub_i['duration'] // 60
                    s = sub_i['duration'] % 60
                    dur_str = f"{m}m {s}s" if s > 0 else f"{m}m"
                    
                    p_min = (1609.34 / (threshold_pace_mps * sub_i['target_high'])) / 60
                    p_max = (1609.34 / (threshold_pace_mps * sub_i['target_low'])) / 60
                    pace_str = f"{int(p_min)}:{int((p_min%1)*60):02d}-{int(p_max)}:{int((p_max%1)*60):02d}"
                    
                    st.caption(f"• {sub_i['name']}: {dur_str} @ {sub_i['zone_name']} ({pace_str}/mi)")

                st.divider()

                # ROW 3: MOBILE BUTTONS (Single Line, Icons Only)
                # ⬇️ CHANGED: Use columns with equal small width to keep them side-by-side on mobile
                b1, b2, b3 = st.columns([1, 1, 1])
                
                # Up
                if b1.button("⬆️", key=f"u{idx}", disabled=(idx==0), use_container_width=True):
                    move_block(idx, -1)
                    st.rerun()
                
                # Down
                if b2.button("⬇️", key=f"d{idx}", disabled=(idx==len(st.session_state.blocks)-1), use_container_width=True):
                    move_block(idx, 1)
                    st.rerun()
                    
                # Delete
                if b3.button("🗑️", key=f"x{idx}", type="secondary", use_container_width=True):
                    st.session_state.blocks.pop(idx)
                    st.rerun()

        st.markdown(f"**Total Duration:** {int(total_seconds/60)} minutes")
        
        if st.button("🚀 Upload & Schedule", type="primary", use_container_width=True):
            with st.spinner("Uploading..."):
                pid = upload_plan_to_wahoo(active_token, st.session_state.blocks, st.session_state.workout_name, threshold_pace_mps)
                if pid:
                    wid = schedule_workout(active_token, pid, st.session_state.workout_name, total_seconds)
                    if wid:
                        st.success("Scheduled! 🎉")
                        st.balloons()

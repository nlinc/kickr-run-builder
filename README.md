# Wahoo KICKR RUN Workout Builder 🏃💨

A simplified web tool to build structured interval workouts and upload them directly to the **Wahoo Cloud API** for use with the **KICKR RUN** smart treadmill.

## Features
* **Visual Builder**: Add Warmup, Active, Recovery, and Cooldown intervals via a simple UI.
* **Smart Pace Targets**: Define your threshold pace (min/mile), and the app calculates the correct `% Threshold Speed` for the treadmill.
* **Instant Upload**: Pushes the plan to Wahoo and schedules it for **"Today"** so it appears immediately on your KICKR RUN / Wahoo App.
* **Mobile Friendly**: Designed to work on your phone's browser.

## 🚀 How to Run Your Own Instance (Self-Hosting)

This application is built with **Python** and **Streamlit**. To run it, you need your own Wahoo Developer credentials.

### Prerequisites
1.  **Wahoo Developer Account**: Register at [developers.wahooligan.com](https://developers.wahooligan.com/).
2.  **Create an App**: Create a new application in the Wahoo portal to get your `Client ID` and `Client Secret`.
    * **Allowed Callback URLs**: Set this to `http://localhost:8501` (for local) or your Streamlit Cloud URL.
    * **Scopes**: Ensure you enable `workouts_write`, `plans_write`, and `user_read`.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/YOUR_USERNAME/kickr-run-builder.git](https://github.com/YOUR_USERNAME/kickr-run-builder.git)
    cd kickr-run-builder
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Secrets:**
    Create a file named `.streamlit/secrets.toml` in the project root (do NOT commit this file):
    ```toml
    WAHOO_CLIENT_ID = "YOUR_CLIENT_ID"
    WAHOO_CLIENT_SECRET = "YOUR_CLIENT_SECRET"
    WAHOO_REDIRECT_URI = "http://localhost:8501" 
    ```

4.  **Run the App:**
    ```bash
    streamlit run wahoo_workout_builder.py
    ```

## ☁️ Deploying to Streamlit Cloud (Free)

1.  Push this code to your own GitHub repository.
2.  Go to [share.streamlit.io](https://share.streamlit.io/) and deploy the repo.
3.  In the Streamlit App Settings, go to **Settings** -> **Secrets** and paste your credentials there (same format as step 3 above).
4.  **Important**: Update your Wahoo Developer App's "Callback URL" to match your new `https://....streamlit.app` URL.

## ⚠️ Disclaimer
This tool is a personal project and is not affiliated with Wahoo Fitness. Use at your own risk. 
* **Safety**: Always verify the speeds and intervals on your treadmill console before starting. 
* **Data**: This app connects directly to the Wahoo API using OAuth. Your credentials are handled securely via Streamlit Secrets and are never exposed in the browser.

## License
MIT License

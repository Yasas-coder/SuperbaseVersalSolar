import os
import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# Import the NEW Google GenAI SDK
from google import genai

# 1. Load Secrets
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "").strip()
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "").strip()
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "").strip()

if SUPABASE_URL and not SUPABASE_URL.startswith(("http://", "https://")):
    SUPABASE_URL = f"https://{SUPABASE_URL}"

# 2. Setup Headers for Supabase
headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# 3. Calculate 24-hour Window
now = datetime.utcnow()
yesterday = now - timedelta(days=1)
start_time_iso = yesterday.isoformat()

# 4. Fetch full 24h data from Supabase
table_name = "solar_telemetry"
url = f"{SUPABASE_URL}/rest/v1/{table_name}?created_at=gte.{start_time_iso}&select=battery_v,battery_a,load_w,ac_energy,created_at&limit=3000"

response = requests.get(url, headers=headers)

if response.status_code != 200 or not response.json():
    print(f"Failed to fetch data: {response.status_code} - {response.text}")
    exit(1)

data = response.json()

# 5. Crunch 24-Hour Numbers
battery_voltages = [row['battery_v'] for row in data if row.get('battery_v') is not None]
loads = [row['load_w'] for row in data if row.get('load_w') is not None]
energies = [row['ac_energy'] for row in data if row.get('ac_energy') is not None]

max_v = max(battery_voltages) if battery_voltages else 0
min_v = min(battery_voltages) if battery_voltages else 0
peak_load = max(loads) if loads else 0
avg_load = sum(loads) / len(loads) if loads else 0

energy_used = (max(energies) - min(energies)) if len(energies) > 1 else 0

system_data_summary = f"""
Solar Telemetry Summary (Past 24 Hours):
- Total AC Energy Consumed: {energy_used:.2f} kWh
- Battery Peak Voltage (Solar Peak): {max_v:.2f} V
- Battery Minimum Voltage (Night Drain): {min_v:.2f} V
- Peak AC Load Drawn: {peak_load:.2f} W
- Average AC Load: {avg_load:.2f} W
- Total Data Points Analyzed: {len(data)} rows
"""

# 6. Generate AI Insight via Gemini (Using the new SDK syntax)
client = genai.Client(api_key=GEMINI_API_KEY)

prompt = f"""
You are an expert renewable energy assistant. Analyze the following 24-hour solar system data and generate a clear, concise daily email report for the system owner.

{system_data_summary}

Please include:
1. A brief overall health rating (e.g., Excellent, Good, Warning).
2. Key performance observations (solar charging performance, battery depth of discharge, load surges).
3. Any actionable recommendations or efficiency tips.

Keep the tone professional, concise, and easy to read on a phone.
"""

response = client.models.generate_content(
    model='gemini-1.5-flash',
    contents=prompt,
)
ai_analysis = response.text

print("--- AI Generated Insight ---")
print(ai_analysis)

# 7. Send Email directly via SMTP
try:
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"⚡ Daily Solar Insight - {datetime.now().strftime('%Y-%m-%d')}"
    
    msg.attach(MIMEText(ai_analysis, 'plain'))

    # Connect to Gmail SMTP Server (Port 587 for TLS)
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    
    server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
    server.quit()
    
    print("Email sent successfully via Gmail SMTP!")
except Exception as e:
    print(f"Failed to send email via SMTP: {e}")

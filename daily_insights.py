import os
import requests
import smtplib
import calendar
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
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

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

table_name = "solar_telemetry"

# 2. Timezone Math (Adjusting for Sri Lanka UTC+5:30)
sl_offset = timedelta(hours=5, minutes=30)
sl_now = datetime.utcnow() + sl_offset

# Calculate Sri Lanka Midnight & 1st of the Month
start_of_today_sl = sl_now.replace(hour=0, minute=0, second=0, microsecond=0)
start_of_month_sl = sl_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

# Convert back to UTC strings so Supabase can understand the query
start_of_today_utc = (start_of_today_sl - sl_offset).isoformat()
start_of_month_utc = (start_of_month_sl - sl_offset).isoformat()
yesterday_utc = (sl_now - timedelta(days=1) - sl_offset).isoformat()

# 3. Helper Function to Get Baseline Readings
def get_baseline_energy(time_iso):
    url = f"{SUPABASE_URL}/rest/v1/{table_name}?created_at=gte.{time_iso}&select=ac_energy&ac_energy=not.is.null&order=created_at.asc&limit=1"
    res = requests.get(url, headers=headers)
    if res.status_code == 200 and res.json():
        return res.json()[0]['ac_energy']
    return None

month_start_energy = get_baseline_energy(start_of_month_utc)
today_start_energy = get_baseline_energy(start_of_today_utc)

# 4. Fetch Last 24 Hours of Data
url_24h = f"{SUPABASE_URL}/rest/v1/{table_name}?created_at=gte.{yesterday_utc}&select=battery_v,battery_a,load_w,ac_energy,created_at&limit=3000"
response = requests.get(url_24h, headers=headers)

if response.status_code != 200 or not response.json():
    print(f"Failed to fetch data: {response.status_code} - {response.text}")
    exit(1)

data = response.json()

# 5. Crunch the Numbers
valid_battery_rows = [row for row in data if row.get('battery_v') is not None]
loads = [row['load_w'] for row in data if row.get('load_w') is not None]
energies = [row['ac_energy'] for row in data if row.get('ac_energy') is not None]

# Parse Peak Voltage & Exact Time
if valid_battery_rows:
    max_v_row = max(valid_battery_rows, key=lambda x: x['battery_v'])
    max_v = max_v_row['battery_v']
    
    # Convert Supabase UTC time to SL Time for the email
    raw_time = max_v_row['created_at'].replace('Z', '+00:00')
    try:
        dt_obj = datetime.fromisoformat(raw_time)
        sl_peak_time = dt_obj + sl_offset
        max_v_time = sl_peak_time.strftime("%I:%M %p")
    except:
        max_v_time = raw_time
        
    min_v = min(row['battery_v'] for row in valid_battery_rows)
else:
    max_v, min_v, max_v_time = 0, 0, "N/A"

peak_load = max(loads) if loads else 0
avg_load = sum(loads) / len(loads) if loads else 0

# Calculate Cumulative Usage
latest_energy = energies[-1] if energies else 0
today_usage = (latest_energy - today_start_energy) if (latest_energy and today_start_energy is not None) else 0
month_usage = (latest_energy - month_start_energy) if (latest_energy and month_start_energy is not None) else 0

# Month Forecast Math
days_elapsed = sl_now.day
days_in_month = calendar.monthrange(sl_now.year, sl_now.month)[1]
month_forecast = (month_usage / days_elapsed) * days_in_month if days_elapsed > 0 else 0

# 6. Build the AI Prompt Data
system_data_summary = f"""
-- CEB GRID (AC SYSTEM) --
- This Month's AC Usage (So far): {month_usage:.2f} kWh
- End of Month AC Forecast: {month_forecast:.2f} kWh
- Today's AC Usage (Up to now): {today_usage:.2f} kWh
- Peak AC Load Drawn (Last 24h): {peak_load:.2f} W
- Average AC Load (Last 24h): {avg_load:.2f} W

-- OFF-GRID (DC BATTERY SYSTEM) --
- Battery Peak Voltage: {max_v:.2f} V (Recorded at exactly: {max_v_time})
- Battery Minimum Voltage (Night Drain): {min_v:.2f} V
"""

client = genai.Client(api_key=GEMINI_API_KEY)

prompt = f"""
You are an expert renewable energy assistant. Analyze the following telemetry data and generate a clear, concise daily email report for the system owner.

CRITICAL INSTRUCTIONS - YOU MUST FOLLOW THESE EXACTLY:
1. LANGUAGE: The entire output MUST be written in Sinhala (සිංහල).
2. STRUCTURE ORDER: 
   - First paragraph: State "This Month's Usage" and the "End of Month Forecast".
   - Second paragraph: State "Today's Usage (up to now)".
   - Third paragraph: Provide system health analysis. You MUST clearly separate the CEB Grid AC usage from the Battery/Solar DC health.
   - Fourth paragraph: You MUST state the exact peak battery voltage and the exact time it occurred based on the data provided.
3. ARCHITECTURE RULES: The AC load is powered by the main CEB grid and is completely separate from the battery. The battery powers a separate DC circuit. DO NOT imply that the battery powers the AC loads or that AC surges affect the battery.

Data to translate and analyze:
{system_data_summary}
"""

response = client.models.generate_content(
    model='gemini-3.5-flash-lite',
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
    
    # Subject line updated to show Sri Lanka Date
    msg['Subject'] = f"⚡ දෛනික සූර්ය බලශක්ති වාර්තාව - {sl_now.strftime('%Y-%m-%d')}"
    
    # UTF-8 encoding ensures Sinhala text renders correctly in the email
    msg.attach(MIMEText(ai_analysis, 'plain', 'utf-8'))

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    
    server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
    server.quit()
    
    print("Email sent successfully in Sinhala!")
except Exception as e:
    print(f"Failed to send email via SMTP: {e}")

import os
import requests
import smtplib
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

# 2. Fetch App Settings (To match the Web Dashboard EXACTLY)
settings_url = f"{SUPABASE_URL}/rest/v1/app_settings?id=eq.1&select=*"
settings_res = requests.get(settings_url, headers=headers).json()
if settings_res:
    last_billing_date = settings_res[0].get("last_billing_date", "2026-07-22")
    cycle_days = float(settings_res[0].get("cycle_days", 33))
    energy_offset = float(settings_res[0].get("energy_offset", 35.0))
else:
    last_billing_date, cycle_days, energy_offset = "2026-07-22", 33.0, 35.0

# 3. Timezone Math (Sri Lanka UTC+5:30)
sl_offset = timedelta(hours=5, minutes=30)
sl_now = datetime.utcnow() + sl_offset

cycle_start_sl = datetime.strptime(last_billing_date, "%Y-%m-%d")
start_of_today_sl = sl_now.replace(hour=0, minute=0, second=0, microsecond=0)

# Convert to UTC strings for Supabase querying
cycle_start_utc = (cycle_start_sl - sl_offset).isoformat()
start_of_today_utc = (start_of_today_sl - sl_offset).isoformat()
yesterday_utc = (sl_now - timedelta(days=1) - sl_offset).isoformat()

# 4. Helper function to get baseline energy readings
def get_baseline_energy(time_iso):
    url = f"{SUPABASE_URL}/rest/v1/solar_telemetry?created_at=gte.{time_iso}&select=ac_energy&ac_energy=not.is.null&order=created_at.asc&limit=1"
    res = requests.get(url, headers=headers)
    if res.status_code == 200 and res.json():
        return float(res.json()[0]['ac_energy'])
    return 0.0

cycle_start_energy = get_baseline_energy(cycle_start_utc)
today_start_energy = get_baseline_energy(start_of_today_utc)

# 5. Fetch Last 24 Hours of Data
url_24h = f"{SUPABASE_URL}/rest/v1/solar_telemetry?created_at=gte.{yesterday_utc}&select=battery_v,battery_a,load_w,ac_energy,created_at&limit=3000"
data = requests.get(url_24h, headers=headers).json()

# 6. Crunch the Numbers to perfectly match the Vercel App
valid_battery_rows = [row for row in data if row.get('battery_v') is not None]
loads = [row for row in data if row.get('load_w') is not None]

latest_energy = float(data[-1]['ac_energy']) if data and data[-1].get('ac_energy') is not None else today_start_energy

if valid_battery_rows:
    max_v_row = max(valid_battery_rows, key=lambda x: x['battery_v'])
    max_v = max_v_row['battery_v']
    min_v = min(row['battery_v'] for row in valid_battery_rows)
    
    raw_time = max_v_row['created_at'].replace('Z', '+00:00')
    try:
        sl_peak_time = datetime.fromisoformat(raw_time) + sl_offset
        max_v_time = sl_peak_time.strftime("%I:%M:%S %p")
    except:
        max_v_time = raw_time
else:
    max_v, min_v, max_v_time = 0, 0, "N/A"

peak_load = max(row['load_w'] for row in loads) if loads else 0
avg_load = sum(row['load_w'] for row in loads) / len(loads) if loads else 0

# The precise Vercel Dashboard Math
raw_used = max(0, latest_energy - cycle_start_energy)
used_so_far = raw_used + energy_offset
used_today = max(0, latest_energy - today_start_energy)

elapsed_ms = max(3600000, (sl_now - cycle_start_sl).total_seconds() * 1000)
elapsed_days = elapsed_ms / 86400000
forecasted_total = (used_so_far / elapsed_days) * cycle_days

# 7. Build AI Prompt
system_data_summary = f"""
-- CEB GRID (AC SYSTEM) --
- Billing Cycle Usage (Used So Far): {used_so_far:.2f} kWh
- End of Cycle Forecast: {forecasted_total:.2f} kWh
- Today's Usage: {used_today:.2f} kWh
- Peak AC Load (Last 24h): {peak_load:.2f} W
- Average AC Load (Last 24h): {avg_load:.2f} W

-- OFF-GRID (DC BATTERY SYSTEM) --
- Battery Peak Voltage: {max_v:.2f} V (Time: {max_v_time})
- Battery Minimum Voltage: {min_v:.2f} V
"""

client = genai.Client(api_key=GEMINI_API_KEY)

prompt = f"""
You are an expert renewable energy assistant. Analyze the following telemetry data and generate a clear, concise daily email report.

CRITICAL INSTRUCTIONS:
1. LANGUAGE: The entire output MUST be written in Sinhala (සිංහල).
2. STRUCTURE ORDER: 
   - Paragraph 1: State the total "Used So Far" in the current billing cycle and the "Projected Month End" forecast.
   - Paragraph 2: State "Used Today".
   - Paragraph 3: Provide data insights for the AC side and the DC side.
   - Paragraph 4: State the exact peak battery voltage and the exact time it occurred.
3. TONE: DO NOT explain system architecture. DO NOT tell the user that the AC and DC systems are separate, independent, or unrelated. Just present the AC numbers and the DC numbers smoothly and professionally.

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

# 8. Send Email
try:
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"⚡ දෛනික සූර්ය බලශක්ති වාර්තාව - {sl_now.strftime('%Y-%m-%d')}"
    
    msg.attach(MIMEText(ai_analysis, 'plain', 'utf-8'))

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    
    server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
    server.quit()
    
    print("Email sent successfully in Sinhala!")
except Exception as e:
    print(f"Failed to send email via SMTP: {e}")

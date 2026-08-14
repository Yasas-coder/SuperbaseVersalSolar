import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from google import genai
from playwright.sync_api import sync_playwright

# 1. Load Secrets
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "").strip()
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "").strip()
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

# 2. Scrape the Live Vercel Website for AC Data
VERCEL_URL = "https://superbase-versal-solar.vercel.app/forecast.html"

print("Booting virtual browser and loading Vercel...")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    
    # Force the virtual browser to be in Sri Lanka's timezone
    context = browser.new_context(timezone_id="Asia/Colombo")
    page = context.new_page()
    
    page.goto(VERCEL_URL)
    
    # Wait up to 15 seconds for your JS to fetch Supabase and replace the "--" loading states
    page.wait_for_selector("#val-used:not(:has-text('--'))", timeout=15000)
    
    # Extract the exact text from your HTML elements
    used_so_far = page.locator("#val-used").inner_text().replace('\n', ' ')
    used_today = page.locator("#val-today").inner_text().replace('\n', ' ')
    forecast = page.locator("#val-forecast").inner_text().replace('\n', ' ')
    
    max_v = page.locator("#val-max-v").inner_text().replace('\n', ' ')
    max_v_time = page.locator("#time-max-v").inner_text()
    
    min_v = page.locator("#val-min-v").inner_text().replace('\n', ' ')
    min_v_time = page.locator("#time-min-v").inner_text()
    
    browser.close()

# 3. Fetch Live, Max, and Min SOC Directly from Supabase
print("Fetching Live, Max, and Min SOC from Supabase...")
current_soc = "N/A"
max_soc, max_soc_time = "N/A", "N/A"
min_soc, min_soc_time = "N/A", "N/A"

try:
    if SUPABASE_URL and SUPABASE_KEY:
        headers = {
            "apikey": SUPABASE_KEY, 
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }
        
        # Calculate the UTC time for 24 hours ago
        start_iso = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # Helper function to query Supabase and format the time to Sri Lanka Time
        def get_soc(query):
            res = requests.get(f"{SUPABASE_URL}/rest/v1/solar_telemetry?{query}", headers=headers)
            if res.status_code == 200 and res.json():
                data = res.json()[0]
                dt_utc = datetime.strptime(data['created_at'][:19], "%Y-%m-%dT%H:%M:%S")
                dt_sl = dt_utc + timedelta(hours=5, minutes=30)
                return f"{data['soc']}%", dt_sl.strftime("%I:%M %p")
            return "N/A", "N/A"

        # 1. Get Live SOC
        current_soc, _ = get_soc("soc=not.is.null&select=soc,created_at&order=created_at.desc&limit=1")
        
        # 2. Get Max SOC for the last 24 hours
        max_soc, max_soc_time = get_soc(f"created_at=gte.{start_iso}&soc=not.is.null&select=soc,created_at&order=soc.desc,created_at.desc&limit=1")
        
        # 3. Get Min SOC for the last 24 hours
        min_soc, min_soc_time = get_soc(f"created_at=gte.{start_iso}&soc=not.is.null&select=soc,created_at&order=soc.asc,created_at.desc&limit=1")

except Exception as e:
    print(f"Failed to fetch SOC metrics from Supabase: {e}")

print(f"Scraped Data: Today={used_today}, Total={used_so_far}, MaxV={max_v}, LiveSOC={current_soc}, MaxSOC={max_soc}, MinSOC={min_soc}")

# 4. Build AI Prompt (Updated with Max/Min SOC metrics)
system_data_summary = f"""
-- AC SYSTEM --
- Used So Far: {used_so_far}
- Projected Month End: {forecast}
- Used Today: {used_today}

-- DC BATTERY SYSTEM (52Ah LiFePO4) --
- Current State of Charge (SOC): {current_soc}
- Today's Max SOC: {max_soc} ({max_soc_time})
- Today's Min SOC: {min_soc} ({min_soc_time})
- Estimated State of Health (SOH): 100%
- Today's Peak Voltage: {max_v} ({max_v_time})
- Today's Lowest Voltage: {min_v} ({min_v_time})
"""

client = genai.Client(api_key=GEMINI_API_KEY)

prompt = f"""
You are an expert renewable energy assistant. 

CRITICAL INSTRUCTIONS:
1. LANGUAGE: The entire output MUST be written in Sinhala (සිංහල).
2. STRUCTURE ORDER: 
   - Paragraph 1: State the total "Used So Far" and the "Projected Month End" forecast.
   - Paragraph 2: State "Used Today".
   - Paragraph 3: State the Current SOC, the Estimated SOH (100%), the Maximum SOC with its time, the Minimum SOC with its time, the exact peak battery voltage with its time, and the Lowest Battery Voltage with its time. Mention it is a 52Ah LiFePO4 battery setup.
3. TONE: DO NOT explain system architecture. DO NOT tell the user that the AC and DC systems are separate. Just present the numbers smoothly. No explanations, Just give data in sinhala and english.

Data to translate and analyze:
{system_data_summary}
"""

print("Generating Sinhala translation via Gemini...")
response = client.models.generate_content(
    model='gemini-3.5-flash-lite',
    contents=prompt,
)
ai_analysis = response.text

# 5. Send Email
# Adjust to Sri Lanka time for the Subject Line
sl_now = datetime.utcnow() + timedelta(hours=5, minutes=30)

try:
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    
    # This keeps the comma-separated string for the visible "To:" header in the email
    msg['To'] = RECEIVER_EMAIL 
    msg['Subject'] = f"⚡ දෛනික සූර්ය බලශක්ති වාර්තාව - {sl_now.strftime('%Y-%m-%d')}"
    
    msg.attach(MIMEText(ai_analysis, 'plain', 'utf-8'))

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    
    # Convert your comma-separated secret into a proper list for the SMTP server
    recipient_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
    
    server.sendmail(SENDER_EMAIL, recipient_list, msg.as_string())
    server.quit()
    
    print(f"Email sent successfully to: {recipient_list}")
except Exception as e:
    print(f"Failed to send email: {e}")

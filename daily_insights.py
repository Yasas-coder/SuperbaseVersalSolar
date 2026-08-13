import os
import smtplib
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

# 2. Scrape the Live Vercel Website
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

print(f"Scraped Data: Today={used_today}, Total={used_so_far}, MaxV={max_v}")

# 3. Build AI Prompt
system_data_summary = f"""
-- AC SYSTEM --
- Used So Far: {used_so_far}
- Projected Month End: {forecast}
- Used Today: {used_today}

-- DC BATTERY SYSTEM --
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
   - Paragraph 3: Provide brief, professional data insights.
   - Paragraph 4: State the exact peak battery voltage, the exact time, Lowest Battery VOltage and the exact time it occurred.
3. TONE: DO NOT explain system architecture. DO NOT tell the user that the AC and DC systems are separate. Just present the numbers smoothly.

Data to translate and analyze:
{system_data_summary}
"""

print("Generating Sinhala translation via Gemini...")
response = client.models.generate_content(
    model='gemini-3.5-flash-lite',
    contents=prompt,
)
ai_analysis = response.text

# 4. Send Email
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

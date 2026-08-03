import requests

SUPABASE_URL = "https://YOUR_PROJECT_ID.supabase.co/rest/v1/solar_telemetry"
SUPABASE_KEY = "YOUR_ANON_PUBLIC_KEY"

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

payload = {
    "battery_v": 12.8,
    "battery_a": 0.5,
    "ac_v": 238.5,
    "load_w": 150.0
}

response = requests.post(SUPABASE_URL, json=payload, headers=headers)

if response.status_code in [200, 201]:
    print("✅ Success! Telemetry data inserted into Supabase.")
else:
    print(f"❌ Error: {response.status_code} - {response.text}")

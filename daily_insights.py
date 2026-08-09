import os
import requests
import json
from datetime import datetime, timedelta

# 1. Load Secrets
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 2. Setup Headers for Supabase REST API
headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# 3. Calculate time window (Last 24 hours)
now = datetime.utcnow()
yesterday = now - timedelta(days=1)
start_time_iso = yesterday.isoformat()

# 4. Fetch Data from Supabase
# We query the solar_telemetry table for rows created in the last 24 hours
table_name = "solar_telemetry"
url = f"{SUPABASE_URL}/rest/v1/{table_name}?created_at=gte.{start_time_iso}&select=battery_v,battery_a,load_w,ac_energy,created_at"

response = requests.get(url, headers=headers)

if response.status_code == 200:
    data = response.json()
    
    if not data:
        print("No data found for the last 24 hours.")
        exit()

    # 5. Crunch the daily numbers
    battery_voltages = [row['battery_v'] for row in data if row['battery_v'] is not None]
    loads = [row['load_w'] for row in data if row['load_w'] is not None]
    energies = [row['ac_energy'] for row in data if row['ac_energy'] is not None]
    
    max_v = max(battery_voltages) if battery_voltages else 0
    min_v = min(battery_voltages) if battery_voltages else 0
    peak_load = max(loads) if loads else 0
    avg_load = sum(loads) / len(loads) if loads else 0
    
    # Calculate daily energy used (difference between last and first reading of the day)
    energy_used = (max(energies) - min(energies)) if energies else 0

    # 6. Format the data string for your AI Agent
    ai_prompt_data = f"""
    Here is the solar system data for the last 24 hours:
    - Total Energy Consumed: {energy_used:.2f} kWh
    - Battery Peak Voltage (Solar Max): {max_v:.2f} V
    - Battery Lowest Voltage (Night Drain): {min_v:.2f} V
    - Peak AC Load: {peak_load:.2f} W
    - Average AC Load: {avg_load:.2f} W
    
    Analyze this data, summarize the system's health, and write a short, insightful daily email to the system owner.
    """
    
    print(ai_prompt_data)
    
    # ---------------------------------------------------------
    # YOUR AI & EMAIL CODE GOES HERE
    # e.g., gemini_response = generate_ai_text(ai_prompt_data)
    # send_email("Daily Solar Insight", gemini_response)
    # ---------------------------------------------------------

else:
    print(f"Failed to fetch data: {response.status_code} - {response.text}")

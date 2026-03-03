import subprocess
import json
import re
import time
import sys

def run_pipeline():
    print("🚀 Starting Omni-Scout Phase...")
    # Run the scout and capture its output
    scout_process = subprocess.run(
        [sys.executable, "omni_scout.py"], 
        capture_output=True, 
        text=True
    )
    
    if "SCOUT_JSON::" not in scout_process.stdout:
        print("❌ Could not find valid job data from Omni-Scout.")
        print("Scout Output:", scout_process.stdout)
        print("Scout Error:", scout_process.stderr)
        return

    # Extract everything after SCOUT_JSON::
    json_str = scout_process.stdout.split("SCOUT_JSON::")[1]
    
    # nodriver often prints cleanup messages at the very end of stdout, which corrupts the JSON
    if "successfully removed temp profile" in json_str:
        json_str = json_str.split("successfully removed temp profile")[0]
        
    json_str = json_str.strip()
    
    try:
        jobs = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"❌ JSON Parsing Error: {e}")
        print(f"Raw Extracted String:\n{json_str}")
        return
    print(f"🎯 Scout found {len(jobs)} high-priority jobs. Moving to Application Phase...")
    
    # Loop through each job and apply
    for i, job in enumerate(jobs, 1):
        url = job.get("Job_URL")
        print(f"\n[{i}/{len(jobs)}] Applying to: {job.get('Company', 'Unknown')} - {job.get('Role')}")
        
        # Trigger the apply agent
        apply_process = subprocess.run([sys.executable, "apply_agent.py", url])
        
        if apply_process.returncode == 0:
            print(f"✅ Application finished for {url}")
        else:
            print(f"⚠️ Application encountered an issue for {url}")
            
        # Wait 30 seconds between applications to avoid anti-bot detection
        print("Waiting 30 seconds before next application...")
        time.sleep(30)
        
    print("\n🏁 Fully Automated Cycle Complete.")

if __name__ == "__main__":
    run_pipeline()

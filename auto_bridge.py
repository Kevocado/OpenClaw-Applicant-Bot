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
    
    # Extract the JSON block from the scout's output
    match = re.search(r'SCOUT_JSON::\s*(\[.*?\])', scout_process.stdout, re.DOTALL)
    
    if not match:
        print("❌ Could not find valid job data from Omni-Scout.")
        print("Scout Output:", scout_process.stdout)
        print("Scout Error:", scout_process.stderr)
        return

    jobs = json.loads(match.group(1))
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

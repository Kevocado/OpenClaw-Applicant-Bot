import asyncio
import os
import sys
import json
import traceback
import nodriver as uc
from queue_manager import JobQueue
from omni_scout import run_scout
from apply_agent import run_apply, load_knowledge_base, init_gemini, EXIT_SUCCESS, EXIT_LOW_SCORE, EXIT_HIGH_TIER_PAUSED, EXIT_FAILURE

USER_DATA_DIR = "/Users/sigey/Documents/Projects/OpenClaw Resume Bot/user_data_dir"

async def main():
    print("🚀 Starting OpenClaw Orchestrator (Single Browser Sequence)...")
    queue = JobQueue()
    
    # Initialize the single live browser instance
    has_display = os.getenv("DISPLAY") is not None or sys.platform == "darwin"
    headless_mode = not has_display
    
    print(f"[BROWSER] Launching nodriver (headless={headless_mode}, profile={USER_DATA_DIR})")
    browser = await uc.start(
        headless=headless_mode,
        user_data_dir=USER_DATA_DIR,
        no_sandbox=True,
        browser_args=[
            '--profile-directory=Profile 3',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-setuid-sandbox',
            '--disable-session-crashed-bubble',
            '--enforce-webrtc-ip-handling-policy=default_public_interface_only'
        ]
    )

    try:
        # Phase 1: Scout using the live browser
        # Wait a moment before beginning
        await asyncio.sleep(2)
        print("\n--- PHASE 1: SCOUTING ---")
        
        # Grab the persistent main tab to prevent Focus Stealing
        main_tab = browser.tabs[0] if browser.tabs else await browser.get("about:blank")
        
        added_count = await run_scout(main_tab, queue)
        print(f"✅ Scout Phase Complete. Added {added_count} new unique jobs.\n")

        # Phase 2: Apply using the SAME live browser
        print("--- PHASE 2: APPLYING ---")
        pending_jobs = queue.get_pending_jobs()
        
        if not pending_jobs:
            print("No pending jobs to apply to. Shutting down gracefully.")
            return

        print(f"Found {len(pending_jobs)} pending jobs in the queue.")
        
        # --- GRAND TEST FILTER ---
        test_jobs = {}
        li_found, hs_found = False, False
        
        for j_id, job in pending_jobs.items():
            if not li_found and "linkedin.com" in job['url']:
                test_jobs[j_id] = job
                li_found = True
            elif not hs_found and "joinhandshake.com" in job['url']:
                test_jobs[j_id] = job
                hs_found = True
                
            if li_found and hs_found:
                break # We have our two targets!
        # -------------------------

        print(f"\n[BRIDGE] Initiating Grand Test on {len(test_jobs)} specific jobs.")
        
        # Load KB & Init Gemini once for the whole run
        kb = load_knowledge_base()
        client = init_gemini()
        
        # Using the main_tab approach avoids new windows and WebSocket drops

        for job_id, job_data in test_jobs.items():
            print(f"\n[ORCHESTRATOR] Processing Job: {job_data['company']} - {job_data['title']}")
            try:
                # Pass the main_tab straight to the applicator
                exit_code = await run_apply(main_tab, job_data['url'], client, kb)
                
                if exit_code == EXIT_SUCCESS:
                    queue.update_status(job_id, "APPLIED", notes="Successfully applied.")
                elif exit_code == EXIT_LOW_SCORE:
                    queue.update_status(job_id, "FAILED", notes="Skipped: Low Match Score.")
                elif exit_code == EXIT_HIGH_TIER_PAUSED:
                    queue.update_status(job_id, "PENDING", notes="Paused for manual review (High Tier).")
                else:
                    queue.update_status(job_id, "SOFT_FAIL", notes=f"Failed cleanly with EXIT_FAILURE code.")
                    
            except Exception as e:
                error_msg = str(e)
                print(f"[ORCHESTRATOR] Exception caught for {job_id}: {error_msg}")
                traceback.print_exc()
                
                # Hard Fail boundaries
                if "Workday ATS Skipped" in error_msg:
                    queue.update_status(job_id, "WORKDAY_SKIPPED", notes="ATS blacklisted due to account creation requirements.")
                elif "LinkedIn indicates this job is no longer available" in error_msg:
                    queue.update_status(job_id, "FAILED", notes="Job no longer available.")
                else:
                    queue.update_status(job_id, "SOFT_FAIL", notes=f"Exception caught: {error_msg}")
            
    finally:
        browser.stop()
        print("\n🏁 Fully Automated Cycle Complete.")

if __name__ == "__main__":
    uc.loop().run_until_complete(main())

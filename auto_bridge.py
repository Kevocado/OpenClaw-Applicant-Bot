import asyncio
import os
import sys
import nodriver as uc
from queue_manager import JobQueue
from omni_scout import run_scout
from apply_agent import run_apply, load_knowledge_base, init_gemini

async def main():
    print("🚀 Starting OpenClaw Orchestrator (Single-Tab Sequential Execution)...")
    queue = JobQueue()
    
    # Build an absolute path to a local sandboxed folder
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    BOT_PROFILE_DIR = os.path.join(PROJECT_ROOT, "bot_chrome_profile")
    
    # Ensure the directory exists
    os.makedirs(BOT_PROFILE_DIR, exist_ok=True)
    
    has_display = os.getenv("DISPLAY") is not None or sys.platform == "darwin"
    headless_mode = not has_display
    
    print(f"[BROWSER] Launching nodriver (headless={headless_mode}, profile={BOT_PROFILE_DIR})")
    
    # [ROBUSTNESS]: Prevent headless browser from booting if API keys are missing
    if not os.getenv("GEMINI_API_KEY") and not os.getenv("KEYWORDSAI_API_KEY"):
        print("[BRIDGE] 🚨 CRITICAL ERROR: No LLM API key configured in .env.")
        print("[BRIDGE] You must provide GEMINI_API_KEY (or KEYWORDSAI_API_KEY) to proceed.")
        sys.exit(1)
        
    # Optional: explicitly point to Chrome for Testing if installed
    browser_kwargs = {
        "user_data_dir": BOT_PROFILE_DIR,
        "headless": headless_mode,
        "browser_args": [
            '--no-sandbox',           # [CRITICAL]: Required for running as root on VPS
            '--disable-setuid-sandbox', # [CRITICAL]: Required for running as root on VPS
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-session-crashed-bubble',
            '--enforce-webrtc-ip-handling-policy=default_public_interface_only',
            '--remote-debugging-host=127.0.0.1'
        ]
    }
    
    mac_chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if sys.platform == "darwin" and os.path.exists(mac_chrome_path):
        browser_kwargs["browser_executable_path"] = mac_chrome_path
        
    # Force the browser to ONLY use this isolated directory
    browser = await uc.start(**browser_kwargs)

    try:
        await asyncio.sleep(2)
        print("\n[BRIDGE] Booting Master Browser Orchestrator...")
        
        # Load KB & Init Gemini once for the whole run
        kb = load_knowledge_base()
        client = init_gemini()
        
        main_tab = browser.tabs[0] if browser.tabs else await browser.get("about:blank")
        
        print("[BRIDGE] Launching Continuous Background Pipeline...")
        print("[BRIDGE] You may now move this window to another Desktop Space.")
        
        while True:
            try:
                print(f"\n[{'='*60}]\n[BRIDGE] Phase 1: Scouting New Roles\n")
                await run_scout(main_tab, queue)
                
                print(f"\n[{'='*60}]\n[BRIDGE] Phase 2: Processing Backlog\n")
                await run_apply(browser, main_tab, queue, client, kb)
                
                print("\n[BRIDGE] Full cycle complete. System resting for 30 minutes to emulate human pacing...\n")
                await main_tab.get("about:blank")
                await asyncio.sleep(1800)  # Sleep 30 mins between major indexing sweeps
                
            except Exception as e:
                error_msg = str(e)
                print(f"\n[BRIDGE] ERROR during cycle: {error_msg}")
                
                if "Login Wall" in error_msg:
                    print(f"[BRIDGE] 🚨 CRITICAL: Session blocked by login wall or IP ban.")
                    print(f"[BRIDGE] Halting execution completely to save resources and protect browser profile.")
                    print(f"[BRIDGE] Please run `python3 login_helper.py` or check your cookies.")
                    break  # Break out of the infinite loop gracefully
                    
                print(f"[BRIDGE] Recovering in 5 minutes before retry...\n")
                try:
                    await main_tab.get("about:blank")
                except Exception:
                    pass
                await asyncio.sleep(300)  # Wait 5 minutes before retrying
                continue
            
    finally:
        browser.stop()
        print("\n🏁 Fully Automated Cycle Complete or Terminated.")

if __name__ == "__main__":
    uc.loop().run_until_complete(main())

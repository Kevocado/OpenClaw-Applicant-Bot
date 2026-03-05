import os
import json
import time
import asyncio
from pathlib import Path

# Paths
PAYLOAD_DIR = Path("./execution_payloads")

async def process_payload(payload_path: Path):
    """
    Reads a dispatched payload and uses OpenClaw's clawbrowser skill
    to natively execute the DOM manipulation.
    """
    try:
        data = json.loads(payload_path.read_text(encoding="utf-8"))
        job_id = data.get("job_id")
        job_url = data.get("job_url")
        company = data.get("company")
        role = data.get("role")
        cover_letter = data.get("generated_cover_letter", "")
        qa_answers = data.get("qa_answers", {})
        
        print(f"\n[MAC NODE] 🚀 Processing Payload: {company} - {role} ({job_id})")
        print(f"[MAC NODE] Navigating to target: {job_url}")
        
        # NOTE: Here we will shell out to the `clawbrowser` command line 
        # or use the Playwright Python API natively with our stealth config.
        # Ensure our `openclaw_mac_node.json` configuration is respected.
        
        # --- MOCK EXECUTION FOR NOW ---
        print(f"[MAC NODE] Target URL: {job_url}")
        print(f"[MAC NODE] Injecting Cover Letter: {len(cover_letter)} chars")
        print(f"[MAC NODE] Injecting Q&A Answers: {len(qa_answers)} questions answered")
        await asyncio.sleep(2)  # Emulate execution
        # ------------------------------
        
        # Execution successful. Clean up payload.
        print(f"[MAC NODE] ✅ Execution successful. Purging payload.")
        payload_path.unlink()
        
    except Exception as e:
        print(f"[MAC NODE] ❌ Execution failed for {payload_path.name}: {e}")
        # Rename to indicate failure so we don't infinitely retry
        failed_path = payload_path.with_suffix(".failed")
        payload_path.rename(failed_path)


async def poll_payload_directory():
    """
    Long-running daemon loop that monitors the Tailscale-synced payload directory.
    """
    print("[MAC NODE] 🛡️ OpenClaw Execution Node Online.")
    print(f"[MAC NODE] Polling directory for dispatched payloads: {PAYLOAD_DIR.absolute()}")
    
    PAYLOAD_DIR.mkdir(exist_ok=True)
    
    while True:
        try:
            # Find any pending JSON payloads that haven't failed
            payloads = list(PAYLOAD_DIR.glob("job_payload_*.json"))
            
            for payload in payloads:
                # Process sequentially to avoid overlap detection
                await process_payload(payload)
                
            # Sleep briefly before polling again (low CPU impact)
            await asyncio.sleep(3)
            
        except KeyboardInterrupt:
            print("\n[MAC NODE] Shutting down execution node gracefully...")
            break
        except Exception as e:
            print(f"[MAC NODE] Poller error: {e}")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(poll_payload_directory())

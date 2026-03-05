import asyncio
import os
import sys
from queue_manager import JobQueue
from omni_scout import run_scout
from apply_agent import run_apply, load_knowledge_base, init_gemini

async def main():
    print("🚀 Starting OpenClaw Orchestrator (Gateway Brain Node)...")
    queue = JobQueue()
    
    # [ROBUSTNESS]: Prevent execution if API keys are missing
    if not os.getenv("GEMINI_API_KEY") and not os.getenv("KEYWORDSAI_API_KEY"):
        print("[BRIDGE] 🚨 CRITICAL ERROR: No LLM API key configured in .env.")
        print("[BRIDGE] You must provide GEMINI_API_KEY (or KEYWORDSAI_API_KEY) to proceed.")
        sys.exit(1)
        
    try:
        await asyncio.sleep(2)
        print("\n[BRIDGE] Booting Master Orchestrator...")
        
        # Load KB & Init Gemini once for the whole run
        kb = load_knowledge_base()
        client = init_gemini()
        
        print("[BRIDGE] Launching Continuous Background Pipeline...")
        
        while True:
            try:
                print(f"\n[{'='*60}]\n[BRIDGE] Phase 1: Scouting New Roles\n")
                await run_scout(queue)
                
                print(f"\n[{'='*60}]\n[BRIDGE] Phase 2: Processing Backlog & Generating Payloads\n")
                await run_apply(queue, client, kb)
                
                print("\n[BRIDGE] Full cycle complete. System resting for 30 minutes to emulate human pacing...\n")
                await asyncio.sleep(1800)  # Sleep 30 mins between major indexing sweeps
                
            except Exception as e:
                error_msg = str(e)
                print(f"\n[BRIDGE] ERROR during cycle: {error_msg}")
                    
                print(f"[BRIDGE] Recovering in 5 minutes before retry...\n")
                await asyncio.sleep(300)  # Wait 5 minutes before retrying
                continue
            
    finally:
        print("\n🏁 Fully Automated Cycle Terminated.")

if __name__ == "__main__":
    asyncio.run(main())

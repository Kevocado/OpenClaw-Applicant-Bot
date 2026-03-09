import asyncio
import os
import sys
from queue_manager import JobQueue
from omni_scout import run_scout
from apply_agent import run_apply, load_knowledge_base

async def main():
    print("🚀 Starting OpenClaw Orchestrator (Gateway Brain Node)...")
    queue = JobQueue()
        
    try:
        await asyncio.sleep(2)
        print("\n[BRIDGE] Booting Master Orchestrator...")
        
        # Load KB once for the whole run. No Gemini initialization since Ollama is used.
        kb = load_knowledge_base()
        
        print("[BRIDGE] Launching Continuous Background Pipeline...")
        
        while True:
            try:
                print(f"\n[{'='*60}]\n[BRIDGE] Phase 1: Scouting New Roles\n")
                await run_scout(queue)
                
                print(f"\n[{'='*60}]\n[BRIDGE] Phase 2: Processing Backlog & Generating Payloads\n")
                await run_apply(queue, kb)
                
                print("\n[BRIDGE] Full cycle complete. System resting for 30 minutes to emulate human pacing...\n")
                await asyncio.sleep(1800) 
                
            except Exception as e:
                error_msg = str(e)
                print(f"\n[BRIDGE] ERROR during cycle: {error_msg}")
                    
                print(f"[BRIDGE] Recovering in 5 minutes before retry...\n")
                await asyncio.sleep(300) 
                continue
            
    finally:
        print("\n🏁 Fully Automated Cycle Terminated.")

if __name__ == "__main__":
    asyncio.run(main())

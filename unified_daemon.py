import asyncio
import os
import signal
import sys

from queue_manager import JobQueue
from omni_scout import run_scout
from apply_agent import run_apply, load_knowledge_base
from telegram_bot import send_startup_message
from clawd_master_bot import run_clawd_bot

# Shared state dict passed to both orchestrator and control bot
daemon_status = {"phase": "Initializing"}

async def start_orchestrator(pause_event: asyncio.Event):
    print("\n[DAEMON] Booting Master Orchestrator...")
    queue = JobQueue()
    kb = load_knowledge_base()
    
    print("[DAEMON] Launching Continuous Background Pipeline...")
    
    while True:
        # ── Pause Check ──────────────────────────────────────────────────────
        if not pause_event.is_set():
            daemon_status["phase"] = "Paused ⏸️"
            print("\n[DAEMON] ⏸️  Paused via ClawdMasterBot. Waiting for /resume...")
            await pause_event.wait()
            print("[DAEMON] ▶️  Resumed.")

        try:
            daemon_status["phase"] = "🔍 Scouting"
            print(f"\n[{'='*60}]\n[DAEMON] Phase 1: Scouting New Roles\n")
            await run_scout(queue)
            
            daemon_status["phase"] = "📋 Applying"
            print(f"\n[{'='*60}]\n[DAEMON] Phase 2: Processing Backlog & Generating Payloads\n")
            await run_apply(queue, kb)
            
            daemon_status["phase"] = "😴 Sleeping (30 min)"
            print("\n[DAEMON] Full cycle complete. System resting for 30 minutes...\n")
            await asyncio.sleep(1800)
            
        except asyncio.CancelledError:
            print("\n[DAEMON] Orchestrator loop cancelled.")
            break
        except Exception as e:
            daemon_status["phase"] = f"⚠️ Error — retrying in 5m"
            print(f"\n[DAEMON] ERROR during cycle: {str(e)}")
            print(f"[DAEMON] Recovering in 5 minutes before retry...\n")
            await asyncio.sleep(300)

async def unified_main():
    print("🚀 Starting Unified OpenClaw Daemon (Single Process)...")

    # Send startup ping via the alert bot
    send_startup_message()

    # Shared pause event — set means running, cleared means paused
    pause_event = asyncio.Event()
    pause_event.set()  # Start in running state

    stop_event = asyncio.Event()

    def handle_sigint():
        print("\n🛑 Shutting down daemon...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    if sys.platform != "win32":
        try:
            loop.add_signal_handler(signal.SIGINT, handle_sigint)
            loop.add_signal_handler(signal.SIGTERM, handle_sigint)
        except NotImplementedError:
            pass

    orchestrator_task = asyncio.create_task(start_orchestrator(pause_event))
    clawd_task = asyncio.create_task(run_clawd_bot(pause_event, daemon_status))

    try:
        done, pending = await asyncio.wait(
            [orchestrator_task, clawd_task, asyncio.create_task(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
    except asyncio.CancelledError:
        pass
    finally:
        orchestrator_task.cancel()
        clawd_task.cancel()
        try:
            await asyncio.gather(orchestrator_task, clawd_task, return_exceptions=True)
        except Exception:
            pass
        print("✅ Shutdown complete.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(unified_main())
    except KeyboardInterrupt:
        pass

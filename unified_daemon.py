import asyncio
import os
import signal
import sys

from queue_manager import JobQueue
from omni_scout import run_scout
from apply_agent import run_apply, load_knowledge_base
from telegram_bot import init_app

async def start_orchestrator():
    print("\n[DAEMON] Booting Master Orchestrator...")
    queue = JobQueue()
    kb = load_knowledge_base()
    
    print("[DAEMON] Launching Continuous Background Pipeline...")
    
    while True:
        try:
            print(f"\n[{'='*60}]\n[DAEMON] Phase 1: Scouting New Roles\n")
            await run_scout(queue)
            
            print(f"\n[{'='*60}]\n[DAEMON] Phase 2: Processing Backlog & Generating Payloads\n")
            await run_apply(queue, kb)
            
            print("\n[DAEMON] Full cycle complete. System resting for 30 minutes to emulate human pacing...\n")
            await asyncio.sleep(1800)
            
        except asyncio.CancelledError:
            print("\n[DAEMON] Orchestrator loop cancelled.")
            break
        except Exception as e:
            print(f"\n[DAEMON] ERROR during cycle: {str(e)}")
            print(f"[DAEMON] Recovering in 5 minutes before retry...\n")
            await asyncio.sleep(300)

async def unified_main():
    print("🚀 Starting Unified OpenClaw Daemon (Single Process)...")

    # Start the scraping/evaluating loop natively
    orchestrator_task = asyncio.create_task(start_orchestrator())

    # Start the Telegram Bot background task
    app = init_app()
    await app.initialize()
    await app.start()
    
    # Run bot polling in the background without blocking the main thread
    telegram_task = asyncio.create_task(app.updater.start_polling())
    
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
            
    try:
        await asyncio.gather(orchestrator_task, stop_event.wait())
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        
        orchestrator_task.cancel()
        print("✅ Shutdown complete.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(unified_main())
    except KeyboardInterrupt:
        pass

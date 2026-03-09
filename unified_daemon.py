import asyncio
import os
import signal
import sys

from telegram_bot import main as start_telegram_bot
from auto_bridge import main as start_auto_bridge

async def unified_main():
    print("🚀 Starting Unified OpenClaw Daemon (Single Process)...")

    # Start the scraping/evaluating loop from auto_bridge
    # We must ensure start_auto_bridge correctly awaits internally.
    bridge_task = asyncio.create_task(start_auto_bridge())

    # Start the Telegram Bot background task.
    # We invoke telegram_bot in a non-blocking asyncio manner
    # Because telegram's `run_polling()` is blocking, we need to adapt it.
    
    # We will refactor telegram_bot's main to return an initialized application.
    from telegram_bot import init_app
    app = init_app()

    await app.initialize()
    await app.start()
    
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
        await asyncio.gather(bridge_task, stop_event.wait())
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        
        bridge_task.cancel()
        print("✅ Shutdown complete.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(unified_main())
    except KeyboardInterrupt:
        pass

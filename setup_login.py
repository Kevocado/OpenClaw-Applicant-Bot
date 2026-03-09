import os
import asyncio
from playwright.async_api import async_playwright

async def main():
    USER_DATA_DIR = os.path.abspath("./bot_session")
    
    print("🚀 Launching OpenClaw setup browser...")
    print("📁 Using profile directory:", USER_DATA_DIR)
    print("⏳ Please log into LinkedIn, Google, Handshake, etc.")
    print("🛑 Close the browser window when you are finished.")
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"]
        )
        
        # Open LinkedIn as a convenience
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.linkedin.com/login")
        
        # Wait until the browser is closed manually
        while len(context.pages) > 0:
            await asyncio.sleep(1)
            
    print("✅ Session saved successfully. You can now close this script and run mac_node_runner.py")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested")

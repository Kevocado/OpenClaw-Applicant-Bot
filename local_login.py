import asyncio
import os
import nodriver as uc

async def main():
    print("🚀 Launching Isolated ClawdBot Profile...")
    print("Please log into LinkedIn, Workday, and Handshake in the browser window that appears.")
    print("Once you are logged in, just close the terminal or press Ctrl+C.")
    
    # Use the isolated project directory
    user_data_dir = "/Users/sigey/Documents/Projects/OpenClaw Resume Bot/user_data_dir"
    os.makedirs(user_data_dir, exist_ok=True)
    
    browser = await uc.start(
        headless=False,
        user_data_dir=user_data_dir,
        no_sandbox=True,
        browser_args=[
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--enforce-webrtc-ip-handling-policy=default_public_interface_only'
        ]
    )
    
    page = await browser.get("https://www.linkedin.com/login")
    
    # Keep the browser open for 15 minutes to allow manual login
    await asyncio.sleep(900)

if __name__ == '__main__':
    try:
        uc.loop().run_until_complete(main())
    except KeyboardInterrupt:
        print("\nSession saved. Exiting...")

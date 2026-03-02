import nodriver as uc
import nodriver.cdp.network as network
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    li_at_cookie = os.getenv("LINKEDIN_LI_AT")
    
    if not li_at_cookie:
        print("❌ Error: LINKEDIN_LI_AT not found in .env")
        return

    print("Launching browser and injecting the Golden Key...")
    # Launching a fresh profile
    browser = await uc.start(headless=False, browser_args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
    
    # 1. Navigate to a safe LinkedIn page to establish the domain context
    page = await browser.get("https://www.linkedin.com/robots.txt")
    
    # 2. Inject the HttpOnly authentication cookie directly into the network
    await page.send(network.set_cookie(
        name="li_at",
        value=li_at_cookie,
        domain=".linkedin.com",
        path="/",
        secure=True,
        http_only=True
    ))
    
    print("Cookie injected. Navigating to feed...")
    
    # 3. Go to the feed. You should be instantly logged in.
    await page.get("https://www.linkedin.com/feed/")
    await asyncio.sleep(5)
    
    await page.save_screenshot("cookie_success.png")
    print("✅ Screenshot saved as 'cookie_success.png'")
    
    browser.stop()

if __name__ == "__main__":
    asyncio.run(main())

import nodriver as uc
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    base_path = os.path.dirname(os.path.abspath(__file__))
    profile_path = os.path.join(base_path, "user_data_dir")
    
    # Start browser and go to login
    browser = await uc.start(
        user_data_dir=profile_path, 
        headless=False, 
        no_sandbox=True,
        browser_args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
    )
    page = await browser.get("https://www.linkedin.com/login")
    await asyncio.sleep(5)
    
    # 1. Grab the CORRECT variables from your .env
    li_user = os.getenv("N8N_BASIC_AUTH_USER")
    li_pass = os.getenv("Linkedin_password")
    
    if not li_user or not li_pass:
        print("❌ ERROR: Could not find N8N_BASIC_AUTH_USER or Linkedin_password in .env")
        return

    email_input = await page.select('input[id="username"]')
    await email_input.send_keys(li_user)
    
    password_input = await page.select('input[id="password"]')
    await password_input.send_keys(li_pass)
    
    # Click Sign In
    button = await page.select('button[type="submit"]')
    await button.click()
    
    print("Sign-in clicked. Waiting 20 seconds for redirect/2FA...")
    await asyncio.sleep(20)
    
    await page.save_screenshot("login_attempt_result.png")
    print("Screenshot saved as 'login_attempt_result.png'")
    
    browser.stop()

if __name__ == "__main__":
    asyncio.run(main())

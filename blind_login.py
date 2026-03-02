import nodriver as uc
import asyncio
import os

async def main():
    base_path = os.path.dirname(os.path.abspath(__file__))
    profile_path = os.path.join(base_path, "user_data_dir")
    
    # Start browser and go to login
    browser = await uc.start(user_data_dir=profile_path, headless=False, browser_args=["--no-sandbox"])
    page = await browser.get("https://www.linkedin.com/login")
    await asyncio.sleep(5)
    
    # STEP 1: Enter Credentials (REPLACE THESE)
    email_input = await page.select('input[id="username"]')
    await email_input.send_keys("YOUR_LINKEDIN_EMAIL")
    
    password_input = await page.select('input[id="password"]')
    await password_input.send_keys("YOUR_LINKEDIN_PASSWORD")
    
    # Click Sign In
    button = await page.select('button[type="submit"]')
    await button.click()
    
    # STEP 2: Wait for potential 2FA/Security Code
    print("Sent login. Waiting 30 seconds for 2FA screen...")
    await asyncio.sleep(30)
    await page.save_screenshot("login_step_2.png")
    
    browser.stop()

if __name__ == "__main__":
    asyncio.run(main())

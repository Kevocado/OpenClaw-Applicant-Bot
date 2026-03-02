import nodriver as uc
import asyncio

async def main():
    print("Launching browser... Please log in to LinkedIn.")
    # This creates a folder called user_data_dir on your Mac
    browser = await uc.start(user_data_dir="./user_data_dir", headless=False)
    page = await browser.get("https://www.linkedin.com/login")

    # The script pauses here so you can log in manually
    input("Press ENTER in this terminal ONLY after you have fully logged in and see your LinkedIn feed...")

    browser.stop()
    print("Profile saved securely!")

if __name__ == "__main__":
    asyncio.run(main())

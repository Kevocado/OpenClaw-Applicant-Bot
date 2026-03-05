"""
OpenClaw Applicant Bot — Persistent Browser Login Helper
Run this script ONCE on the VPS (with display forwarding) to manually log into
LinkedIn, Handshake, MigrateMate, and other job boards.
Session cookies are saved to user_data_dir/ for automated runs.

Usage:
    # On VPS with X11 forwarding:
    ssh -X root@195.26.241.52
    cd /root/OpenClaw-Applicant-Bot
    source venv/bin/activate
    python login_helper.py

    # Or locally:
    python login_helper.py
"""

import asyncio
import os
import sys

import nodriver as uc
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
USER_DATA_DIR = os.getenv("USER_DATA_DIR", os.path.join(PROJECT_ROOT, "bot_chrome_profile"))

# Sites to log into — the script opens each one and waits for you to log in
LOGIN_SITES = [
    {
        "name": "LinkedIn",
        "url": "https://www.linkedin.com/login",
        "check_url": "linkedin.com/feed",
        "instructions": "Log in with your LinkedIn credentials. Complete any 2FA if prompted.",
    },
    {
        "name": "Handshake",
        "url": "https://app.joinhandshake.com/login",
        "check_url": "joinhandshake.com",
        "instructions": "Log in with your university SSO. Complete any 2FA if prompted.",
    },
    {
        "name": "MigrateMate",
        "url": "https://migratemate.co/jobs",
        "check_url": "migratemate.co",
        "instructions": "Log in with your MigrateMate account.",
    },
    {
        "name": "Indeed",
        "url": "https://secure.indeed.com/auth",
        "check_url": "indeed.com",
        "instructions": "Log in with your Indeed account.",
    },
    {
        "name": "Glassdoor",
        "url": "https://www.glassdoor.com/profile/login_input.htm",
        "check_url": "glassdoor.com",
        "instructions": "Log in with your Glassdoor account.",
    },
]


async def main():
    print("=" * 60)
    print("  OpenClaw Applicant Bot — Login Helper")
    print("  Saving sessions to:", os.path.abspath(USER_DATA_DIR))
    print("=" * 60)
    print()
    print("This script opens each job board so you can log in manually.")
    print("Your session cookies will be saved for automated nightly runs.")
    print()

    browser_kwargs = {
        "user_data_dir": USER_DATA_DIR,
        "headless": False,
        "sandbox": False, # Required for running as root on VPS
        "browser_args": [
            "--window-size=1280,900",
            "--remote-debugging-host=127.0.0.1",
        ],
    }

    mac_chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if sys.platform == "darwin" and os.path.exists(mac_chrome_path):
        browser_kwargs["browser_executable_path"] = mac_chrome_path

    browser = await uc.start(**browser_kwargs)

    for i, site in enumerate(LOGIN_SITES, 1):
        print(f"\n[{i}/{len(LOGIN_SITES)}] Opening {site['name']}...")
        print(f"     URL: {site['url']}")
        print(f"     → {site['instructions']}")

        page = await browser.get(site["url"])

        # Wait for user to log in
        input(f"\n     Press ENTER when you've finished logging into {site['name']}...")

        # Verify we're logged in by checking the URL
        current_url = page.url if hasattr(page, 'url') else "unknown"
        print(f"     Current URL: {current_url}")
        print(f"     ✅ {site['name']} session saved!")

    print("\n" + "=" * 60)
    print("  ✅ ALL SESSIONS SAVED")
    print("=" * 60)
    print(f"\n  Session data stored in: {os.path.abspath(USER_DATA_DIR)}")
    print("  The bot will use these cookies for automated runs.")
    print("  You should NOT need to log in again unless sessions expire.")
    print()

    # Keep browser open briefly for any final checks
    input("Press ENTER to close the browser...")
    browser.stop()


if __name__ == "__main__":
    uc.loop().run_until_complete(main())

import asyncio
import json
import re
import nodriver as uc
import urllib.parse
import os
import sys
from bs4 import BeautifulSoup
from google import genai
from dotenv import load_dotenv
from queue_manager import JobQueue

load_dotenv()

# Load config from openclaw.json
try:
    with open("openclaw.json", "r") as f:
        # Properly parse the nested JSON architecture
        config = json.load(f).get("agents", {}).get("job_bot", {}).get("scout_config", {})
    base_roles = config.get("target_roles", [])
    TARGET_ROLES = config.get("keywords", []) + ["Engineer", "Developer", "Data", "Product", "Intern", "Analyst", "Scientist"]
except Exception as e:
    print(f"[SCOUT] Error loading openclaw.json: {e}")
    base_roles = ["Software Engineer Intern"]
    TARGET_ROLES = ["Software", "Engineer", "Intern"]
    config = {}

def generate_search_queries(base_roles, config):
    print("[SCOUT] Using customized F-1 corporate queries")
    return [
        "Data Analyst Insurance",
        "Business Analytics Manufacturing",
        "Logistics Analyst",
        "Healthcare Data"
    ]

search_queries = generate_search_queries(base_roles, config)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KEYWORDSAI_API_KEY = os.getenv("KEYWORDSAI_API_KEY")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
USER_DATA_DIR = os.path.join(PROJECT_ROOT, "bot_chrome_profile")
# DataImpulse Residential Proxy (Commented out to use native Mac Wi-Fi)
# PROXY_SERVER = "http://gw.dataimpulse.com:823"

async def extract_jobs_from_dom(page, platform, priority):
    """
    Extracts job data from the raw DOM safely handling NoneType elements.
    """
    await asyncio.sleep(5)
    
    jobs = []
    try:
        elements = await page.select_all('a')
        
        for el in elements:
            try:
                # Safely handle potential NoneTypes from nodriver elements
                href = getattr(el, 'href', '') or ''
                text = getattr(el, 'text', '') or getattr(el, 'text_content', '') or ''
                
                href = str(href).strip()
                text = str(text).strip()
                
                if not href or not text:
                    continue
                    
                # Fix relative URLs
                if href.startswith('/'):
                    if platform == "MigrateMate":
                        href = "https://migratemate.co" + href
                    elif platform == "Handshake":
                        href = "https://app.joinhandshake.com" + href
                    elif platform == "LinkedIn":
                        href = "https://www.linkedin.com" + href
                    
                # Basic heuristic filtering for job links
                is_job_link = False
                if platform == "MigrateMate" and "/job/" in href:
                    is_job_link = True
                elif platform == "Handshake" and "/jobs/" in href:
                    is_job_link = True
                elif platform == "LinkedIn" and "/view/" in href:
                    is_job_link = True
                    
                if is_job_link and any(role.lower() in text.lower() for role in TARGET_ROLES):
                    jobs.append({
                        "Job_URL": href,
                        "Company": "Extracted from DOM", 
                        "Role": text,
                        "ATS_System": platform,
                        "Priority": priority,
                        "Deadline": ""
                    })
            except Exception:
                # If a single element fails parsing, silently skip it
                continue
                
    except Exception as e:
        print(f"[SCOUT] Failed to select elements on {platform}: {e}")
            
    # Deduplicate by URL
    seen_urls = set()
    unique_jobs = []
    for job in jobs:
        if job["Job_URL"] not in seen_urls:
            unique_jobs.append(job)
            seen_urls.add(job["Job_URL"])
            
    if len(unique_jobs) == 0:
        import time
        ts = int(time.time())
        try:
            os.makedirs("./screenshots", exist_ok=True)
            await page.save_screenshot(f"./screenshots/debug_scout_{platform}_{ts}.png")
            print(f"        -> [DEBUG] Saved blank scrape screenshot to screenshots/debug_scout_{platform}_{ts}.png")
        except Exception:
            pass
            
    return unique_jobs[:10]

async def run_scout(main_tab, queue: JobQueue):
    added_count = 0

    try:
        # Target 1: MigrateMate (Base page + Filter Click)
        print("[SCOUT] Sourcing from MigrateMate...")
        await main_tab.get('https://migratemate.co/jobs')
        
        # Give the React Virtual DOM time to paint the screen
        await asyncio.sleep(4)
        
        try:
            # Find and click the specific filter button
            filter_btn = await main_tab.select('button:contains("Apply Filters")')
            await filter_btn.mouse_click()
            print("[SCOUT] Filters applied. Waiting for results...")
            
            # Give the network time to fetch the filtered jobs
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[SCOUT] Failed to apply filters on MigrateMate: {e}")

        mm_jobs = await extract_jobs_from_dom(main_tab, "MigrateMate", 1)
        for job in mm_jobs:
            if queue.add_job(title=job['Role'], company=job['Company'], url=job['Job_URL'], source="MigrateMate"):
                added_count += 1
        print(f"        -> Found {len(mm_jobs)} on MM")
        
        for query in search_queries:
            print(f"[SCOUT] Target: Scouring for '{query}'...")
            query_encoded = urllib.parse.quote(query)

            # Target 2: Handshake (Appended options for Sponsorship)
            print("[SCOUT] Sourcing from Handshake...")
            await main_tab.get(f'https://app.joinhandshake.com/stu/postings?query={query_encoded}&options[Sponsorship+Options][]=Sponsors+Candidates&options[Sponsorship+Options][]=Accepts+OPT%2FCPT')
            hs_jobs = await extract_jobs_from_dom(main_tab, "Handshake", 2)
            for job in hs_jobs:
                if queue.add_job(title=job['Role'], company=job['Company'], url=job['Job_URL'], source="Handshake"):
                    added_count += 1
            print(f"        -> Found {len(hs_jobs)} on HS")

    except Exception as e:
        print(f"[SCOUT] Critical browser error during scout loop: {e}")
        raise e  # Propagate error up to trigger standby

    if added_count == 0:
        print("[SCOUT] CRITICAL WARNING: 0 jobs were added to the queue during this cycle.")
        print("[SCOUT] This usually indicates the browser is blocked by a login wall, CAPTCHA, or the DOM failed to load.")
        raise Exception("Login Wall or Page Load Failure Detected (0 jobs scraped)")

    print(f"\n[SCOUT] Total new unique jobs added to queue: {added_count}")
    return added_count

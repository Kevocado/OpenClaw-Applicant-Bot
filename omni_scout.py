import asyncio
import json
import re
import nodriver as uc
import urllib.parse
import os
import sys
import nodriver as uc
import urllib.parse
import os
import sys
from bs4 import BeautifulSoup
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Load config from openclaw.json
try:
    with open("openclaw.json", "r") as f:
        config = json.load(f).get("scout_config", {})
    base_roles = config.get("target_roles", [])
    TARGET_ROLES = config.get("keywords", []) + ["Engineer", "Developer", "Data", "Product", "Intern"]
except Exception as e:
    print(f"[SCOUT] Error loading openclaw.json: {e}")
    base_roles = ["Software Engineer Intern"]
    TARGET_ROLES = ["Software", "Engineer", "Intern"]
    config = {}

def generate_search_queries(base_roles, config):
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return base_roles[:3]
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"response_mime_type": "application/json", "temperature": 0.7})
        
        prompt = f"Given these target roles: {base_roles} and keywords: {config.get('keywords', [])}. Generate exactly 5 diverse, highly effective job search query strings that capture semantic variations (e.g. abbreviations, different titles, specific keywords) for job boards. Return ONLY a JSON array of strings. Example: ['Software Engineer Intern Summer 2026', 'SWE Intern OPT', 'Data Scientist Visa Sponsorship']"
        
        response = model.generate_content(prompt)
        queries = json.loads(response.text)
        if isinstance(queries, list) and len(queries) > 0:
            return queries[:5]
    except Exception as e:
        print(f"[SCOUT] Failed to generate AI queries: {e}")
    return base_roles

search_queries = generate_search_queries(base_roles, config)

PROXY_SERVER = "http://gw.dataimpulse.com:823"

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

async def main():
    has_display = os.getenv("DISPLAY") is not None or sys.platform == "darwin"
    headless_mode = not has_display
    print(f"[SCOUT] Initializing Omni-Scout Browser (headless={headless_mode})...")
    browser = await uc.start(
        headless=headless_mode,
        no_sandbox=True,
        browser_args=[
            f'--proxy-server={PROXY_SERVER}',
            '--no-sandbox', 
            '--disable-setuid-sandbox', 
            '--disable-dev-shm-usage'
        ]
    )
    
    all_extracted_jobs = []

    try:
        for query in search_queries:
            print(f"[SCOUT] Target: Scouring for '{query}'...")
            query_encoded = urllib.parse.quote(query)

            # Target 1: MigrateMate 
            print("[SCOUT] Checking for MigrateMate Session...")
            mm_cookie = os.getenv("MIGRATEMATE_COOKIE")
            if mm_cookie:
                page_mm = await browser.get("https://migratemate.co/robots.txt")
                await asyncio.sleep(2)
                await page_mm.send(uc.cdp.network.set_cookie(
                    name="session", # typical name, user can verify
                    value=mm_cookie,
                    domain=".migratemate.co",
                    path="/",
                    secure=True,
                    http_only=True
                ))
            
            page_mm = await browser.get(f'https://migratemate.co/jobs?query={query_encoded}')
            mm_jobs = await extract_jobs_from_dom(page_mm, "MigrateMate", 1)
            all_extracted_jobs.extend(mm_jobs)
            print(f"        -> Found {len(mm_jobs)} on MM")

            # Target 2: Handshake
            print("[SCOUT] Checking for Handshake Session...")
            hs_cookie = os.getenv("HANDSHAKE_COOKIE")
            if hs_cookie:
                page_hs = await browser.get("https://app.joinhandshake.com/robots.txt")
                await asyncio.sleep(2)
                await page_hs.send(uc.cdp.network.set_cookie(
                    name="_handshake_session", # typical name, user can verify
                    value=hs_cookie,
                    domain="app.joinhandshake.com",
                    path="/",
                    secure=True,
                    http_only=True
                ))

            page_hs = await browser.get(f'https://app.joinhandshake.com/stu/postings?query={query_encoded}&employer_preferences_sponsor_internship=true')
            hs_jobs = await extract_jobs_from_dom(page_hs, "Handshake", 2)
            all_extracted_jobs.extend(hs_jobs)
            print(f"        -> Found {len(hs_jobs)} on HS")

            # Target 3: LinkedIn (No Session Cookie = Public Safe Scraping)
            print("[SCOUT] Searching LinkedIn...")

            page_li = await browser.get(f'https://www.linkedin.com/jobs/search/?keywords={query_encoded}')
            li_jobs = await extract_jobs_from_dom(page_li, "LinkedIn", 3)
            all_extracted_jobs.extend(li_jobs)
            print(f"        -> Found {len(li_jobs)} on LI")

    except Exception as e:
        print(f"[SCOUT] Critical browser error: {e}")
    
    finally:
        browser.stop()

    # Output strictly as JSON for n8n Parsing
    print("\nSCOUT_JSON::")
    print(json.dumps(all_extracted_jobs, indent=2))

if __name__ == '__main__':
    uc.loop().run_until_complete(main())

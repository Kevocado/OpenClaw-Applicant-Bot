import asyncio
import json
import re
import nodriver as uc

import urllib.parse

import os

# Load config from openclaw.json
try:
    with open("openclaw.json", "r") as f:
        config = json.load(f).get("scout_config", {})
    search_queries = config.get("target_roles", [])
    TARGET_ROLES = config.get("keywords", []) + ["Engineer", "Developer", "Data", "Product", "Intern"]
except Exception as e:
    print(f"[SCOUT] Error loading openclaw.json: {e}")
    search_queries = ["Software Engineer Intern"]
    TARGET_ROLES = ["Software", "Engineer", "Intern"]

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
            
    return unique_jobs[:10]

async def main():
    print("[SCOUT] Initializing Omni-Scout Browser...")
    browser = await uc.start(
        headless=True,
        user_data_dir="./user_data_dir",
        browser_args=[
            f'--proxy-server={PROXY_SERVER}',
            '--no-sandbox',
            '--disable-dev-shm-usage'
        ]
    )
    
    all_extracted_jobs = []

    try:
        for query in search_queries:
            print(f"[SCOUT] Target: Scouring for '{query}'...")
            query_encoded = urllib.parse.quote(query)

            # Target 1: MigrateMate 
            page_mm = await browser.get(f'https://migratemate.com/jobs?query={query_encoded}&visa=cpt')
            mm_jobs = await extract_jobs_from_dom(page_mm, "MigrateMate", 1)
            all_extracted_jobs.extend(mm_jobs)
            print(f"        -> Found {len(mm_jobs)} on MM")

            # Target 2: Handshake
            page_hs = await browser.get(f'https://app.joinhandshake.com/stu/jobs?query={query_encoded}&employer_preferences_sponsor_internship=true')
            hs_jobs = await extract_jobs_from_dom(page_hs, "Handshake", 2)
            all_extracted_jobs.extend(hs_jobs)
            print(f"        -> Found {len(hs_jobs)} on HS")

            # Target 3: LinkedIn
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

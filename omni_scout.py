import asyncio
import json
import re
import nodriver as uc

PROXY_SERVER = "http://gw.dataimpulse.com:823"
TARGET_ROLES = ["Data Analyst", "Business Analyst"]
SEARCH_TERM = "Data Analyst Summer 2026"

async def extract_jobs_from_dom(page, platform, priority):
    """
    Skill: regex-vs-llm-structured-text
    Extracts job data from the raw DOM using heuristic matching to bypass dynamic CSS class obfuscation.
    """
    # Wait for dynamic content to load
    await asyncio.sleep(5)
    
    jobs = []
    # This is a generalized DOM extraction pattern. 
    # We look for all links that match standard job posting URL structures.
    elements = await page.select_all('a')
    
    for el in elements:
        href = getattr(el, 'href', '')
        text = getattr(el, 'text_content', '').strip()
        
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
                "Company": "Extracted from DOM", # Placeholder for downstream Gemini refinement
                "Role": text,
                "ATS_System": platform,
                "Priority": priority
            })
            
    # Deduplicate by URL
    seen_urls = set()
    unique_jobs = []
    for job in jobs:
        if job["Job_URL"] not in seen_urls:
            unique_jobs.append(job)
            seen_urls.add(job["Job_URL"])
            
    return unique_jobs[:10] # Return top 10

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
        # ==========================================
        # Priority 1: MigrateMate (CPT/OPT Focused)
        # ==========================================
        print("[SCOUT] Target 1: Scouring MigrateMate...")
        page_mm = await browser.get('https://migratemate.com/jobs?query=Data+Analyst+Summer+2026&visa=cpt')
        mm_jobs = await extract_jobs_from_dom(page_mm, "MigrateMate", 1)
        all_extracted_jobs.extend(mm_jobs)

        # ==========================================
        # Priority 2: Handshake
        # ==========================================
        print("[SCOUT] Target 2: Scouring Handshake...")
        page_hs = await browser.get('https://app.joinhandshake.com/stu/jobs?query=Data+Analyst&employer_preferences_sponsor_internship=true')
        hs_jobs = await extract_jobs_from_dom(page_hs, "Handshake", 2)
        all_extracted_jobs.extend(hs_jobs)

        # ==========================================
        # Priority 3: LinkedIn
        # ==========================================
        print("[SCOUT] Target 3: Scouring LinkedIn...")
        page_li = await browser.get('https://www.linkedin.com/jobs/search/?keywords=Data%20Analyst%20Summer%202026')
        li_jobs = await extract_jobs_from_dom(page_li, "LinkedIn", 3)
        all_extracted_jobs.extend(li_jobs)

    except Exception as e:
        print(f"[SCOUT] Error during extraction: {e}")
    
    finally:
        browser.stop()

    # Output strictly as JSON for n8n Parsing
    print("\nSCOUT_JSON::")
    print(json.dumps(all_extracted_jobs, indent=2))

if __name__ == '__main__':
    uc.loop().run_until_complete(main())

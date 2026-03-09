import asyncio
import json
import re
import urllib.parse
import os
import sys
from google import genai
from dotenv import load_dotenv
from queue_manager import JobQueue
import time
from playwright.async_api import async_playwright

load_dotenv()

# Load config from openclaw.json
try:
    with open("openclaw.json", "r") as f:
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
        "Data Analyst Internship",
        "Business Analytics Intern",
        "Logistics Analyst"
    ]

search_queries = generate_search_queries(base_roles, config)

async def fetch_linkedin_jobs(page, query: str, time_filter: str = "r86400") -> list:
    """
    Scrape LinkedIn public job search. No login required.
    time_filter: "r86400" (past 24h) or "r604800" (past week)
    """
    jobs = []
    
    # LinkedIn public search URL format
    query_encoded = urllib.parse.quote(query)
    url = f"https://www.linkedin.com/jobs/search?keywords={query_encoded}&location=United%20States&f_TPR={time_filter}&position=1&pageNum=0"
    
    try:
        await page.goto(url, timeout=30000)
        # Give LinkedIn time to load the public list
        await asyncio.sleep(5)
        
        # Scroll a bit to load more jobs in the public view
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
        await asyncio.sleep(2)
        
        elements = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('.base-card__full-link, .base-search-card__title')).map(el => {
                let aTag = el.tagName.toLowerCase() === 'a' ? el : el.closest('a');
                if (!aTag) return null;
                
                let card = aTag.closest('.base-search-card');
                let companyEl = card ? card.querySelector('.base-search-card__subtitle') : null;
                
                return {
                    href: aTag.getAttribute('href'),
                    text: aTag.innerText || aTag.textContent,
                    company: companyEl ? (companyEl.innerText || companyEl.textContent) : "Unknown Company"
                };
            }).filter(Boolean);
        }''')
        
        for el in elements:
            try:
                href = (el.get('href') or '').strip()
                title = (el.get('text') or '').strip()
                company = (el.get('company') or 'Unknown').strip()
                
                if not href or not title:
                    continue
                    
                # Strip tracking parameters to get clean Job ID URL
                if '?' in href:
                    href = href.split('?')[0]
                    
                if any(role.lower() in title.lower() for role in TARGET_ROLES):
                    jobs.append({
                        "Job_URL": href,
                        "Company": company, 
                        "Role": title,
                        "ATS_System": "LinkedIn",
                        "Priority": 1,
                        "Deadline": ""
                    })
            except Exception:
                continue
                
    except Exception as e:
        print(f"[SCOUT] Failed to fetch LinkedIn jobs for '{query}': {e}")
            
    # Deduplicate by URL
    seen_urls = set()
    unique_jobs = []
    for job in jobs:
        if job["Job_URL"] not in seen_urls:
            unique_jobs.append(job)
            seen_urls.add(job["Job_URL"])
            
    return unique_jobs[:10]

async def fetch_google_jobs(page, query: str, time_filter: str = "d") -> list:
    """
    Search Google for LinkedIn job postings.
    Uses Google Dorking to target the public job view.
    time_filter: "d" (past 24h) or "w" (past week)
    """
    jobs = []
    
    # 1. Google Dork targeting LinkedIn job pages
    dork_query = f'site:linkedin.com/jobs/view/ "{query}"'
    dork_encoded = urllib.parse.quote(dork_query)
    
    # 2. Google Time Filter
    url = f"https://www.google.com/search?q={dork_encoded}&tbs=qdr:{time_filter}"
    
    try:
        await page.goto(url, timeout=30000)
        await asyncio.sleep(3) # Wait for results
        
        # Scroll to load
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
        
        # Extract hrefs
        elements = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                href: a.getAttribute('href'),
                text: a.innerText || a.textContent
            })).filter(el => el.href.includes('linkedin.com/jobs/view/'));
        }''')
        
        for el in elements:
            try:
                href = (el.get('href') or '').strip()
                title = (el.get('text') or '').strip()
                
                if not href:
                    continue
                    
                # Clean up Google URL redirects if any, and strip tracking
                if 'url?q=' in href:
                    href = href.split('url?q=')[1].split('&')[0]
                    href = urllib.parse.unquote(href)
                    
                if '?' in href:
                    href = href.split('?')[0] # Remove tracking to get clean job ID URL
                    
                # Extract basic company/role if possible from title
                # Google usually formats as "Job Title - Company - LinkedIn"
                parts = title.split(' - ')
                role = parts[0] if len(parts) > 0 else query
                company = parts[1] if len(parts) > 1 else 'Unknown Google Scrape'
                
                jobs.append({
                    "Job_URL": href,
                    "Company": company, 
                    "Role": role,
                    "ATS_System": "LinkedIn via Google",
                    "Priority": 1,
                    "Deadline": ""
                })
            except Exception:
                continue
                
    except Exception as e:
        print(f"[SCOUT] Failed Google Dork search for '{query}': {e}")
            
    # Deduplicate by URL
    seen_urls = set()
    unique_jobs = []
    for job in jobs:
        if job["Job_URL"] not in seen_urls:
            unique_jobs.append(job)
            seen_urls.add(job["Job_URL"])
            
    return unique_jobs[:10]

async def run_scout(queue: JobQueue):    """
    VPS (Brain) Orchestration loop for scouting. Uses headless Playwright.
    """
    added_count = 0

    try:
        async with async_playwright() as p:
            print("[SCOUT] Launching headless Playwright browser...")
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            for query in search_queries:
                # Filter for "Past 1 Week" and "Past 24 Hours" for a wide range of jobs
                # We map the human concept to Google ('w', 'd') and LinkedIn ('r604800', 'r86400')
                time_filters = [
                    {"label": "Past 1 Week", "google": "w", "linkedin": "r604800"},
                    {"label": "Past 24 Hours", "google": "d", "linkedin": "r86400"}
                ]
                
                for t_filter in time_filters:
                    print(f"\\n[SCOUT] Target: Google Dork Search for '{query}' ({t_filter['label']})...")
                    google_jobs = await fetch_google_jobs(page, query, time_filter=t_filter['google'])
                    
                    for job in google_jobs:
                        if queue.add_job(title=job['Role'], company=job['Company'], url=job['Job_URL'], source=f"Google Search ({t_filter['label']})"):
                            added_count += 1
                    print(f"        -> Found {len(google_jobs)} via Google Dork")
                    
                    print(f"[SCOUT] Target: LinkedIn Public Search for '{query}' ({t_filter['label']})...")
                    li_jobs = await fetch_linkedin_jobs(page, query, time_filter=t_filter['linkedin'])
                    
                    for job in li_jobs:
                        if queue.add_job(title=job['Role'], company=job['Company'], url=job['Job_URL'], source=f"LinkedIn Public ({t_filter['label']})"):
                            added_count += 1
                    print(f"        -> Found {len(li_jobs)} on LinkedIn")

            await browser.close()
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\\n[SCOUT] Shutting down gracefully. Queue state is preserved.")
        return added_count
    except Exception as e:
        print(f"[SCOUT] Critical Playwright error during scout loop: {e}")
        raise e

    if added_count == 0:
        print("[SCOUT] WARNING: 0 jobs were added to the queue during this cycle.")

    print(f"\n[SCOUT] Total new unique jobs added to queue: {added_count}")
    return added_count


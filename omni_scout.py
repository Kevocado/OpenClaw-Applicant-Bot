import asyncio
import json
import re
import urllib.parse
import os
import sys
import requests
from bs4 import BeautifulSoup
from google import genai
from dotenv import load_dotenv
from queue_manager import JobQueue
import time

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

# DataImpulse Residential Proxy (Commented out to use native Mac Wi-Fi)
# PROXY_SERVER = "http://gw.dataimpulse.com:823"


def fetch_and_extract_jobs(url: str, platform: str, priority: int) -> list:
    """
    HTTP GET request for lightweight scraping on the VPS (Brain)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    jobs = []
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        elements = soup.find_all('a', href=True)
        
        for el in elements:
            try:
                href = el.get('href', '').strip()
                text = el.get_text(separator=" ", strip=True)
                
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
                continue
                
    except Exception as e:
        print(f"[SCOUT] Failed to HTTP fetch elements on {platform}: {e}")
            
    # Deduplicate by URL
    seen_urls = set()
    unique_jobs = []
    for job in jobs:
        if job["Job_URL"] not in seen_urls:
            unique_jobs.append(job)
            seen_urls.add(job["Job_URL"])
            
    return unique_jobs[:10]


async def run_scout(queue: JobQueue):
    """
    VPS (Brain) Orchestration loop for scouting. No headless browser.
    """
    added_count = 0

    try:
        # Target 1: MigrateMate
        print("[SCOUT] HTTP Fetching MigrateMate...")
        mm_url = "https://migratemate.co/jobs"
        mm_jobs = fetch_and_extract_jobs(mm_url, "MigrateMate", 1)
        for job in mm_jobs:
            if queue.add_job(title=job['Role'], company=job['Company'], url=job['Job_URL'], source="MigrateMate"):
                added_count += 1
        print(f"        -> Found {len(mm_jobs)} on MM")
        
        for query in search_queries:
            time.sleep(2)
            print(f"[SCOUT] Target: HTTP Fetching '{query}'...")
            query_encoded = urllib.parse.quote(query)

            # Target 2: Handshake
            print("[SCOUT] HTTP Fetching Handshake...")
            hs_url = f'https://app.joinhandshake.com/stu/postings?query={query_encoded}&options[Sponsorship+Options][]=Sponsors+Candidates&options[Sponsorship+Options][]=Accepts+OPT%2FCPT'
            hs_jobs = fetch_and_extract_jobs(hs_url, "Handshake", 2)
            
            for job in hs_jobs:
                if queue.add_job(title=job['Role'], company=job['Company'], url=job['Job_URL'], source="Handshake"):
                    added_count += 1
            print(f"        -> Found {len(hs_jobs)} on HS")

    except Exception as e:
        print(f"[SCOUT] Critical HTTP error during scout loop: {e}")
        raise e

    if added_count == 0:
        print("[SCOUT] CRITICAL WARNING: 0 jobs were added to the queue during this cycle.")
        print("[SCOUT] Handshake/MigrateMate might have implemented strict Cloudflare blocks.")

    print(f"\n[SCOUT] Total new unique jobs added to queue: {added_count}")
    return added_count

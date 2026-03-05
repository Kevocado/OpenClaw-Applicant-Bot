import asyncio
import random
import json
import os
import re
import sys
import time
import traceback
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from dotenv import load_dotenv

# ─── Configuration ────────────────────────────────────────────────────────────

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KEYWORDSAI_API_KEY = os.getenv("KEYWORDSAI_API_KEY")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
USER_DATA_DIR = os.path.join(PROJECT_ROOT, "bot_chrome_profile")
SCREENSHOTS_DIR = Path(os.path.join(PROJECT_ROOT, "screenshots"))
PENDING_APPROVALS_FILE = Path("./pending_approvals.json")
KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
# Exit codes for n8n orchestration
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_HIGH_TIER_PAUSED = 2  # Signals n8n to route to Telegram for approval
EXIT_LOW_SCORE = 3         # Signals n8n to auto-reject application
EXIT_FAILED_PRESCREEN = 4  # Signals n8n that the LLM Bouncer rejected it

# DataImpulse Residential Proxy (Removed from defaults to use native Mac Residential Wi-Fi)
# PROXY_SERVER = "http://gw.dataimpulse.com:823"

# High-tier companies that require manual approval
HIGH_TIER_COMPANIES = [
    "mckinsey", "bain", "bcg", "boston consulting",
    "deloitte", "ey", "ernst & young", "ernst and young",
    "kpmg", "pwc", "pricewaterhousecoopers",
    "capital one", "goldman sachs", "jp morgan", "jpmorgan",
    "morgan stanley", "blackrock", "citadel", "jane street",
    "two sigma", "de shaw", "bridgewater",
    "google", "meta", "amazon", "apple", "microsoft",
]

# ─── Knowledge Base Loader ────────────────────────────────────────────────────

def load_knowledge_base() -> dict:
    """Load all knowledge base files into memory."""
    kb = {}
    files = {
        "resume": "honest_resume.md",
        "cover_letter_template": "cover_letter_templates.md",
        "interview_qa": "interview_qa_matrix.md",
        "project_context": "project_context.md",
        "application_rules": "application_rules.json",
    }
    for key, filename in files.items():
        filepath = KNOWLEDGE_BASE_DIR / filename
        if filepath.exists():
            kb[key] = filepath.read_text(encoding="utf-8")
            print(f"[KB] Loaded {filename} ({len(kb[key])} chars)")
        else:
            print(f"[KB] 🚨 CRITICAL ERROR: {filename} not found at {filepath}")
            print("[KB] Cannot proceed without core knowledge base. Exiting.")
            sys.exit(1)
    return kb


# ─── Job Description Sanitization (Prompt Injection Defense) ─────────────────

def sanitize_jd(raw_text: str) -> str:
    """Strip potentially malicious content from scraped job descriptions."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', raw_text)
    # Remove common prompt injection patterns
    injection_patterns = [
        r'ignore\s+(all\s+)?previous\s+instructions',
        r'output\s+your\s+(system\s+)?prompt',
        r'disregard\s+(all\s+)?above',
        r'you\s+are\s+now\s+a',
        r'new\s+instructions?:',
        r'system\s*:\s*',
        r'\[INST\]',
        r'\[/INST\]',
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, '[REDACTED]', text, flags=re.IGNORECASE)
    # Enforce character limit (10k chars max)
    text = text[:10000]
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ─── LLM Bouncer ─────────────────────────────────────────────────────────────

def run_llm_bouncer(jd_text: str, client: genai.Client) -> dict:
    """Fast prescreen to protect API tokens from impossible applications."""
    bouncer_prompt = f"""
    Analyze this Job Description:
    {jd_text}
    
    The applicant is an MSBA student requiring F-1 CPT/OPT sponsorship for Summer 2026. 
    The absolute minimum acceptable salary is $60,000.
    
    Perform a strict gatekeeping check based on these three rules:
    
    1. SALARY: If the text explicitly states a salary below $60,000, reject it. If the salary is NOT explicitly listed, assume it pays well and DO NOT reject it for this reason.
    2. VISA/SPONSORSHIP & INDUSTRY: STRICTLY REJECT startups, boutique firms, or descriptions mentioning "US Citizenship", "Permanent Residency/Green Card required" or "We do not provide sponsorship". 
    3. TARGET SECTORS: Automatically APPROVE and prioritize mid-to-large corporations in the logistics, finance, and healthcare sectors.
    
    Return ONLY valid JSON with no markdown formatting:
    {{
        "proceed": true or false,
        "rejection_reason": "Provide a 1-sentence reason only if proceed is false. Otherwise leave blank."
    }}
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=bouncer_prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
        )
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except json.JSONDecodeError as e:
        print(f"[BOUNCER] JSON parse error: {e}. Defaulting to REJECT (safe fail).")
        return {"proceed": False, "rejection_reason": "Bouncer parse error — malformed LLM response"}
    except Exception as e:
        print(f"[BOUNCER] Network/API error running prescreen: {e}")
        # On network error, default to PROCEED (retry later) rather than blocking
        return {"proceed": True, "rejection_reason": ""}


# ─── Gemini Integration ──────────────────────────────────────────────────────

def init_gemini() -> genai.Client:
    """Initialize the LLM client, routing through Respan proxy if available."""
    if KEYWORDSAI_API_KEY:
        client = genai.Client(
            api_key=KEYWORDSAI_API_KEY,
            http_options={
                "base_url": "https://api.respan.ai/api/google/gemini",
            },
        )
        print("[LLM] Client initialized via Respan proxy (observability enabled)")
        return client

    if not GEMINI_API_KEY:
        print("[ERROR] Neither KEYWORDSAI_API_KEY nor GEMINI_API_KEY is set")
        sys.exit(EXIT_FAILURE)
    client = genai.Client(api_key=GEMINI_API_KEY)
    print("[LLM] Client initialized (direct Gemini — no observability)")
    return client


def analyze_job(client: genai.Client, job_url: str, job_description: str, knowledge_base: dict) -> dict:
    """
    Analyze a job posting using Gemini.
    Returns strict JSON with analysis, cover letter, QA answers, and metadata.
    """
    system_prompt = f"""You are an expert career agent for Kevin Sigey. You have access to his EXACT resume, 
cover letter templates, interview Q&A matrix, and project context below. 
You must STRICTLY adhere to these documents.
Do NOT invent skills, experiences, or metrics not present in these files.

=== RESUME ===
{knowledge_base['resume']}

=== COVER LETTER TEMPLATES ===
{knowledge_base['cover_letter_template']}

=== INTERVIEW Q&A MATRIX ===
{knowledge_base['interview_qa']}

=== PROJECT CONTEXT (Match projects to JD keywords) ===
{knowledge_base.get('project_context', '')}

=== INSTRUCTIONS ===
Analyze the following job description and return a JSON object with these exact keys:

1. "Company" (string): The company name extracted from the job description.

2. "Role" (string): The job title extracted from the job description.

3. "ATS_System" (string): Identify the ATS platform from the URL or page structure.
   One of: "Workday", "iCIMS", "Greenhouse", "Lever", "Taleo", "BambooHR", "LinkedIn", "Unknown".

4. "visa_eligible" (boolean): 
   - false if the JD explicitly says "U.S. Citizens only", "U.S. Citizenship required", 
     "No sponsorship", "Must be authorized to work without sponsorship", or similar.
   - true if OPT/CPT is accepted, or if no visa restriction is mentioned.

5. "Visa_Required" (string): "Yes" or "No" — whether the JD explicitly requires visa sponsorship.
   Use the CPT/OPT Q&A Matrix logic from the interview matrix.

6. "company_tier" (string, either "High" or "Standard"):
   - "High" if the company is a top consulting firm (McKinsey, BCG, Bain, Deloitte, EY, KPMG, PwC),
     a top finance firm (Goldman Sachs, JP Morgan, Morgan Stanley, Capital One, BlackRock, Citadel),
     or a top tech company (Google, Meta, Amazon, Apple, Microsoft).
   - "Standard" for all other companies.

7. "Target_Keywords" (array of strings): 
   The top 5-8 technical keywords from the JD that match Kevin's skills 
   (e.g., "Python", "SQL", "Tableau", "Machine Learning").

8. "Match_Score" (integer, 1-10): 
   How well Kevin's resume aligns with this specific role. 
   10 = perfect match, 1 = no overlap. Consider skills, experience level, and domain fit.
Return ONLY valid JSON. No markdown, no code fences, no explanation.
"""

    user_prompt = f"""
JOB URL: {job_url}

JOB DESCRIPTION:
{job_description}
"""

    # Model fallback chain — best model first, cheaper fallbacks
    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    max_retries = 3
    base_delay = 10  # seconds

    for model_name in models_to_try:
        for attempt in range(1, max_retries + 1):
            try:
                print(f"[LLM] Trying {model_name} (attempt {attempt}/{max_retries})...")

                response = client.models.generate_content(
                    model=model_name,
                    contents=[system_prompt, user_prompt],
                    config=genai.types.GenerateContentConfig(
                        temperature=0.3,
                        response_mime_type="application/json",
                    ),
                )
                raw_text = response.text
                result = json.loads(raw_text)

                # Validate required keys with defaults
                defaults = {
                    "Company": "Unknown",
                    "Role": "Unknown",
                    "ATS_System": "Unknown",
                    "visa_eligible": True,
                    "Visa_Required": "No",
                    "company_tier": "Standard",
                    "Target_Keywords": [],
                    "Match_Score": 5
                }
                for key, default in defaults.items():
                    if key not in result:
                        print(f"[LLM] WARNING: Missing key '{key}', using default")
                        result[key] = default

                print(f"[LLM] Analysis complete:")
                print(f"  Company: {result['Company']} | Role: {result['Role']}")
                print(f"  ATS: {result['ATS_System']} | Match: {result['Match_Score']}/10")
                print(f"  Visa: {result['visa_eligible']} | Tier: {result['company_tier']}")
                print(f"  Keywords: {', '.join(result.get('Target_Keywords', []))}")

                # Write analysis to file for n8n to read
                analysis_file = Path("./last_analysis.json")
                analysis_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(f"[LLM] Analysis saved to {analysis_file}")

                # Output structured JSON line for n8n stdout parsing
                print(f"ANALYSIS_JSON::{json.dumps(result)}")
                return result

            except json.JSONDecodeError as e:
                print(f"[LLM] ERROR: Failed to parse JSON response: {e}")
                print(f"[LLM] Raw response: {raw_text[:500]}")
                return {"Company": "Unknown", "Role": "Unknown", "ATS_System": "Unknown",
                        "visa_eligible": True, "Visa_Required": "No", "company_tier": "Standard",
                        "Target_Keywords": [], "Match_Score": 5}

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    delay = base_delay * (2 ** (attempt - 1))  # 10s, 20s, 40s
                    print(f"[LLM] Rate limited on {model_name} — waiting {delay}s before retry...")
                    time.sleep(delay)
                    if attempt == max_retries:
                        print(f"[LLM] Exhausted retries on {model_name}, trying next model...")
                        break  # try next model
                elif "404" in error_str or "NOT_FOUND" in error_str:
                    print(f"[LLM] Model {model_name} not available, trying next model...")
                    break  # skip to next model immediately
                else:
                    print(f"[LLM] ERROR: API call failed: {e}")
                    traceback.print_exc()
                    return {"Company": "Unknown", "Role": "Unknown", "ATS_System": "Unknown",
                            "visa_eligible": True, "Visa_Required": "No", "company_tier": "Standard",
                            "Target_Keywords": [], "Match_Score": 5}

    print("[LLM] All models exhausted — using safe defaults")
    return {"Company": "Unknown", "Role": "Unknown", "ATS_System": "Unknown",
            "visa_eligible": True, "Visa_Required": "No", "company_tier": "Standard",
            "Target_Keywords": [], "Match_Score": 5}


# ─── Approval Management ─────────────────────────────────────────────────────

def save_pending_approval(job_url: str, analysis: dict):
    """Save high-tier job analysis to pending_approvals.json for Telegram review."""
    pending = []
    if PENDING_APPROVALS_FILE.exists():
        try:
            pending = json.loads(PENDING_APPROVALS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pending = []

    pending.append({
        "job_url": job_url,
        "company_tier": analysis["company_tier"],
        "visa_eligible": analysis["visa_eligible"],
        "cover_letter": analysis["generated_cover_letter"],
        "qa_answers": analysis["qa_answers"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending_approval",
    })

    PENDING_APPROVALS_FILE.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    print(f"[APPROVAL] Saved to {PENDING_APPROVALS_FILE} — awaiting Telegram approval")


# ─── Browser Automation ──────────────────────────────────────────────────────

async def scrape_job_description(page) -> str:
    """Extract the job description text from the current page."""
    # Debug: log current page state
    try:
        page_title = await page.evaluate("document.title")
        page_url = await page.evaluate("window.location.href")
        print(f"[SCRAPE] Page title: {page_title}")
        print(f"[SCRAPE] Page URL: {page_url}")
        
        # Detect login redirect
        if any(kw in str(page_url).lower() for kw in ["login", "signin", "auth", "checkpoint"]):
            print("[SCRAPE] ⚠️  LOGIN PAGE DETECTED — cookies may be expired or incompatible")
            print("[SCRAPE] You need to run login_helper.py on the VPS to create fresh cookies")
            return ""
    except Exception as e:
        print(f"[SCRAPE] Debug error: {e}")

    # Try to extract JD text using JavaScript (most reliable with nodriver)
    js_selectors = [
        ".jobs-description__content",           # LinkedIn
        ".jobs-box__html-content",              # LinkedIn alt
        ".jobs-description-content__text",      # LinkedIn v2
        ".job-details-jobs-unified-top-card__job-insight",  # LinkedIn unified
        "#job-details",                         # LinkedIn / Workday
        "[class*='job-description']",           # Generic
        "[class*='jobDescription']",            # Generic camelCase
        "[class*='description__text']",         # LinkedIn variant
        "[data-testid='job-description']",      # Handshake / modern
        ".posting-requirements",                # Lever
        ".content-wrapper",                     # Greenhouse
        ".job-posting-section",                 # Generic
        "article",                              # Semantic fallback
        "main",                                 # Broad fallback
    ]

    for selector in js_selectors:
        try:
            text = await page.evaluate(
                f"""(() => {{
                    const el = document.querySelector('{selector}');
                    return el ? el.innerText : null;
                }})()"""
            )
            if text and len(text.strip()) > 50:
                print(f"[SCRAPE] Found JD via selector: {selector} ({len(text)} chars)")
                return text.strip()
        except Exception:
            continue

    # Final fallback: full body text
    try:
        body_text = await page.evaluate("document.body.innerText")
        if body_text and len(body_text.strip()) > 100:
            print(f"[SCRAPE] Fallback to body text ({len(body_text)} chars)")
            # Truncate to avoid sending enormous text to Gemini
            return body_text.strip()[:10000]
    except Exception as e:
        print(f"[SCRAPE] Body text fallback error: {e}")

    print("[SCRAPE] WARNING: Could not extract job description")
    return ""


def delegate_to_mac_node(job_id: str, job_url: str, analysis: dict):
    """
    Stateful Handshake Payload Transfer. 
    Writes the job specification (including LLM-generated answers and target URL) 
    to a JSON payload file. The Mac Execution Node will pull this payload to execute 
    natively via Playwright.
    """
    payload_dir = Path("./execution_payloads")
    payload_dir.mkdir(exist_ok=True)
    
    payload_path = payload_dir / f"job_payload_{job_id}.json"
    
    payload = {
        "job_id": job_id,
        "job_url": job_url,
        "company": analysis.get("Company", "Unknown"),
        "role": analysis.get("Role", "Unknown"),
        "ats_system": analysis.get("ATS_System", "Unknown"),
        "generated_cover_letter": analysis.get("generated_cover_letter", ""),
        "qa_answers": analysis.get("qa_answers", {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending_execution"
    }
    
    payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[GATEWAY] 📡 Dispatched execution payload to Mac Node: {payload_path}")
    return payload_path


# ─── Main Application Loop ───────────────────────────────────────────────────

def generate_application_material(client: genai.Client, job_url: str, job_description: str, knowledge_base: dict) -> dict:
    """
    Generate just the expensive Application Materials (Cover Letter, QAs) after routing succeeds.
    """
    system_prompt = f"""You are an expert career agent. Generate the exact application materials based on the provided documents.
=== RESUME ===
{knowledge_base['resume']}
=== COVER LETTER TEMPLATES ===
{knowledge_base['cover_letter_template']}
=== INTERVIEW Q&A MATRIX ===
{knowledge_base['interview_qa']}
=== PROJECT CONTEXT ===
{knowledge_base.get('project_context', '')}

=== INSTRUCTIONS ===
Analyze the job description and return strictly a JSON object with these keys:

1. "generated_cover_letter" (string):
   - Use the MASTER TEMPLATE from the cover letter templates file. Follow tone adjustments.
   - Mention F-1 STEM OPT (36 months) only if international students are mentioned.
   - Replace all [BRACKETED] sections with company-specific info. Write with human cadence.

2. "qa_answers" (object):
   - Keys are common application questions found in the job posting.
   - Values are answers drawn STRICTLY from the interview Q&A matrix.

Return ONLY valid JSON. No markdown.
"""
    user_prompt = f"JOB URL: {job_url}\nJOB DESCRIPTION:\n{job_description}"
    
    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    for model_name in models_to_try:
        try:
            print(f"[LLM] Generating specialized materials via {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=[system_prompt, user_prompt],
                config=genai.types.GenerateContentConfig(temperature=0.3, response_mime_type="application/json")
            )
            data = json.loads(response.text)
            return {
                "generated_cover_letter": data.get("generated_cover_letter", ""),
                "qa_answers": data.get("qa_answers", {})
            }
        except Exception as e:
            print(f"[LLM] Generation error on {model_name}: {e}")
            
    return {"generated_cover_letter": "", "qa_answers": {}}


async def apply_to_job_internal(job_url: str, job_id: str, queue, client: genai.Client, kb: dict) -> int:
    """
    HTTP scraping application flow for a single job from the Brain (VPS).
    """
    print(f"\n{'='*60}")
    print(f"[JOB] HTTP Fetching: {job_url}")
    print(f"{'='*60}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        import requests
        from bs4 import BeautifulSoup
        response = requests.get(job_url, headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
    except Exception as e:
        print(f"[JOB] ERROR: HTTP request failed for {job_url}: {e}")
        return EXIT_FAILURE

    # ─── Failsafe: Check if Job is Still Active ──────────────────────────────
    try:
        body_text = soup.body.get_text(separator=" ", strip=True) if soup.body else ""
        closed_phrases = [
            "No longer accepting applications",
            "This job is off the market",
            "This job is no longer available",
            "Job not found",
            "no longer accepting applications"
        ]
        if body_text and any(phrase.lower() in body_text.lower() for phrase in closed_phrases):
            print("[JOB] ERROR: Page indicates this job is no longer available/closed.")
            return EXIT_FAILURE
    except Exception as e:
        print(f"[JOB] Warning: Could not verify job active status failsafe: {e}")
        body_text = ""
    # ─────────────────────────────────────────────────────────────────────────

    # Step 1: Scrape Job Description
    jd_text = ""
    # Try typical specific containers
    js_selectors = [
        ".jobs-description__content",
        ".jobs-box__html-content",
        ".jobs-description-content__text",
        ".job-details-jobs-unified-top-card__job-insight",
        "#job-details",
        ".posting-requirements",
        ".content-wrapper",
        ".job-posting-section"
    ]
    for selector in js_selectors:
        element = soup.select_one(selector)
        if element:
            jd_text = element.get_text(separator="\n", strip=True)
            if len(jd_text) > 50:
                print(f"[SCRAPE] Found JD via selector: {selector} ({len(jd_text)} chars)")
                break
                
    if not jd_text and body_text and len(body_text) > 100:
        print(f"[SCRAPE] Fallback to entire body text ({len(body_text)} chars)")
        jd_text = body_text[:10000]

    if not jd_text:
        print("[JOB] ERROR: No job description found — skipping")
        return EXIT_FAILURE

    # Sanitize JD to prevent prompt injection
    jd_text = sanitize_jd(jd_text)
    print(f"[JOB] JD sanitized ({len(jd_text)} chars)")

    # ─── The LLM Bouncer ─────────────────────────────────────────────────────
    print("[JOB] Running LLM Bouncer prescreen...")
    bouncer_verdict = run_llm_bouncer(jd_text, client)
    if not bouncer_verdict.get("proceed", True):
        reason = bouncer_verdict.get('rejection_reason', 'Failed prescreen')
        print(f"[BOUNCER] Skipped: {reason}")
        return EXIT_FAILED_PRESCREEN
    else:
        print("[BOUNCER] Passed! Proceeding to full analysis.")
    # ─────────────────────────────────────────────────────────────────────────

    # Step 2: Analyze with Gemini
    print("[JOB] Analyzing job with Gemini...")
    analysis = analyze_job(client, job_url, jd_text, kb)

    # Step 3: Low Score Auto-Reject (Path 1)
    if analysis.get("Match_Score", 0) <= 5:
        print(f"[JOB] SKIPPED — Match Score too low ({analysis.get('Match_Score', 0)}/10)")
        return EXIT_LOW_SCORE

    # Step 4: Visa Gatekeeper
    if not analysis["visa_eligible"]:
        print(f"[JOB] SKIPPED — Visa ineligible: {analysis.get('reason', 'Requires US authorization')}")
        return EXIT_FAILURE

    # Step 5: Company Tier Routing (Path 2)
    if analysis["company_tier"] == "High":
        print("[JOB] HIGH-TIER company detected — pausing for Telegram approval")
        save_pending_approval(job_url, analysis)
        return EXIT_HIGH_TIER_PAUSED

    # Step 6: Extract External ATS Link
    print("[JOB] Hunting for external ATS Apply link...")
    external_url = None
    try:
        # Search all anchor tags for apply buttons
        for a in soup.find_all('a', href=True):
            classes = a.get('class', [])
            text = a.get_text(strip=True).lower()
            if 'apply-button' in classes or 'jobs-apply-button' in classes or text == 'apply' or 'apply now' in text:
                external_url = a['href']
                break
    except Exception:
        pass

    if external_url and 'linkedin.com' in external_url and 'sign-in' in external_url:
        print("[JOB] Cannot extract ATS link. Button leads to LinkedIn sign-in (likely Easy Apply).")
        return EXIT_FAILURE

    if not external_url:
        print("[JOB] WARNING: Could not find external Apply link in DOM. Defaulting to source URL for node delegation.")
        external_url = job_url

    print(f"[JOB] Target ATS Link identified: {external_url}")
    
    # ─── Step 7: The ATS Whitelist ──────────────────────────────────────────
    ats_domain = urllib.parse.urlparse(external_url).netloc
    
    # The Workday Trap / Blacklist
    if 'myworkdayjobs.com' in ats_domain or 'icims.com' in ats_domain:
        print(f"[JOB] SKIPPED — Hit ATS Blacklist ({ats_domain}). Account Creation Required. Aborting to save LLM credits.")
        raise Exception("Workday ATS Skipped")
        
    # The ATS Whitelist
    whitelist = ['greenhouse.io', 'lever.co', 'ashbyhq.com']
    if not any(w in ats_domain for w in whitelist):
        print(f"[JOB] WARNING — ATS ({ats_domain}) is not in Whitelist. Attempting execution node routing anyway.")
    else:
        print(f"[JOB] SUCCESS — ATS ({ats_domain}) is Whitelisted for guest checkout!")

    # Step 8: JIT LLM API Generation
    print("[JOB] Validated ATS destination. Generating Just-In-Time Application Materials...")
    materials = generate_application_material(client, job_url, jd_text, kb)
    
    # State Injection
    analysis["generated_cover_letter"] = materials["generated_cover_letter"]
    analysis["qa_answers"] = materials["qa_answers"]
    
    # Step 9: Delegate Form Execution to the Distributed Mac Node
    delegate_to_mac_node(job_id, external_url, analysis)
    
    print("[JOB] ✅ ATS payload generation complete. Payload dispatched to Execution Node.")
    return EXIT_SUCCESS


async def run_apply(queue, client: genai.Client, kb: dict):
    pending_jobs = queue.get_pending_jobs()
    if not pending_jobs:
        print("[APPLY] No pending jobs. Skipping apply phase.")
        return

    for job_id, job_data in pending_jobs.items():
        print(f"\n[{'='*60}]\n[ORCHESTRATOR] Processing Job: {job_data['company']} - {job_data['title']}")
        try:
            exit_code = await apply_to_job_internal(job_data['url'], job_id, queue, client, kb)
            
            # Trust the exit_code returned from apply_to_job_internal.
            if exit_code == EXIT_SUCCESS:
                queue.update_status(job_id, "APPLIED", notes="Successfully analyzed and dispatched payload.")
            elif exit_code == EXIT_LOW_SCORE:
                queue.update_status(job_id, "FAILED", notes="Skipped: Low Match Score.")
            elif exit_code == EXIT_HIGH_TIER_PAUSED:
                queue.update_status(job_id, "PENDING", notes="Paused for manual review (High Tier).")
            elif exit_code == EXIT_FAILED_PRESCREEN:
                queue.update_status(job_id, "FAILED_PRESCREEN", notes="Failed LLM Bouncer (Visa/Salary).")
            else:
                queue.update_status(job_id, "SOFT_FAIL", notes=f"Failed cleanly with EXIT_FAILURE code.")
                    
        except Exception as e:
            error_msg = str(e)
            print(f"[ORCHESTRATOR] Exception caught for {job_id}: {error_msg}")
            
            if "Workday ATS Skipped" in error_msg or "icims.com" in error_msg:
                queue.update_status(job_id, "WORKDAY_SKIPPED", notes="ATS blacklisted.")
            elif "no longer available" in error_msg.lower() or "off the market" in error_msg.lower():
                queue.update_status(job_id, "FAILED", notes="Job no longer available.")
            else:
                queue.update_status(job_id, "SOFT_FAIL", notes=f"Exception caught: {error_msg}")
        finally:
            import random
            jitter = random.uniform(3.5, 7.2)
            print(f"[ORCHESTRATOR] Tab loaded about:blank. State purged. Jittering for {jitter:.2f}s before next job...\n")
            await asyncio.sleep(jitter)

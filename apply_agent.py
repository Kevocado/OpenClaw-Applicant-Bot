import asyncio
import random
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import nodriver as uc
import nodriver.cdp.network as network
from google import genai
from dotenv import load_dotenv

# ─── Configuration ────────────────────────────────────────────────────────────

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KEYWORDSAI_API_KEY = os.getenv("KEYWORDSAI_API_KEY")
USER_DATA_DIR = os.getenv("USER_DATA_DIR", "./user_data_dir")
SCREENSHOTS_DIR = Path("./screenshots")
PENDING_APPROVALS_FILE = Path("./pending_approvals.json")
KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
# Exit codes for n8n orchestration
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_HIGH_TIER_PAUSED = 2  # Signals n8n to route to Telegram for approval
EXIT_LOW_SCORE = 3         # Signals n8n to auto-reject application

# DataImpulse Residential Proxy
PROXY_SERVER = "http://gw.dataimpulse.com:823"

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
        "resume": "honest_resume.txt",
        "cover_letter_template": "cover_letter_templates.txt",
        "interview_qa": "interview_qa_matrix.txt",
        "project_context": "project_context.txt",
    }
    for key, filename in files.items():
        filepath = KNOWLEDGE_BASE_DIR / filename
        if filepath.exists():
            kb[key] = filepath.read_text(encoding="utf-8")
            print(f"[KB] Loaded {filename} ({len(kb[key])} chars)")
        else:
            print(f"[KB] WARNING: {filename} not found at {filepath}")
            kb[key] = ""
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

9. "generated_cover_letter" (string):
   - Use the MASTER TEMPLATE from the cover letter templates file.
   - Follow the TONE ADJUSTMENTS for the company type.
   - CRITICAL: Read the Job Description carefully. If the JD asks for specific questions to be answered in the cover letter, or specifies a word/page limit, you MUST follow those exact instructions. Otherwise, ensure the cover letter is concise, highly relevant, and avoids fluff.
   - MUST include the $3.05M DOT Foods savings metric.
   - MUST include the 100+ WOW Payments field sales conversations.
   - Mention F-1 STEM OPT (36 months) only if the JD mentions international students.
   - Replace all [BRACKETED] sections with company-specific information.
   - Reference the most relevant project from the PROJECT CONTEXT based on JD keywords.
   
   [HUMANIZER SKILL PROTOCOL ACTIVATED]
   You must transform this cover letter using the Humanizer module guidelines.
   1. Remove all signs of AI-generated writing. 
   2. Do not use robotic transition words or overly formal vocabulary (e.g., avoid "furthermore", "delve", "testament to", "crucial").
   3. Write with the natural, slightly imperfect cadence of a human professional. 
   4. Keep sentence structures varied but grounded strictly in the provided resume achievements.


10. "qa_answers" (object):
    - Keys are common application questions found in the job posting.
    - Values are answers drawn STRICTLY from the interview Q&A matrix.
    - If the JD asks "Why this company?", use the framework from the matrix.
    - For visa/sponsorship questions, use the EXACT context-dependent answers from the matrix
      (different answer depending on the exact question phrasing).

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
                    "Match_Score": 5,
                    "generated_cover_letter": "",
                    "qa_answers": {},
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
                        "Target_Keywords": [], "Match_Score": 5,
                        "generated_cover_letter": "", "qa_answers": {}}

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
                            "Target_Keywords": [], "Match_Score": 5,
                            "generated_cover_letter": "", "qa_answers": {}}

    print("[LLM] All models exhausted — using safe defaults")
    return {"Company": "Unknown", "Role": "Unknown", "ATS_System": "Unknown",
            "visa_eligible": True, "Visa_Required": "No", "company_tier": "Standard",
            "Target_Keywords": [], "Match_Score": 5,
            "generated_cover_letter": "", "qa_answers": {}}


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


async def fill_application_form(page, analysis: dict):
    """
    Attempt to fill an application form using the generated cover letter and QA answers.
    This is a best-effort approach — DOM structures vary wildly between job boards.
    """
    cover_letter = analysis.get("generated_cover_letter", "")
    qa_answers = analysis.get("qa_answers", {})

    # Try to find and fill cover letter textarea
    cover_letter_selectors = [
        "textarea[name*='cover']",
        "textarea[id*='cover']",
        "textarea[placeholder*='cover letter']",
        "textarea[aria-label*='cover letter']",
        "textarea[name*='message']",
    ]

    for selector in cover_letter_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                await elem.clear_input()
                await elem.send_keys(cover_letter)
                print(f"[FORM] Filled cover letter via: {selector}")
                break
        except Exception:
            continue

    # Try to fill QA text fields
    for question, answer in qa_answers.items():
        try:
            # Look for textareas/inputs near labels containing the question text
            labels = await page.query_selector_all("label")
            for label in labels:
                label_text = await label.text_all
                if label_text and question.lower() in label_text.lower():
                    label_for = await label.get_attribute("for")
                    if label_for:
                        field = await page.query_selector(f"#{label_for}")
                        if field:
                            await field.clear_input()
                            await field.send_keys(str(answer))
                            print(f"[FORM] Filled QA field: {question[:50]}...")
                            break
        except Exception:
            continue

    # Add a small delay for form validation to catch up
    await asyncio.sleep(1)
    print("[FORM] Form fill attempt complete")


async def take_screenshot(page, label: str):
    """Save a screenshot with a descriptive filename."""
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = SCREENSHOTS_DIR / f"{label}_{timestamp}.png"
    await page.save_screenshot(filename=str(filename))
    print(f"[SCREENSHOT] Saved: {filename}")
    return filename


# ─── Main Application Loop ───────────────────────────────────────────────────

async def apply_to_job(browser, job_url: str, client: genai.Client, kb: dict) -> int:
    """
    Main application flow for a single job.
    Returns exit code: 0=success, 1=failure, 2=high-tier paused.
    """
    print(f"\n{'='*60}")
    print(f"[JOB] Navigating to: {job_url}")
    print(f"{'='*60}")

    # Robust Proxy Retry Logic
    max_retries = 3
    page = None
    for attempt in range(1, max_retries + 1):
        page = await browser.get(job_url)
        print("[JOB] Waiting for page to fully render...")
        await asyncio.sleep(random.uniform(5.0, 8.5))
        
        # Check against proxy connection drops
        try:
            current_url = await page.evaluate("window.location.href")
        except Exception:
            current_url = getattr(page.target, 'url', '')
            
        if 'chrome-error://' in str(current_url):
            print(f"⚠️ [NETWORK] Connection dropped by LinkedIn (Attempt {attempt}/{max_retries}). Retrying navigation...")
            await asyncio.sleep(4)
            continue
        else:
            break
            
    if page:
        try:
            final_url = await page.evaluate("window.location.href")
        except Exception:
            final_url = getattr(page.target, 'url', '')
        if 'chrome-error://' in str(final_url):
            print("[JOB] ERROR: Proxy repeatedly failed to connect to the target URL.")
            return EXIT_FAILURE

    # Wait for page to fully load (LinkedIn is JS-heavy)
    print("[JOB] Waiting for page to load...")
    await asyncio.sleep(8)

    # Step 1: Scrape Job Description
    jd_text = await scrape_job_description(page)
    if not jd_text:
        print("[JOB] ERROR: No job description found — skipping")
        await take_screenshot(page, "no_jd")
        return EXIT_FAILURE

    # Sanitize JD to prevent prompt injection
    jd_text = sanitize_jd(jd_text)
    print(f"[JOB] JD sanitized ({len(jd_text)} chars)")

    # Step 2: Analyze with Gemini
    print("[JOB] Analyzing job with Gemini...")
    analysis = analyze_job(client, job_url, jd_text, kb)

    # Step 3: Low Score Auto-Reject (Path 1)
    if analysis.get("Match_Score", 0) <= 5:
        print(f"[JOB] SKIPPED — Match Score too low ({analysis.get('Match_Score', 0)}/10)")
        await take_screenshot(page, "skipped_low_score")
        return EXIT_LOW_SCORE

    # Step 4: Visa Gatekeeper
    if not analysis["visa_eligible"]:
        print(f"[JOB] SKIPPED — Visa ineligible: {analysis.get('reason', 'Requires US authorization')}")
        await take_screenshot(page, "skipped_visa")
        return EXIT_FAILURE

    # Step 5: Company Tier Routing (Path 2)
    if analysis["company_tier"] == "High":
        print("[JOB] HIGH-TIER company detected — pausing for Telegram approval")
        save_pending_approval(job_url, analysis)
        await take_screenshot(page, "high_tier_paused")
        return EXIT_HIGH_TIER_PAUSED

    # Step 6: Standard-tier → Auto-fill and submit (Path 3)
    print("[JOB] STANDARD-TIER — proceeding with auto-fill")
    await fill_application_form(page, analysis)

    # Step 6: Look for submit button (but DON'T click yet — safety first)
    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button[class*='submit']",
        "[data-testid*='submit']",
    ]

    for selector in submit_selectors:
        try:
            submit_btn = await page.query_selector(selector)
            if submit_btn:
                print(f"[JOB] Found submit button: {selector}")
                await submit_btn.click()
                print("[JOB] ✅ Application submitted!")
                await take_screenshot(page, "ready_to_submit")
                return EXIT_SUCCESS
        except Exception:
            continue

    print("[JOB] WARNING: No submit button found")
    await take_screenshot(page, "no_submit_button")
    return EXIT_FAILURE


async def main():
    """Entry point — reads job URL from CLI args or environment."""
    # Parse job URL from arguments
    if len(sys.argv) < 2:
        print("Usage: python apply_agent.py <job_url>")
        print("  Or set JOB_URL environment variable")
        job_url = os.getenv("JOB_URL")
        if not job_url:
            sys.exit(EXIT_FAILURE)
    else:
        job_url = sys.argv[1]

    print(f"[AGENT] OpenClaw Applicant Bot starting...")
    print(f"[AGENT] Target: {job_url}")
    print(f"[AGENT] Timestamp: {datetime.now(timezone.utc).isoformat()}")

    # Load knowledge base
    kb = load_knowledge_base()

    # Initialize LLM (Respan proxy or direct Gemini)
    client = init_gemini()

    # Detect if we have a display (local) or not (VPS)
    has_display = os.getenv("DISPLAY") is not None or sys.platform == "darwin"
    headless_mode = not has_display
    print(f"[BROWSER] Launching nodriver (headless={headless_mode}, profile={USER_DATA_DIR})")

    # Configure Nodriver explicitly for root VPS execution
    config = uc.Config()
    config.headless = headless_mode
    config.user_data_dir = USER_DATA_DIR
    config.sandbox = False
    config.add_argument('--disable-dev-shm-usage')
    config.add_argument('--disable-gpu')
    config.add_argument('--disable-software-rasterizer')
    
    browser = await uc.start(config=config)

    # --- NEW COOKIE INJECTION BLOCK ---
    li_at_cookie = os.getenv("LINKEDIN_LI_AT")
    if li_at_cookie:
        print("[AUTH] Injecting LinkedIn session cookie...")
        # Navigate to a safe page to establish domain context
        page = await browser.get("https://www.linkedin.com/robots.txt")
        
        # Pause for 2 to 4 seconds to simulate reading the page
        await asyncio.sleep(random.uniform(2.1, 4.5)) 
        
        await page.send(network.set_cookie(
            name="li_at",
            value=li_at_cookie,
            domain=".linkedin.com",
            path="/",
            secure=True,
            http_only=True
        ))
        print("[AUTH] Cookie injected successfully. Simulating human pause...")
        
        # Pause before jumping to the job URL (Crucial for bypassing 429s)
        await asyncio.sleep(random.uniform(3.5, 6.8))
    else:
        print("⚠️ WARNING: LINKEDIN_LI_AT not found in .env. Bot may face LinkedIn login walls.")

    hs_cookie = os.getenv("HANDSHAKE_COOKIE")
    if hs_cookie and "joinhandshake.com" in job_url:
        print("[AUTH] Injecting Handshake session cookie...")
        page = await browser.get("https://app.joinhandshake.com/robots.txt")
        await asyncio.sleep(random.uniform(2.1, 4.5)) 
        await page.send(network.set_cookie(
            name="_handshake_session",
            value=hs_cookie,
            domain=".joinhandshake.com",
            path="/",
            secure=True,
            http_only=True
        ))
        print("[AUTH] Cookie injected successfully. Simulating human pause...")
        await asyncio.sleep(random.uniform(3.5, 6.8))

    mm_cookie = os.getenv("MIGRATEMATE_COOKIE")
    if mm_cookie and "migratemate.co" in job_url:
        print("[AUTH] Injecting MigrateMate session cookie...")
        page = await browser.get("https://migratemate.co/robots.txt")
        await asyncio.sleep(random.uniform(2.1, 4.5)) 
        await page.send(network.set_cookie(
            name="session",
            value=mm_cookie,
            domain=".migratemate.co",
            path="/",
            secure=True,
            http_only=True
        ))
        print("[AUTH] Cookie injected successfully. Simulating human pause...")
        await asyncio.sleep(random.uniform(3.5, 6.8))
    # -----------------------------------

    try:
        exit_code = await apply_to_job(browser, job_url, client, kb)
    except TimeoutError:
        print("[AGENT] ERROR: Page load timeout")
        exit_code = EXIT_FAILURE
    except Exception as e:
        print(f"[AGENT] ERROR: Unexpected exception: {e}")
        traceback.print_exc()
        # Try to screenshot whatever state we're in
        try:
            tab = browser.main_tab
            if tab:
                await take_screenshot(tab, "crash")
        except Exception:
            pass
        exit_code = EXIT_FAILURE
    finally:
        try:
            browser.stop()
        except Exception:
            pass

    print(f"\n[AGENT] Exiting with code {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    uc.loop().run_until_complete(main())

"""
OpenClaw Applicant Bot — Browser Agent
Uses nodriver (undetected Chrome) + Google Gemini Pro for autonomous job applications.
"""

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import nodriver as uc
from google import genai
from dotenv import load_dotenv

# ─── Configuration ────────────────────────────────────────────────────────────

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
USER_DATA_DIR = os.getenv("USER_DATA_DIR", "./user_data_dir")
SCREENSHOTS_DIR = Path("./screenshots")
PENDING_APPROVALS_FILE = Path("./pending_approvals.json")
KNOWLEDGE_BASE_DIR = Path("./knowledge_base")

# Exit codes for n8n orchestration
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_HIGH_TIER_PAUSED = 2  # Signals n8n to route to Telegram for approval

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


# ─── Gemini Integration ──────────────────────────────────────────────────────

def init_gemini() -> genai.Client:
    """Initialize the Gemini client."""
    if not GEMINI_API_KEY:
        print("[ERROR] GEMINI_API_KEY not set in environment")
        sys.exit(EXIT_FAILURE)
    client = genai.Client(api_key=GEMINI_API_KEY)
    print("[GEMINI] Client initialized (gemini-2.0-flash)")
    return client


def analyze_job(client: genai.Client, job_url: str, job_description: str, knowledge_base: dict) -> dict:
    """
    Analyze a job posting using Gemini Pro.
    Returns strict JSON: {visa_eligible, company_tier, generated_cover_letter, qa_answers}
    """
    system_prompt = f"""You are an expert career agent for Kevin Sigey. You have access to his EXACT resume, 
cover letter templates, and interview Q&A matrix below. You must STRICTLY adhere to these documents.
Do NOT invent skills, experiences, or metrics not present in these files.

=== RESUME ===
{knowledge_base['resume']}

=== COVER LETTER TEMPLATES ===
{knowledge_base['cover_letter_template']}

=== INTERVIEW Q&A MATRIX ===
{knowledge_base['interview_qa']}

=== INSTRUCTIONS ===
Analyze the following job description and return a JSON object with these exact keys:

1. "visa_eligible" (boolean): 
   - false if the JD explicitly says "U.S. Citizens only", "U.S. Citizenship required", 
     "No sponsorship", "Must be authorized to work without sponsorship", or similar.
   - true if OPT/CPT is accepted, or if no visa restriction is mentioned.

2. "company_tier" (string, either "High" or "Standard"):
   - "High" if the company is a top consulting firm (McKinsey, BCG, Bain, Deloitte, EY, KPMG, PwC),
     a top finance firm (Goldman Sachs, JP Morgan, Morgan Stanley, Capital One, BlackRock, Citadel),
     or a top tech company (Google, Meta, Amazon, Apple, Microsoft).
   - "Standard" for all other companies.

3. "generated_cover_letter" (string):
   - Use the MASTER TEMPLATE from the cover letter templates file.
   - Follow the TONE ADJUSTMENTS for the company type.
   - Must be between 200-300 words based on company type.
   - MUST include the $3.05M DOT Foods savings metric.
   - MUST include the 100+ WOW Payments field sales conversations.
   - Mention F-1 STEM OPT (36 months) only if the JD mentions international students.
   - Replace all [BRACKETED] sections with company-specific information.

4. "qa_answers" (object):
   - Keys are common application questions found in the job posting.
   - Values are answers drawn STRICTLY from the interview Q&A matrix.
   - If the JD asks "Why this company?", use the framework from the matrix.
   - If the JD asks about visa/sponsorship, use the exact visa answer from the matrix.

Return ONLY valid JSON. No markdown, no code fences, no explanation.
"""

    user_prompt = f"""
JOB URL: {job_url}

JOB DESCRIPTION:
{job_description}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[system_prompt, user_prompt],
            config=genai.types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
        result = json.loads(response.text)

        # Validate required keys
        required_keys = ["visa_eligible", "company_tier", "generated_cover_letter", "qa_answers"]
        for key in required_keys:
            if key not in result:
                print(f"[GEMINI] WARNING: Missing key '{key}' in response, adding default")
                if key == "visa_eligible":
                    result[key] = True
                elif key == "company_tier":
                    result[key] = "Standard"
                elif key == "generated_cover_letter":
                    result[key] = ""
                elif key == "qa_answers":
                    result[key] = {}

        print(f"[GEMINI] Analysis complete — visa_eligible={result['visa_eligible']}, tier={result['company_tier']}")
        return result

    except json.JSONDecodeError as e:
        print(f"[GEMINI] ERROR: Failed to parse JSON response: {e}")
        print(f"[GEMINI] Raw response: {response.text[:500]}")
        return {"visa_eligible": True, "company_tier": "Standard", "generated_cover_letter": "", "qa_answers": {}}
    except Exception as e:
        print(f"[GEMINI] ERROR: API call failed: {e}")
        traceback.print_exc()
        return {"visa_eligible": True, "company_tier": "Standard", "generated_cover_letter": "", "qa_answers": {}}


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
    # Try common JD selectors across LinkedIn, Handshake, and generic job boards
    selectors = [
        ".jobs-description__content",           # LinkedIn
        ".jobs-box__html-content",              # LinkedIn alt
        "[class*='job-description']",           # Generic
        "[class*='jobDescription']",            # Generic camelCase
        "[data-testid='job-description']",      # Handshake / modern
        ".posting-requirements",                # Lever
        ".content-wrapper",                     # Greenhouse
        "#job-details",                         # Workday
        "article",                              # Semantic fallback
        "main",                                 # Broad fallback
    ]

    for selector in selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                text = await elem.text_all
                if text and len(text.strip()) > 100:
                    print(f"[SCRAPE] Found JD via selector: {selector} ({len(text)} chars)")
                    return text.strip()
        except Exception:
            continue

    # Final fallback: grab all body text
    try:
        body = await page.query_selector("body")
        if body:
            text = await body.text_all
            print(f"[SCRAPE] Fallback to body text ({len(text)} chars)")
            return text.strip()
    except Exception:
        pass

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
    page = await browser.get(job_url)
    print(f"\n{'='*60}")
    print(f"[JOB] Navigating to: {job_url}")
    print(f"{'='*60}")

    # Wait for page to load
    await asyncio.sleep(3)

    # Step 1: Scrape Job Description
    jd_text = await scrape_job_description(page)
    if not jd_text:
        print("[JOB] ERROR: No job description found — skipping")
        await take_screenshot(page, "no_jd")
        return EXIT_FAILURE

    # Step 2: Analyze with Gemini
    print("[JOB] Analyzing job with Gemini...")
    analysis = analyze_job(client, job_url, jd_text, kb)

    # Step 3: Visa Gatekeeper
    if not analysis["visa_eligible"]:
        print(f"[JOB] SKIPPED — Visa ineligible: {analysis.get('reason', 'Requires US authorization')}")
        await take_screenshot(page, "skipped_visa")
        return EXIT_FAILURE

    # Step 4: Company Tier Routing
    if analysis["company_tier"] == "High":
        print("[JOB] HIGH-TIER company detected — pausing for Telegram approval")
        save_pending_approval(job_url, analysis)
        await take_screenshot(page, "high_tier_paused")
        return EXIT_HIGH_TIER_PAUSED

    # Step 5: Standard-tier → Auto-fill and submit
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
                # TODO: Uncomment when ready for production
                # await submit_btn.click()
                # print("[JOB] ✅ Application submitted!")
                print("[JOB] ⚠️  DRY RUN — submit button found but not clicked (safety mode)")
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

    # Initialize Gemini
    client = init_gemini()

    # Detect if we have a display (local) or not (VPS)
    has_display = os.getenv("DISPLAY") is not None or sys.platform == "darwin"
    headless_mode = not has_display
    print(f"[BROWSER] Launching nodriver (headless={headless_mode}, profile={USER_DATA_DIR})")

    browser = await uc.start(
        user_data_dir=USER_DATA_DIR,
        headless=headless_mode,
        browser_args=[
            "--window-size=1920,1080",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )

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

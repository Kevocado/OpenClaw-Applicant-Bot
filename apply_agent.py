import asyncio
import json
import os
import re
import sys
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai

# ─── Configuration ────────────────────────────────────────────────────────────

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_BASE_DIR = Path(os.path.join(PROJECT_ROOT, "knowledge_base"))
JOB_DESCRIPTIONS_DIR = Path(os.path.join(PROJECT_ROOT, "job_descriptions"))
JOB_DESCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_LOW_SCORE = 3         
EXIT_FAILED_PRESCREEN = 4  

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
    return kb

# ─── Job Description Sanitization (Prompt Injection Defense) ─────────────────

def sanitize_jd(raw_text: str) -> str:
    """Strip potentially malicious content from scraped job descriptions."""
    text = re.sub(r'<[^>]+>', '', raw_text)
    injection_patterns = [
        r'ignore\s+(all\s+)?previous\s+instructions',
        r'output\s+your\s+(system\s+)?prompt',
        r'disregard\s+(all\s+)?above',
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, '[REDACTED]', text, flags=re.IGNORECASE)
    text = text[:10000]
    return re.sub(r'\s+', ' ', text).strip()

# ─── LLM Bouncer ─────────────────────────────────────────────────────────────

def run_llm_bouncer(jd_text: str, kb: dict) -> dict:
    """Evaluate job against rules using Gemini Flash. Returns structured JSON."""
    resume_text = kb.get("resume", "")
    rules_json = kb.get("application_rules", "{}")

    bouncer_prompt = f"""You are a strict job screener for a specific candidate. Evaluate the job posting below.

<JOB_POSTING>
{jd_text}
</JOB_POSTING>

<CANDIDATE_PROFILE>
{resume_text[:2500]}
</CANDIDATE_PROFILE>

<SCREENING_RULES>
{rules_json}
</SCREENING_RULES>

Instructions:
1. Extract COMPANY NAME and JOB TITLE directly from <JOB_POSTING>. Do NOT use the candidate's current employer.
2. REJECT if: US Citizen only, Security Clearance required, No CPT/OPT, No sponsorship, Unpaid, Full-time (not an internship/co-op).
3. REJECT if the role is clearly a poor fit (e.g. marketing, legal, nursing, manufacturing, unrelated field).
4. SCORE match 1-10 strictly: 9-10 = near-perfect fit for an MSBA student with Data/Analytics/Finance/Product skills. 7-8 = good fit. Below 7 = weak fit.
5. Be conservative. Most jobs should score 5-7. Only exceptional alignment earns 9-10.

Return ONLY raw JSON, no markdown:
{{"proceed": true, "Match_Score": 7, "Company": "<company from posting>", "Role": "<title from posting>", "rejection_reason": ""}}
"""

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("[BOUNCER] ERROR: GEMINI_API_KEY not set. Defaulting to REJECT.")
        return {"proceed": False, "rejection_reason": "No Gemini API key", "Match_Score": 0, "Company": "Unknown", "Role": "Unknown"}

    try:
        client = genai.Client(api_key=gemini_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=bouncer_prompt
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)
        if "Match_Score" in result and isinstance(result["Match_Score"], str):
            result["Match_Score"] = int(result["Match_Score"]) if result["Match_Score"].isdigit() else 5
        return result
    except json.JSONDecodeError as e:
        print(f"[BOUNCER] JSON parse error: {e}. Defaulting to REJECT.")
        return {"proceed": False, "rejection_reason": "Bouncer parse error", "Match_Score": 0, "Company": "Unknown", "Role": "Unknown"}
    except Exception as e:
        print(f"[BOUNCER] Gemini API error: {e}")
        return {"proceed": False, "rejection_reason": f"Gemini error: {str(e)}", "Match_Score": 0, "Company": "Unknown", "Role": "Unknown"}


# ─── Telegram Notifier ───────────────────────────────────────────────────────

def send_telegram_alert(company: str, role: str, score: int, job_id: str, job_url: str):
    """Sends a Telegram message to the user for a passing job."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Missing Bot Token or Chat ID. Cannot send alert.")
        return

    text = (f"🎯 *New Job Match!*\n\n"
            f"🏢 *Company:* {company}\n"
            f"💼 *Role:* {role}\n"
            f"⭐ *Match Score:* {score}/10\n\n"
            f"🔗 [Apply Here]({job_url})\n\n"
            f"Reply with `Generate {job_id}` to draft a tailored cover letter.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"[TELEGRAM] ✅ Alert sent for {company} - {role}")
        else:
            print(f"[TELEGRAM] ❌ Failed to send alert: {response.text}")
    except Exception as e:
        print(f"[TELEGRAM] ❌ Exception sending alert: {e}")

def delegate_to_mac_node(job_id: str, job_url: str, analysis: dict):
    """
    Stateful Handshake Payload Transfer. 
    Writes the job specification (including LLM-generated answers and target URL) 
    to a JSON payload file. The Mac Execution Node will pull this payload to execute 
    natively via Playwright.
    """
    # ─── STRICT PAYLOAD VALIDATION ───────────────────────────────────────────
    if not job_id or not str(job_id).strip():
        print(f"[GATEWAY] ❌ ERROR: Validation Failed. Missing job_id.")
        return None
    if not job_url or not str(job_url).startswith("http"):
        print(f"[GATEWAY] ❌ ERROR: Validation Failed. Invalid job_url: {job_url}")
        return None
    
    jd = analysis.get("job_description", "")
    
    if not isinstance(jd, str) or len(jd) < 10:
        print(f"[GATEWAY] ❌ ERROR: Validation Failed. Job description is invalid.")
        return None
    # ─────────────────────────────────────────────────────────────────────────
    
    payload_dir = Path("./execution_payloads")
    payload_dir.mkdir(exist_ok=True)
    
    payload_path = payload_dir / f"job_payload_{job_id}.json"
    
    payload = {
        "job_id": job_id,
        "job_url": job_url,
        "company": analysis.get("Company", "Unknown"),
        "role": analysis.get("Role", "Unknown"),
        "ats_system": analysis.get("ATS_System", "Unknown"),
        "job_description": analysis.get("job_description", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending_execution"
    }
    try:
        # We need to save the payload locally for Mac to sync.
        payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[GATEWAY] ✅ Payload {payload_path.name} ready for Mac Sync")
    except Exception as e:
        print(f"[GATEWAY] ❌ ERROR saving payload: {e}")
        return None
    return payload_path

# ─── Main Application Loop ───────────────────────────────────────────────────

async def apply_to_job_internal(job_url: str, job_id: str, queue, kb: dict) -> int:
    """HTTP scraping application flow for a single job from the Brain (VPS)."""
    print(f"\n{'='*60}")
    print(f"[JOB] HTTP Fetching: {job_url}")
    print(f"{'='*60}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        response = requests.get(job_url, headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
    except Exception as e:
        print(f"[JOB] ERROR: HTTP request failed for {job_url}: {e}")
        return EXIT_FAILURE

    # Check if Job is Still Active
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

    # Scrape Job Description
    jd_text = ""
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
                break
                
    if not jd_text and body_text and len(body_text) > 100:
        jd_text = body_text[:10000]

    if not jd_text:
        print("[JOB] ERROR: No job description found — skipping")
        return EXIT_FAILURE

    jd_text = sanitize_jd(jd_text)
    print(f"[JOB] JD extracted and sanitized ({len(jd_text)} chars)")

    # Run Ollama (phi3:mini) Bouncer
    print("[JOB] Running Gemini Flash Bouncer prescreen...")
    bouncer_verdict = run_llm_bouncer(jd_text, kb)
    
    proceed = bouncer_verdict.get("proceed", False)
    score = bouncer_verdict.get("Match_Score", 0)
    company = bouncer_verdict.get("Company", "Unknown")
    role = bouncer_verdict.get("Role", "Unknown")
    
    if not proceed:
        reason = bouncer_verdict.get('rejection_reason', 'Failed prescreen')
        print(f"[BOUNCER] Skipped: {reason}")
        return EXIT_FAILED_PRESCREEN

    # Read threshold at runtime so /setscore from ClawdMasterBot takes effect immediately
    threshold_file = Path(os.path.dirname(os.path.abspath(__file__))) / "score_threshold.txt"
    try:
        min_score = int(threshold_file.read_text().strip())
    except Exception:
        min_score = 9  # Default: only elite matches

    if score < min_score:
        print(f"[JOB] SKIPPED — Match Score too low ({score}/10, need {min_score})")
        return EXIT_LOW_SCORE

    print(f"[BOUNCER] Passed! High Match Score ({score}/10). Creating job alert.")
    
    # Save the JD for on-demand Gemini Generation
    jd_filepath = JOB_DESCRIPTIONS_DIR / f"{job_id}.txt"
    jd_filepath.write_text(jd_text, encoding="utf-8")
    print(f"[JOB] Saved description to {jd_filepath}")
    
    # Send Telegram Alert
    send_telegram_alert(company, role, score, job_id, job_url)

    # State Injection
    bouncer_verdict["job_description"] = jd_text
    
    # Delegate Form Execution to the Distributed Mac Node
    delegate_to_mac_node(job_id, job_url, bouncer_verdict)
    
    print("[JOB] ✅ ATS payload generation complete. Payload dispatched to Execution Node.")
    return EXIT_SUCCESS

async def run_apply(queue, kb: dict):
    pending_jobs = queue.get_pending_jobs()
    if not pending_jobs:
        print("[APPLY] No pending jobs. Skipping apply phase.")
        return

    for job_id, job_data in pending_jobs.items():
        print(f"\n[{'='*60}]\n[ORCHESTRATOR] Processing Job: {job_data['company']} - {job_data['title']}")
        try:
            exit_code = await apply_to_job_internal(job_data['url'], job_id, queue, kb)
            
            if exit_code == EXIT_SUCCESS:
                queue.update_status(job_id, "APPLIED", notes="Successfully passed and notified via Telegram.")
            elif exit_code == EXIT_LOW_SCORE:
                queue.update_status(job_id, "FAILED", notes="Skipped: Low Match Score.")
            elif exit_code == EXIT_FAILED_PRESCREEN:
                queue.update_status(job_id, "FAILED_PRESCREEN", notes="Failed LLM Bouncer (Visa/Salary rules).")
            else:
                queue.update_status(job_id, "SOFT_FAIL", notes=f"Failed cleanly with EXIT_FAILURE code.")
                    
        except (asyncio.CancelledError, KeyboardInterrupt):
            print("\\n[ORCHESTRATOR] Shutting down gracefully. Queue state is preserved.")
            return
        except Exception as e:
            error_msg = str(e)
            print(f"[ORCHESTRATOR] Exception caught for {job_id}: {error_msg}")
            queue.update_status(job_id, "SOFT_FAIL", notes=f"Exception caught: {error_msg}")
        finally:
            import random
            jitter = random.uniform(3.5, 7.2)
            print(f"[ORCHESTRATOR] Resting for {jitter:.2f}s before next job...\n")
            await asyncio.sleep(jitter)

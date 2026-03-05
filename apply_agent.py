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

import nodriver as uc
import nodriver.cdp.network as network
from google import genai
from dotenv import load_dotenv

# ─── Configuration ────────────────────────────────────────────────────────────

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KEYWORDSAI_API_KEY = os.getenv("KEYWORDSAI_API_KEY")
USER_DATA_DIR = "/Users/sigey/Documents/Projects/OpenClaw Resume Bot/user_data_dir"
SCREENSHOTS_DIR = Path("./screenshots")
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


# ─── LLM Bouncer ─────────────────────────────────────────────────────────────

async def run_llm_bouncer(jd_text: str, client: genai.Client) -> dict:
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


async def get_execution_context(browser, main_tab):
    """
    Checks if the ATS form is embedded in an iframe. 
    Returns the iframe target if found, otherwise returns the main tab.
    """
    try:
        # 1. Look for known ATS iframe signatures
        iframe_element = await main_tab.select('iframe[src*="greenhouse.io"], iframe[src*="lever.co"]', timeout=3)
        
        if iframe_element and iframe_element.frame_id:
            print(f"[APPLY] Detected Embedded ATS iFrame (Frame ID: {iframe_element.frame_id}). Switching context...")
            
            # 2. Search nodriver's internal target list for the matching frame ID
            # Use next() with default=None to prevent StopIteration crash
            iframe_target = next((x for x in browser.targets if str(x.target.target_id) == str(iframe_element.frame_id)), None)
            
            if iframe_target:
                print(f"[APPLY] Successfully switched to iframe context.")
                return iframe_target
            else:
                print(f"[APPLY] WARNING: Iframe element found but target not in browser.targets. Falling back to main tab.")
            
    except Exception as e:
        # No iframe found, standard page
        print(f"[APPLY] No iframe detected or error during iframe lookup: {e}")
        pass 
        
    return main_tab

async def extract_form_schema(page):
    schema_js = """
    (() => {
        const fields = [];
        const elements = document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select');
        elements.forEach((el, idx) => {
            const uid = `clawd_${idx}`;
            el.setAttribute('data-clawd-id', uid);
            const uniqueSelector = `[data-clawd-id="${uid}"]`;

            let labelText = '';
            if (el.id) {
                const label = document.querySelector(`label[for="${el.id}"]`);
                if (label) labelText = label.innerText;
            }
            let parentLabel = el.closest('label');
            if (!labelText && parentLabel) {
                labelText = parentLabel.innerText;
            }
            labelText = (labelText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim();

            let options = [];
            if (el.tagName.toLowerCase() === 'select') {
                options = Array.from(el.querySelectorAll('option')).map(o => o.innerText.trim()).filter(t => t);
            }
            fields.push({ selector: uniqueSelector, tag: el.tagName.toLowerCase(), type: el.type || '', label: labelText, options: options });
        });
        return JSON.stringify(fields);
    })()
    """
    try:
        raw_schema = await page.evaluate(schema_js)
        form_schema = __import__('json').loads(raw_schema)
        print(f"[FORM] Extracted {len(form_schema)} input fields.")
        return form_schema
    except Exception as e:
        print(f"[FORM] ERROR extracting form schema: {e}")
        return None

async def get_gemini_answers(form_schema, kb: dict, client):
    print("[FORM] Asking Gemini to map Form Schema against Application Rules...")
    system_prompt = f"""You are an advanced AI application form filler.
You will receive a JSON array representing the fields on an application form.
Based on the applicant's Knowledge Base and Free Thinking Rules below, determine what value to input for each field.

=== RESUME & QA MATRIX ===
{kb.get('resume', '')}
{kb.get('interview_qa', '')}

=== APPLICATION RULES (FREE THINKING) ===
{kb.get('application_rules', '')}

INSTRUCTIONS:
1. Match each field in the schema to the correct applicant value.
2. For <select> drop-downs, your value MUST EXACTLY MATCH one of the strings in its "options" array.
3. If a field asks for target salary, use the application rules.
4. If you don't know the answer or a field should be left alone, omit it.
5. Provide your answers as a JSON map where keys are the exact CSS `selector` from the schema, and values are the string answers to inject.
6. RETURN ONLY VALID JSON. No markdown, no exposition.
"""
    try:
        # Generate the JSON string FIRST, then inject into prompt
        form_schema_json = __import__('json').dumps(form_schema, indent=2)
        user_prompt = f"FORM SCHEMA:\n{form_schema_json}"
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[system_prompt, user_prompt],
            config=__import__('google').generativeai.types.GenerateContentConfig(temperature=0.1, response_mime_type="application/json"),
        )
        llm_answers = __import__('json').loads(response.text.replace("```json", "").replace("```", "").strip())
        print(f"[FORM] Gemini returned answers for {len(llm_answers)} fields.")
        return llm_answers
    except Exception as e:
        print(f"[FORM] ERROR querying Gemini for form mapping: {e}")
        return None

async def inject_answers(page, llm_answers):
    print("[FORM] Injecting answers into DOM using Native Setters...")
    safely_encoded_answers = __import__('json').dumps(llm_answers).replace('\\\\', '\\\\\\\\').replace('`', '\\\\`').replace('$', '\\\\$')
    injection_js = f"""
    (() => {{
        const actions = JSON.parse(`{safely_encoded_answers}`);
        let successCount = 0;
        const nativeInputSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
        const nativeTextAreaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
        const nativeSelectSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value")?.set;

        for (const [selector, value] of Object.entries(actions)) {{
            const el = document.querySelector(selector);
            if (!el) continue;
            const tag = el.tagName.toLowerCase();
            let setter = null;
            if (tag === 'input' && nativeInputSetter) setter = nativeInputSetter;
            else if (tag === 'textarea' && nativeTextAreaSetter) setter = nativeTextAreaSetter;
            else if (tag === 'select' && nativeSelectSetter) setter = nativeSelectSetter;
            
            if (setter) {{ setter.call(el, value); }} else {{ el.value = value; }}
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            successCount++;
        }}
        return successCount;
    }})()
    """
    try:
        fields_filled = await page.evaluate(injection_js)
        print(f"[FORM] Successfully injected {fields_filled} fields.")
        return fields_filled
    except Exception as e:
        print(f"[FORM] ERROR executing injection JS: {e}")
        return 0

async def handle_linkedin_easy_apply(main_tab, job_id, queue, client, kb):
    max_steps = 10
    current_step = 0
    while current_step < max_steps:
        current_step += 1
        print(f"\\n[APPLY] --- LinkedIn Modal Step {current_step} ---")
        await asyncio.sleep(1.5)
        form_schema = await extract_form_schema(main_tab)
        if form_schema:
            ai_mapped_answers = await get_gemini_answers(form_schema, kb, client)
            if ai_mapped_answers:
                await inject_answers(main_tab, ai_mapped_answers)
                print("[APPLY] Injected AI answers via React bypass.")
        
        await asyncio.sleep(0.8)
        try:
            primary_btn = await main_tab.select('button.artdeco-button--primary', timeout=5)
            btn_text = await primary_btn.get_text()
            btn_text = btn_text.strip().lower()
            print(f"[APPLY] Found primary action button: '{btn_text}'")
            await primary_btn.mouse_click()
            print("[APPLY] Executed physical CDP click.")
        except Exception:
            print("[ERROR] Could not find a primary action button. Modal may have crashed.")
            queue.update_status(job_id, "FAILED", notes="Modal button timeout")
            return EXIT_FAILURE
            
        await asyncio.sleep(2.0)
        try:
            error_element = await main_tab.select('.artdeco-inline-feedback--error, [aria-invalid="true"]', timeout=1)
            print("[ERROR] React Validation Blocked Submission! Missing or invalid field.")
            queue.update_status(job_id, "FAILED", notes="LinkedIn form validation error")
            try:
                dismiss_btn = await main_tab.select('button[aria-label="Dismiss"]')
                await dismiss_btn.mouse_click()
                confirm_discard = await main_tab.select('button[data-control-name="discard_application_confirm_btn"]')
                await confirm_discard.mouse_click()
            except:
                pass
            return EXIT_FAILURE
        except Exception:
            pass
            
        if "submit" in btn_text or "apply" in btn_text:
            print("[SUCCESS] Application Submitted Successfully!")
            queue.update_status(job_id, "APPLIED", notes="Easy Apply completed successfully.")
            await asyncio.sleep(2)
            try:
                done_btn = await main_tab.select('button.artdeco-button--primary', timeout=2)
                await done_btn.mouse_click()
            except:
                pass
            return EXIT_SUCCESS
        elif "next" in btn_text or "continue" in btn_text:
            print(f"[APPLY] Progressing to next modal step ('{btn_text}')...")
            continue
        else:
            print(f"[ERROR] Unknown modal state or button Action: '{btn_text}'")
            queue.update_status(job_id, "FAILED", notes=f"Unknown Easy Apply modal progression state: {btn_text}")
            return EXIT_FAILURE

    print(f"[ERROR] Exceeded max modal steps ({max_steps}).")
    queue.update_status(job_id, "FAILED", notes="Exceeded max modal steps")
    return EXIT_FAILURE


async def fill_application_form(browser, page, analysis: dict, client, kb: dict):
    print("[FORM] Extracting actual Form Schema from DOM...")
    active_context = await get_execution_context(browser, page)
    
    form_schema = await extract_form_schema(active_context)
    if not form_schema:
        print("[FORM] No input fields found on this page.")
        return True

    llm_answers = await get_gemini_answers(form_schema, kb, client)
    if not llm_answers:
        print("[FORM] Gemini returned empty form mapping.")
        return True

    await inject_answers(active_context, llm_answers)

    await asyncio.sleep(1)
    print("[FORM] Checking for validation errors...")
    await asyncio.sleep(3)
    
    error_selectors = [".error-message", "[aria-invalid='true']", ".has-error", ".field-error"]
    for err_sel in error_selectors:
        try:
            err_elems = await active_context.query_selector_all(err_sel)
            if err_elems and len(err_elems) > 0:
                print(f"[FORM] ERROR: Validation errors found via {err_sel}. Form submission incomplete.")
                return False
        except Exception:
            pass

    print("[FORM] Form fill check complete with no obvious errors.")
    print("[FORM] Executing CDP Mouse Click Override (Datadome Safe)...")
    await asyncio.sleep(0.8)
    try:
        submit_btn = await active_context.select('button[type="submit"], input[type="submit"]', timeout=3)
        await submit_btn.mouse_click()
        print("[FORM] Natively clicked Submit button successfully via CDP.")
    except Exception as e:
        print(f"[FORM] Warning: Could not find strict submit via CDP. {e}")
        try:
            eval_click = """(() => { let btn = document.querySelector('button[type="submit"]') || Array.from(document.querySelectorAll('button')).find(el => el.textContent.trim().toLowerCase().includes('submit') || el.textContent.trim().toLowerCase().includes('apply')); if (btn) { btn.click(); return true; } return false; })()"""
            success = await active_context.evaluate(eval_click)
            if success:
                print("[FORM] Clicked using JS fallback.")
        except Exception:
            pass
    return True


async def take_screenshot(page, label: str):
    """Save a screenshot with a descriptive filename."""
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = SCREENSHOTS_DIR / f"{label}_{timestamp}.png"
    await page.save_screenshot(filename=str(filename))
    print(f"[SCREENSHOT] Saved: {filename}")
    return filename


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


async def apply_to_job_internal(page, browser, job_url: str, job_id: str, queue, client: genai.Client, kb: dict) -> int:
    """
    Main application flow for a single job inside an established tab.
    """
    print(f"\n{'='*60}")
    print(f"[JOB] Navigating to: {job_url}")
    print(f"{'='*60}")

    # Robust Proxy Retry Logic
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        await page.get(job_url)
        print("[JOB] Event-Driven: Waiting for body to render...")
        try:
            await page.select('body', timeout=15)
        except Exception:
            print("[JOB] Timeout waiting for body. Proceeding anyway.")
        
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
            
    try:
        final_url = await page.evaluate("window.location.href")
    except Exception:
        final_url = getattr(page.target, 'url', '')
        
    if 'chrome-error://' in str(final_url):
        print("[JOB] ERROR: Browser tab repeatedly crashed on navigation (chrome-error://chromewebdata).")
        return EXIT_FAILURE

    # Wait for page to fully load (LinkedIn is JS-heavy)
    print("[JOB] Event-Driven: Waiting for JD to load...")
    try:
        await page.select('h1, .jobs-description__content, [data-testid="job-description"], article, main', timeout=15)
    except Exception:
        print("[JOB] Timeout waiting for JD selector. Proceeding anyway.")

    # ─── Failsafe: Check if Job is Still Active ──────────────────────────────
    try:
        body_text = await page.evaluate("document.body.innerText")
        closed_phrases = [
            "No longer accepting applications",
            "This job is off the market",
            "This job is no longer available",
            "Job not found",
            "no longer accepting applications"
        ]
        if body_text and any(phrase in body_text for phrase in closed_phrases):
            print("[JOB] ERROR: LinkedIn indicates this job is no longer available/closed.")
            await take_screenshot(page, "job_unavailable_failsafe")
            return EXIT_FAILURE
    except Exception as e:
        print(f"[JOB] Warning: Could not verify job active status failsafe: {e}")
    # ─────────────────────────────────────────────────────────────────────────

    # Step 1: Scrape Job Description
    jd_text = await scrape_job_description(page)
    if not jd_text:
        print("[JOB] ERROR: No job description found — skipping")
        await take_screenshot(page, "no_jd")
        return EXIT_FAILURE

    # Sanitize JD to prevent prompt injection
    jd_text = sanitize_jd(jd_text)
    print(f"[JOB] JD sanitized ({len(jd_text)} chars)")

    # ─── The LLM Bouncer ─────────────────────────────────────────────────────
    print("[JOB] Running LLM Bouncer prescreen...")
    bouncer_verdict = await run_llm_bouncer(jd_text, client)
    if not bouncer_verdict.get("proceed", True):
        reason = bouncer_verdict.get('rejection_reason', 'Failed prescreen')
        print(f"[BOUNCER] Skipped: {reason}")
        await take_screenshot(page, "failed_prescreen")
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

    # Step 6: Extract External ATS Link
    print("[JOB] Hunting for external ATS Apply link...")
    try:
        external_url = await page.evaluate('''
            () => {
                let applyBtn = document.querySelector('a.apply-button') || document.querySelector('.jobs-apply-button') || Array.from(document.querySelectorAll('a')).find(el => el.textContent.trim().toLowerCase() === 'apply');
                if (applyBtn && applyBtn.href) {
                    return applyBtn.href;
                }
                return null;
            }
        ''')
    except Exception:
        external_url = None

    if external_url and 'linkedin.com' in external_url and 'sign-in' in external_url:
        print("[JOB] Cannot extract ATS link. Button leads to LinkedIn sign-in (likely Easy Apply).")
        await take_screenshot(page, "easy_apply_wall")
        return EXIT_FAILURE

    if not external_url:
        print("[JOB] WARNING: Could not find external Apply link. Checking for Easy Apply...")
        try:
            easy_apply_btn = await page.select('.jobs-apply-button--top-card button, button.jobs-apply-button', timeout=3)
            btn_text = await easy_apply_btn.get_text()
            if "apply" in btn_text.lower():
                print("[JOB] Found Easy Apply button. Launching modal loop...")
                await easy_apply_btn.mouse_click()
                return await handle_linkedin_easy_apply(page, job_id, queue, client, kb)
        except Exception:
            pass
            
        await take_screenshot(page, "no_external_link")
        return EXIT_FAILURE

    print(f"[JOB] Found ATS Link: {external_url}")
    print("[JOB] Pivoting to ATS...")
    
    # We navigate to the ATS link in the SAME tab so it doesn't open thousands of windows.
    await page.get(external_url)
    
    print("[JOB] Event-Driven: Waiting for ATS form to load...")
    try:
        await page.select('form, input, textarea, select', timeout=15)
    except Exception:
        print("[JOB] Timeout waiting for ATS form fields. Proceeding anyway.")
    
    try:
        current_ats_url = await page.evaluate("window.location.href")
    except Exception:
        current_ats_url = getattr(page.target, 'url', 'Unknown')
        
    print(f"[JOB] Arrived at ATS target: {current_ats_url}")
    await take_screenshot(page, "arrived_at_ats")
    
    # ─── Step 7: The ATS Whitelist ──────────────────────────────────────────
    ats_domain = urllib.parse.urlparse(current_ats_url).netloc
    
    # The Workday Trap / Blacklist
    if 'myworkdayjobs.com' in ats_domain or 'icims.com' in ats_domain:
        print(f"[JOB] SKIPPED — Hit ATS Blacklist ({ats_domain}). Account Creation Required. Aborting to save LLM credits.")
        raise Exception("Workday ATS Skipped")
        
    # The ATS Whitelist
    whitelist = ['greenhouse.io', 'lever.co', 'ashbyhq.com']
    if not any(w in ats_domain for w in whitelist):
        print(f"[JOB] WARNING — ATS ({ats_domain}) is not in Whitelist. Attempting generic form-fill, but success unlikely.")
    else:
        print(f"[JOB] SUCCESS — ATS ({ats_domain}) is Whitelisted for guest checkout!")

    # Step 8: JIT LLM API Generation
    print("[JOB] Validated ATS destination. Generating Just-In-Time Application Materials...")
    materials = generate_application_material(client, job_url, jd_text, kb)
    
    # State Injection
    analysis["generated_cover_letter"] = materials["generated_cover_letter"]
    analysis["qa_answers"] = materials["qa_answers"]
    
    # Step 9: Smart Adaptive Form Filling
    form_success = await fill_application_form(browser, page, analysis, client, kb)
    if not form_success:
        print("[JOB] ERROR: Failed cleanly during form fill phase.")
        return EXIT_FAILURE
    
    print("[JOB] ✅ ATS Direct routing, LLM generation, & Form filling successfully tested!")
    return EXIT_SUCCESS


async def run_apply(browser, main_tab, queue, client: genai.Client, kb: dict):
    pending_jobs = queue.get_pending_jobs()
    if not pending_jobs:
        print("[APPLY] No pending jobs. Skipping apply phase.")
        return

    for job_id, job_data in pending_jobs.items():
        print(f"\\n[{'='*60}]\\n[ORCHESTRATOR] Processing Job: {job_data['company']} - {job_data['title']}")
        try:
            exit_code = await apply_to_job_internal(main_tab, browser, job_data['url'], job_id, queue, client, kb)
            
            # Trust the exit_code returned from apply_to_job_internal.
            # Do NOT re-fetch status — handle_linkedin_easy_apply already updated it.
            if exit_code == EXIT_SUCCESS:
                queue.update_status(job_id, "APPLIED", notes="Successfully applied.")
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
            if main_tab:
                try:
                    await main_tab.get("about:blank")
                except Exception as eval_err:
                    print(f"[ORCHESTRATOR] Failed to navigate to about:blank on main_tab: {eval_err}")
                    
            jitter = random.uniform(3.5, 7.2)
            print(f"[ORCHESTRATOR] Tab loaded about:blank. State purged. Jittering for {jitter:.2f}s before next job...\\n")
            await asyncio.sleep(jitter)

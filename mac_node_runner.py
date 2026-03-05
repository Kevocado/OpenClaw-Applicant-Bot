import os
import json
import time
import asyncio
import sys
from pathlib import Path
import logging
import subprocess

from dotenv import load_dotenv
from google import genai

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Initialization
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Paths
KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
PAYLOAD_DIR = Path("./execution_payloads")
SCREENSHOTS_DIR = Path("./execution_screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)
MAX_RETRIES = 3

# ─── Knowledge Base & LLM JIT Generation ──────────────────────────────────────

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
        else:
            print(f"[MAC NODE] 🚨 CRITICAL ERROR: KB file missing: {filepath}")
    return kb

KB_DATA = load_knowledge_base()

def generate_application_material(client: genai.Client, job_url: str, job_description: str, knowledge_base: dict) -> dict:
    """
    Generate the exact Application Materials (Cover Letter, QAs) Just-In-Time.
    """
    system_prompt = f"""You are an expert career agent. Generate the exact application materials based on the provided documents.
=== RESUME ===
{knowledge_base.get('resume', '')}
=== COVER LETTER TEMPLATES ===
{knowledge_base.get('cover_letter_template', '')}
=== INTERVIEW Q&A MATRIX ===
{knowledge_base.get('interview_qa', '')}

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
            print(f"[MAC NODE] JIT Generation via {model_name}...")
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
            print(f"[MAC NODE] Generation error on {model_name}: {e}")
            
    return {"generated_cover_letter": "", "qa_answers": {}}

# ──────────────────────────────────────────────────────────────────────────────
PAYLOAD_DIR = Path("./execution_payloads")

async def clear_overlays(page):
    """Detects and closes common blocking overlays."""
    overlays = [
        "button[aria-label='Dismiss']", 
        "button.artdeco-modal__dismiss", 
        ".login-bg", # LinkedIn login wall
        "button:has-text('Accept Cookies')"
    ]
    for selector in overlays:
        try:
            if await page.is_visible(selector, timeout=500):
                await page.click(selector)
                print(f"[MAC NODE] Cleared overlay: {selector}")
        except:
            pass

async def process_payload(payload_path: Path):
    """
    Reads a dispatched payload and uses Playwright to execute DOM manipulation.
    Implements file locking by renaming to .processing first.
    """
    processing_path = payload_path.with_suffix(".processing")
    try:
        # Atomic rename to acquire lock
        payload_path.rename(processing_path)
    except FileNotFoundError:
        # Another worker grabbed it
        return
        
    try:
        data = json.loads(processing_path.read_text(encoding="utf-8"))
        job_id = data.get("job_id")
        job_url = data.get("job_url")
        job_description = data.get("job_description", "")
        company = data.get("company")
        role = data.get("role")
        
        print(f"\n[MAC NODE] 🚀 Processing Payload: {company} - {role} ({job_id})")
        print(f"[MAC NODE] Navigating to target: {job_url}")
        
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            print("[MAC NODE] Launching persistent Chrome via Playwright...")
            # Create a folder in your project called 'bot_session'
            user_data_dir = os.path.abspath("./bot_session")
            
            # Launch with a persistent context
            context = await p.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"]
            )
            
            # Stealth evasion: scrub webdriver flags
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
            
            page = context.pages[0] if context.pages else await context.new_page()
            print(f"[MAC NODE] Navigating to: {job_url}")
            await page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)  # Let React Virtual DOM settle
            
            await clear_overlays(page)
            
            # Form schema extraction for debugging
            print("[MAC NODE] Extracting form schema...")
            # ─── NATIVE REACT DOM INJECTION ──────────────────────────────
            print("[MAC NODE] Page successfully loaded! Proceeding with JIT Gemini LLM Generation.")
            if not client:
                print("[MAC NODE] ❌ ERROR: GEMINI_API_KEY environment variable is not set. Cannot generate answers.")
                raise Exception("Missing API Key")
            
            materials = await asyncio.to_thread(
                generate_application_material, client, job_url, job_description, KB_DATA
            )
            
            cover_letter = materials.get("generated_cover_letter", "")
            qa_answers = materials.get("qa_answers", {})
            
            print("[MAC NODE] Injecting Cover Letter & Q&A Answers using native React Object bypass...")
            
            inject_payload = {
                "cover_letter": cover_letter,
                "qa_answers": qa_answers
            }
            
            submitted = await page.evaluate("""
            (payload) => {
                const { cover_letter, qa_answers } = payload;
                
                // The React 16+ State Bypass
                const setNativeValue = (element, value) => {
                    const valueSetter = Object.getOwnPropertyDescriptor(element.__proto__, 'value') ?
                        Object.getOwnPropertyDescriptor(element.__proto__, 'value').set :
                        Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value').set;
                        
                    let protoSetter;
                    if (element.tagName === 'TEXTAREA') {
                        protoSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                    } else if (element.tagName === 'INPUT') {
                        protoSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    }
                    
                    if (protoSetter && protoSetter !== valueSetter) {
                        protoSetter.call(element, value);
                    } else if (valueSetter) {
                        valueSetter.call(element, value);
                    } else {
                        element.value = value;
                    }
                    
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                };
                
                // Example logic to find a textarea for cover letter and inject
                const textareas = document.querySelectorAll('textarea');
                textareas.forEach(ta => {
                    // Primitive string matching to find cover letter boxes
                    if (ta.name.toLowerCase().includes('cover') || ta.id.toLowerCase().includes('cover')) {
                        setNativeValue(ta, cover_letter);
                    } else {
                        // Attempt to inject QA answers if keys roughly match names/labels
                        for (const [key, answer] of Object.entries(qa_answers)) {
                            if (ta.name.toLowerCase().includes(key.toLowerCase())) {
                                setNativeValue(ta, answer);
                            }
                        }
                    }
                });
                
                // Example logic to find input fields for QA
                const inputs = document.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"]');
                inputs.forEach(inp => {
                    for (const [key, answer] of Object.entries(qa_answers)) {
                        const nameMatch = inp.name && inp.name.toLowerCase().includes(key.toLowerCase());
                        const idMatch = inp.id && inp.id.toLowerCase().includes(key.toLowerCase());
                        const ariaMatch = inp.getAttribute('aria-label') && inp.getAttribute('aria-label').toLowerCase().includes(key.toLowerCase());
                        
                        if (nameMatch || idMatch || ariaMatch) {
                            setNativeValue(inp, answer);
                        }
                    }
                });
                
                // Form Submission
                const submitButtons = Array.from(document.querySelectorAll('button, input[type="submit"]')).filter(btn => {
                    const text = (btn.innerText || btn.value || '').toLowerCase();
                    return text.includes('submit') || text.includes('apply') || text.includes('next') || text.includes('continue');
                });
                
                if (submitButtons.length > 0) {
                    // Click the most likely submit button safely
                    submitButtons[submitButtons.length - 1].click();
                    return true;
                }
                return false;
            }
            """, inject_payload)
            # ─────────────────────────────────────────────────────────────
            
            await asyncio.sleep(4)
            print(f"[MAC NODE] Injection & Submission attempt completed. Did submit: {submitted}")
            
            if not submitted:
                raise Exception("Blocked by Overlay or Submit button not found")
            
            # Take verification screenshot
            screenshot_path = SCREENSHOTS_DIR / f"success_{job_id}_{int(time.time())}.png"
            await page.screenshot(path=str(screenshot_path))
            print(f"[MAC NODE] Saved verification screenshot to {screenshot_path}")
            
            await context.close()
        
        # Execution successful. Clean up payload.
        print(f"[MAC NODE] ✅ Execution successful. Purging payload.")
        processing_path.unlink()
        
    except Exception as e:
        print(f"[MAC NODE] ❌ Execution failed for {processing_path.name}: {e}")
        
        # Read retry count
        try:
            data = json.loads(processing_path.read_text(encoding="utf-8"))
            retries = data.get("retries", 0) + 1
            data["retries"] = retries
            data["last_error"] = str(e)
            
            if retries <= MAX_RETRIES:
                print(f"[MAC NODE] Retry {retries}/{MAX_RETRIES} backing off...")
                processing_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                # Back to queue
                processing_path.rename(processing_path.with_suffix(".json"))
                await asyncio.sleep(2 ** retries)  # Exponential backoff
            else:
                print(f"[MAC NODE] Max retries reached. Marking as failed.")
                failed_path = processing_path.with_suffix(".failed")
                processing_path.rename(failed_path)
        except Exception as inner_e:
            print(f"[MAC NODE] Critical failure updating retry count: {inner_e}")
            failed_path = processing_path.with_suffix(".failed")
            processing_path.rename(failed_path)


def pull_payloads_from_vps():
    """
    Uses native SCP over the Tailscale interface to fetch execution payloads
    from the Gateway VPS, and SSH to clean them up remotely.
    """
    VPS_ADDRESS = "root@100.86.28.66"
    REMOTE_PAYLOAD_DIR = "/root/OpenClaw-Applicant-Bot/execution_payloads/"
    IDENTITY_FILE = os.path.expanduser("~/.ssh/id_ed25519_openclaw")
    
    PAYLOAD_DIR.mkdir(exist_ok=True)
    
    try:
        # SCP all JSON payloads
        scp_cmd = [
            "scp", "-q", 
            "-i", IDENTITY_FILE,
            f"{VPS_ADDRESS}:{REMOTE_PAYLOAD_DIR}*.json", 
            f"./{PAYLOAD_DIR.name}/"
        ]
        result = subprocess.run(scp_cmd, capture_output=True, text=True)
        
        if result.returncode == 0 or "No such file or directory" in result.stderr:
            # Successfully pulled or nothing to pull. Clean up remote if we succeeded.
            if result.returncode == 0:
                ssh_cmd = [
                    "ssh", "-q", 
                    "-i", IDENTITY_FILE,
                    VPS_ADDRESS, 
                    f"rm -f {REMOTE_PAYLOAD_DIR}*.json"
                ]
                subprocess.run(ssh_cmd)
        else:
            print(f"[MAC NODE] SCP pull returned non-zero. stderr: {result.stderr.strip()}")
            
    except Exception as e:
        print(f"[MAC NODE] Network error during SCP pull: {e}")

async def poll_payload_directory():
    """
    Long-running daemon loop that fetches payloads over SSH,
    reads them locally, executes with Playwright, and cleans up.
    """
    print("[MAC NODE] 🛡️ OpenClaw Execution Node Online.")
    print(f"[MAC NODE] Polling VPS (100.86.28.66) for dispatched payloads...")
    
    PAYLOAD_DIR.mkdir(exist_ok=True)
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    
    while True:
        try:
            # 1. Fetch from Gateway
            pull_payloads_from_vps()
            
            # 2. Find pending JSON payloads locally
            payloads = list(PAYLOAD_DIR.glob("job_payload_*.json"))
            
            # 3. Process sequentially
            for payload in payloads:
                await process_payload(payload)
                
            # Sleep briefly before polling again (low CPU impact)
            await asyncio.sleep(5)
            
        except KeyboardInterrupt:
            print("\n[MAC NODE] Shutting down execution node gracefully...")
            break
        except Exception as e:
            err_str = str(e)
            print(f"[MAC NODE] Poller error: {err_str}")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(poll_payload_directory())

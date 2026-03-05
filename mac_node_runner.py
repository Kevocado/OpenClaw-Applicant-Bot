import os
import json
import time
import asyncio
from pathlib import Path

# Paths
PAYLOAD_DIR = Path("./execution_payloads")

async def process_payload(payload_path: Path):
    """
    Reads a dispatched payload and uses OpenClaw's clawbrowser skill
    to natively execute the DOM manipulation.
    """
    try:
        data = json.loads(payload_path.read_text(encoding="utf-8"))
        job_id = data.get("job_id")
        job_url = data.get("job_url")
        company = data.get("company")
        role = data.get("role")
        cover_letter = data.get("generated_cover_letter", "")
        qa_answers = data.get("qa_answers", {})
        
        print(f"\n[MAC NODE] 🚀 Processing Payload: {company} - {role} ({job_id})")
        print(f"[MAC NODE] Navigating to target: {job_url}")
        
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            print("[MAC NODE] Launching Chrome via Playwright...")
            # We run headful (headless=False) on the Mac Node for maximum residential fidelity
            browser = await p.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            # Stealth evasion: scrub webdriver flags
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
            
            page = await context.new_page()
            print(f"[MAC NODE] Navigating to: {job_url}")
            await page.goto(job_url, timeout=60000)
            await asyncio.sleep(5)  # Let React Virtual DOM settle
            
            # ─── NATIVE REACT DOM INJECTION ──────────────────────────────
            print("[MAC NODE] Injecting Cover Letter & Q&A Answers using native React Object bypass...")
            
            inject_payload = {
                "cover_letter": cover_letter,
                "qa_answers": qa_answers
            }
            
            await page.evaluate("""
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
                const inputs = document.querySelectorAll('input[type="text"]');
                inputs.forEach(inp => {
                    for (const [key, answer] of Object.entries(qa_answers)) {
                        if (inp.name.toLowerCase().includes(key.toLowerCase()) || inp.id.toLowerCase().includes(key.toLowerCase())) {
                            setNativeValue(inp, answer);
                        }
                    }
                });
            }
            """, inject_payload)
            # ─────────────────────────────────────────────────────────────
            
            await asyncio.sleep(3)
            print("[MAC NODE] Injection complete. Reviewing DOM...")
            await browser.close()
        
        # Execution successful. Clean up payload.
        print(f"[MAC NODE] ✅ Execution successful. Purging payload.")
        payload_path.unlink()
        
    except Exception as e:
        print(f"[MAC NODE] ❌ Execution failed for {payload_path.name}: {e}")
        # Rename to indicate failure so we don't infinitely retry
        failed_path = payload_path.with_suffix(".failed")
        payload_path.rename(failed_path)


async def poll_payload_directory():
    """
    Long-running daemon loop that monitors the Tailscale-synced payload directory.
    """
    print("[MAC NODE] 🛡️ OpenClaw Execution Node Online.")
    print(f"[MAC NODE] Polling directory for dispatched payloads: {PAYLOAD_DIR.absolute()}")
    
    PAYLOAD_DIR.mkdir(exist_ok=True)
    
    while True:
        try:
            # Find any pending JSON payloads that haven't failed
            payloads = list(PAYLOAD_DIR.glob("job_payload_*.json"))
            
            for payload in payloads:
                # Process sequentially to avoid overlap detection
                await process_payload(payload)
                
            # Sleep briefly before polling again (low CPU impact)
            await asyncio.sleep(3)
            
        except KeyboardInterrupt:
            print("\n[MAC NODE] Shutting down execution node gracefully...")
            break
        except Exception as e:
            print(f"[MAC NODE] Poller error: {e}")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(poll_payload_directory())

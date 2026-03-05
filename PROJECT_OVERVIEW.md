# OpenClaw Applicant Bot — Master Architecture Overview

> **Living Document** — Technical depth will be added to each section as we build through the implementation phases.

---

## 1. Infrastructure & Hosting (The Foundation)

- **Host:** Contabo Cloud VPS (€6.20/month — Ubuntu 24.04, 4 vCPU, 8GB RAM).
- **Execution Environment:** Bare-metal Python daemon (`auto_bridge.py`) running continuously in the background.
- **System Interactions & Safety:** 
  - `nodriver` is configured with `sandbox: False` to execute gracefully as `root` on the VPS container.
  - SSH X11 Forwarding (`ssh -X`) is utilized to tunnel the Chrome graphical interface to the local Mac for manual `login_helper.py` setup.
  - The internal `nodriver` connection timeout is patched (from 5 loops to 60 loops) to allow for remote X11 rendering latency over SSH.

---

## 2. The Intelligence Layer (The Brain)

- **LLM:** Google Gemini models (2.5-flash / 1.5-pro) routed via Respan API proxy for maximum observability.
- **Knowledge Base:** Local Markdown definitions (`knowledge_base/`):
  - `honest_resume.md`, `cover_letter_templates.md`, `interview_qa_matrix.md`, `project_context.md`.
- **The Bouncer (`run_llm_bouncer`):** A blistering fast, cheap pre-screening prompt that immediately rejects jobs with salaries under $60k, strict US Citizenship/sponsorship requirements, or incompatible boutique firms.
- **The Analyst (`analyze_job`):** Parses the Job Description for match scoring (1-10), extracts the exact ATS routing system, targets 5-8 priority keywords, and determines the company tier.
- **The Generator (`get_gemini_answers`):** Maps the extracted form schema (via CSS selectors) directly to Gemini to generate physical DOM injection answers.

---

## 3. The Orchestration Layer (`auto_bridge.py` & Queue)

The application has deliberately shifted from being orchestrated by n8n webhooks to a standalone, bulletproof Python daemon controlling a central queue (`queue_manager.py`).

### Phase 1 — Omni-Scout
- Navigates through predefined corporate filters on **Handshake** and **MigrateMate** (with LinkedIn scouting completely deprecated due to aggressive anti-bot countermeasures).
- Extracts viable URLs and adds them to a thread-safe JSON Queue (`job_queue.json`) managed by `FileLock`. Ensures duplicates are ignored.

### Phase 2 — The Apply Agent
- Pops pending jobs from the queue and navigates safely.
- Passes JD through the AI pipeline (Bouncer → Analyst → Generator).
- **ATS Whitelist Validation:** Only attempts to fill forms on trusted modern ATS systems (Greenhouse, Lever, Ashby, and LinkedIn Easy Apply). Hard-rejects legacy logic mazes like Workday or iCIMS.
- **Adaptive Form Injection:** Uses raw JavaScript DOM setters (`Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set`) to bypass React/Vue state protections on forms, ensuring the ATS natively registers the keystrokes.

---

## 4. The Execution Layer (Browser Sandbox)

To prevent the catastrophic profile corruption associated with multi-tab concurrency and race conditions, the bot operates aggressively on a **Single-Tab Sequential Execution** loop.

### Strict Profile Sandboxing
- A dedicated, completely self-contained Google Chrome profile is generated at `./bot_chrome_profile` (`USER_DATA_DIR`).
- **Initial Setup:** The `login_helper.py` script opens Handshake/MigrateMate over X11 forwarding from the VPS to allow physical 2FA authentication by the user. 
- **Persistence:** These cryptographically signed session cookies permanently authorize the bot's data-center IP address to operate natively without triggering bot-walls.
- **Pacing:** Emulates human pacing by introducing variable jitter (3-7s) between physical clicks and utilizing massive 30-minute rest periods between index sweeps.

---

## Technical Depth Log

> _Entries added as each phase is built._

| Date | Phase | Notes |
|------|-------|-------|
| 2026-03-01 | Phase 0 | Repo scaffolded, `knowledge_base/` populated. Orchestration originally planned exclusively for n8n. |
| 2026-03-03 | Phase 1 | Python logic implemented. Reverted from Multi-Tab Concurrency to a safer Single-Tab Sequential Execution engine to completely eliminate state/session corruption. |
| 2026-03-04 | Phase 2 | VPS deployment. Configured X11 forwarding to bypass bot-walls via physical authentication (`login_helper.py`), patched `nodriver` root crashes (`sandbox: False`), and extended the `nodriver` connection timeout loop to account for X11 remote rendering latency. Migrated LLM clients to GenAI 0.6+ schema. |

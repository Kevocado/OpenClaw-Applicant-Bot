# OpenClaw Applicant Bot — Master Architecture Overview

> **Living Document** — Technical depth will be added to each section as we build through the implementation phases.

---

## 1. Infrastructure & Hosting (The Foundation)

- **Host:** Contabo Cloud VPS (€6.20/month — Ubuntu 24.04, 4 vCPU, 8GB RAM).
- **Environment:** Docker installed to run n8n safely in a container.
- **Security — OpenClaw:** Runs directly on the VPS, locked down via `openclaw.json`:
  - Binds to **loopback only** (`127.0.0.1`) — not exposed to the internet.
  - Requires **token authentication** for every request.
  - Human-in-the-loop approval for `exec` tool (`"ask": "always"`).
  - Risky tools (`nodes`, `canvas`, `llm_task`, `browser`, `computer`) explicitly denied.

---

## 2. The Intelligence Layer (The Brain)

- **LLM:** Google Gemini Pro (via free API key).
- **Knowledge Base:** Three local files (`knowledge_base/`) that Gemini reads to prevent hallucination:
  - `honest_resume.txt` — Factual resume with honest WOW Payments framing.
  - `cover_letter_templates.txt` — Master template with tone/length rules per industry.
  - `interview_qa_matrix.txt` — Pre-validated answers for common application questions.
- **Core Function — `analyze_job()`:** Returns strict JSON:
  ```json
  {
    "visa_eligible": true,
    "company_tier": "High",
    "generated_cover_letter": "...",
    "qa_answers": { ... }
  }
  ```
- **Visa Gatekeeper:** Flags `visa_eligible: false` if JD explicitly denies OPT/CPT or requires US Citizenship.
- **Company Tier System:**
  - **"High"** = MBB (McKinsey, BCG, Bain), Big 4, Capital One, top finance/consulting → **pauses for Telegram approval**.
  - **"Standard"** = all other companies → **auto-submits**.
- **Cover Letter Rules:** 200–300 words based on company type. Must inject $3.05M DOT Foods savings and 100+ WOW Payments field conversations.

---

## 3. The Orchestration Layer (n8n Workflows)

### Workflow A — The Inbox Backtracker
- **Trigger:** Gmail Trigger Node monitors for "Thank you for applying" emails.
- **Processing:** Code Node uses Regex to extract **Company**, **Role**, and **Location**.
- **Output:** Google Sheets Node appends to the "Consulting & Analytics Summer 2026 Internship Tracker".

### Workflow B — The Application Engine
- **Trigger:** Schedule Trigger at **2:00 AM** nightly.
- **Processing:** Fetches queued job links from Google Sheet, loops through each.
- **Output:** Triggers OpenClaw to run `apply_agent.py` per job.

### Workflow C — The Telegram Gatekeeper
- **Trigger:** `apply_agent.py` exits with code `2` (High-tier company paused).
- **Processing:** n8n reads `pending_approvals.json`, sends generated cover letter to Telegram.
- **Approval:** User taps "Approve" → n8n tells OpenClaw to resume and submit.

---

## 4. The Execution Layer (OpenClaw + nodriver)

### State Management
- **nodriver** (undetected Chrome automation) runs in **headed mode** with a **persistent profile**.
- Saved session cookies keep LinkedIn and Handshake logged in without 2FA every night.

### Application Flow
1. Navigate to job URL → scrape Job Description text.
2. Call `analyze_job()` → get visa eligibility, company tier, cover letter, QA answers.
3. If `visa_eligible == false` → log "Skipped - Visa", close tab, move on.
4. If `company_tier == "High"` → save assets to `pending_approvals.json` → `sys.exit(2)` for Telegram approval.
5. If `company_tier == "Standard"` → auto-fill form via CSS selectors → submit.

### Error Handling
- `try/except` blocks catch CAPTCHAs, timeouts, and unexpected DOM states.
- On failure: screenshot → `screenshots/` → print error code → `sys.exit(1)`.

---

## Technical Depth Log

> _Entries added as each phase is built._

| Date | Phase | Notes |
|------|-------|-------|
| 2026-03-01 | Phase 0 | Repo scaffolded, knowledge_base/ populated, pushed to GitHub |

# OpenClaw Applicant Bot — Master Architecture Overview

> **Living Document** — Technical depth will be added to each section as we build through the five implementation phases.

---

## 1. Infrastructure & Hosting (The Foundation)

- **Host:** Contabo Cloud VPS ($5–$6/month) running Ubuntu Linux.
- **Environment:** Docker installed to run n8n safely in a container.
- **Security:** OpenClaw runs directly on the VPS but is strictly locked down:
  - `openclaw.json` requires human-in-the-loop approvals for shell executions (`"approvals": { "exec": { "enabled": true } }`)
  - Only the `exec` tool is permitted; risky tools (`nodes`, `canvas`, `llm_task`, `browser`, `computer`) are explicitly denied.

---

## 2. The Intelligence Layer (The Brain)

- **LLM:** Google Gemini Pro (via free API key).
- **Role:**
  - Analyzes messy HTML DOMs to find "Apply" buttons and form field selectors.
  - Reads Job Descriptions (JDs) and classifies F-1/OPT/CPT eligibility.
- **Content Generation:**
  - Generates concise (max 250 words) cover letters using the candidate's specific templates.
  - Leads with **$3.05M net savings identified at DOT Foods**.
  - Highlights **100+ field sales conversations at WOW Payments**.
  - Mentions **F-1 STEM OPT eligibility (36 months)** if the JD references international students.

---

## 3. The Orchestration Layer (n8n Workflows)

### Workflow A — The Inbox Backtracker
- **Trigger:** Gmail Trigger Node continuously monitors for "Thank you for applying" emails.
- **Processing:** A Code Node parses the email body using Regex to extract **Company**, **Role**, and **Location**.
- **Output:** Google Sheets Node appends a new row to the "Consulting & Analytics Summer 2026 Internship Tracker".

### Workflow B — The Batch Scheduler
- **Trigger:** Schedule Trigger fires at **2:00 AM** nightly.
- **Processing:** Fetches queued job links from the Google Sheet, loops through them one by one.
- **Output:** Sends a webhook or command to OpenClaw to begin applying to each job.

---

## 4. The Execution Layer (OpenClaw + Playwright)

### State Management
- Playwright runs in **headed mode** (`headless=False`) to bypass basic bot detection.
- Uses a **persistent `user_data_dir`** to load saved cookies — stays logged into LinkedIn and Handshake without triggering 2FA every night.

### Visa Gatekeeper
- Scrapes the JD text from the job posting page.
- Asks Gemini: _"Does this explicitly require US Citizenship or deny OPT/CPT?"_
- If **yes** → closes the tab, logs `"Skipped - Visa"` in the Google Sheet, moves on.

### Dynamic Application
- If eligible → asks Gemini to map candidate skills (Python, SQL, Tableau) to the JD.
- Generates the tailored cover letter.
- Fills out the application form using CSS selectors identified by Gemini from the page DOM.
- Submits the application.

### Error Handling
- `try/except` blocks catch CAPTCHAs, timeouts, and visa rejections.
- On failure: takes a screenshot → saves to `screenshots/` → prints an error code → calls `sys.exit(1)` so n8n can catch the failure and continue the loop.

---

## Technical Depth Log

> _Entries will be added below as each phase is implemented._

| Date | Phase | Notes |
|------|-------|-------|
| — | — | _No entries yet_ |

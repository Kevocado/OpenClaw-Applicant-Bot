# OpenClaw Applicant Bot

An autonomous job application and tracking agent powered by **n8n**, targeted Headless **Playwright**, and **Google Gemini Pro** via a distributed architecture.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    Contabo VPS (Ubuntu 24.04)                  │
│                                                                │
│  ┌──────────────┐    ┌─────────────────────────────────────┐  │
│  │   n8n         │    │ Gateway (apply_agent.py)            │  │
│  │  (Docker)     │───▶│ Generates job_payload_[ID].json     │  │
│  │  Port 5678    │    └──────────────┬──────────────────────┘  │
│  └──────┬───────┘                    │                         │
│         │                            ▼                         │
│  ┌──────┴───────┐    ┌─────────────────────────────────────┐  │
│  │ Gmail + Sheets│    │ Tailscale Network (100.x.x.x)       │  │
│  │ (Workflows)   │    │ Secure payload delivery             │  │
│  └──────────────┘    └──────────────┬──────────────────────┘  │
│         │                           │                          │
│         ▼                           ▼                          │
│  ┌──────────────┐    ┌─────────────────────────────────────┐  │
│  │ Google Sheets │    │ macOS Execution Node                │  │
│  │ (Tracker)     │    │ mac_node_runner.py (Playwright)     │  │
│  └──────────────┘    └─────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

## How It Works

| Company Tier | Action |
|---|---|
| **Standard** | Auto-fills form + submits (dry-run by default) |
| **High** (MBB, Big 4, Capital One, etc.) | Pauses → saves to `pending_approvals.json` → Telegram notification → waits for your approval |
| **Visa Ineligible** | Skips → logs "Skipped - Visa" → moves on |

## Project Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Scaffolding & Knowledge Base | ✅ Complete |
| 1 | Code Implementation | ✅ Complete |
| 2 | VPS Provisioning | ⬜ Not started |
| 3 | Connect Accounts & Services | ⬜ Not started |
| 4 | Activate n8n Workflows | ⬜ Not started |

## Prerequisites

- **Python 3.10+**
- **Docker & Docker Compose**
- **Playwright Chromium** (`playwright install chromium`)
- **Accounts:** Google Cloud (OAuth), Gemini API, Telegram, LinkedIn, Handshake

## Quick Start

```bash
# Clone the repo
git clone https://github.com/Kevocado/OpenClaw-Applicant-Bot.git
cd OpenClaw-Applicant-Bot

# Install Python dependencies
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env
# Edit .env with your API keys

# Start n8n (Docker)
docker compose up -d

# Test the agent (dry-run mode)
python apply_agent.py "https://example.com/job-posting"
```

## Repository Structure

```
OpenClaw-Applicant-Bot/
├── PROJECT_OVERVIEW.md          # Living architecture doc
├── README.md                    # This file
├── apply_agent.py               # Browser agent (nodriver + Gemini)
├── docker-compose.yml           # n8n container config
├── n8n_email_parser.js          # n8n Code Node snippet
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variable template
├── .gitignore
├── knowledge_base/
│   ├── honest_resume.txt        # Factual resume data
│   ├── cover_letter_templates.txt  # Cover letter AI instructions
│   └── interview_qa_matrix.txt  # Q&A answer boundaries
├── screenshots/                 # Error screenshots (auto-generated)
└── pending_approvals.json       # High-tier jobs awaiting approval (auto-generated)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini Pro API key |
| `N8N_BASIC_AUTH_USER` | n8n web UI username |
| `N8N_BASIC_AUTH_PASSWORD` | n8n web UI password |
| `N8N_WEBHOOK_URL` | Public URL for n8n webhooks |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `USER_DATA_DIR` | Path to Chrome persistent profile |
| `GOOGLE_SHEET_ID` | Google Sheets tracker ID |

## Exit Codes

| Code | Meaning | n8n Routing |
|------|---------|-------------|
| `0` | Success — application submitted | Log success |
| `1` | Failure — error, visa skip, timeout | Log failure, continue loop |
| `2` | High-tier paused — awaiting approval | Route to Telegram Gatekeeper |

## License

Private — personal use only.

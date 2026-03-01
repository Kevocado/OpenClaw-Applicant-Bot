# OpenClaw Applicant Bot

An autonomous job application and tracking agent powered by **n8n**, **OpenClaw**, **Playwright**, and **Google Gemini Pro**.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Contabo VPS (Ubuntu)               │
│                                                      │
│  ┌──────────────┐    ┌──────────────────────────┐   │
│  │   n8n         │    │  OpenClaw                 │   │
│  │  (Docker)     │───▶│  (exec gateway)           │   │
│  │  Port 5678    │    │  human-approval gating    │   │
│  └──────┬───────┘    └──────────┬───────────────┘   │
│         │                       │                    │
│         ▼                       ▼                    │
│  ┌──────────────┐    ┌──────────────────────────┐   │
│  │ Gmail + Sheets│    │ apply_agent.py            │   │
│  │ (Workflows)   │    │ Playwright + Gemini Pro   │   │
│  └──────────────┘    └──────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Project Status

🚧 **Phase 0 — Scaffolding** (current)

See [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) for the full architecture narrative and [implementation phases](#phases).

## Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Infrastructure & Hosting | ⬜ Not started |
| 2 | Intelligence Layer (Gemini) | ⬜ Not started |
| 3 | Orchestration (n8n Workflows) | ⬜ Not started |
| 4 | Execution (Playwright + OpenClaw) | ⬜ Not started |
| 5 | Testing & Hardening | ⬜ Not started |

## Prerequisites

- Python 3.10+
- Docker & Docker Compose
- Node.js (for n8n)
- Google Gemini API key
- Contabo VPS (Ubuntu) or equivalent Linux host

## Quick Start

> _Setup instructions will be filled in as each phase is implemented._

```bash
# Clone the repo
git clone https://github.com/Kevocado/OpenClaw-Applicant-Bot.git
cd OpenClaw-Applicant-Bot

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Copy and fill in environment variables
cp .env.example .env

# Start n8n
docker compose up -d
```

## Environment Variables

See [`.env.example`](.env.example) for all required variables.

## License

Private — personal use only.

# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed
- **Distributed Architecture Pivot**: Decoupled the central orchestration Brain (Contabo VPS) from the browser execution Hands (Local macOS) to effectively bypass Datacenter WAF blocks and leverage residential IPs.
- **Stateless HTTP Scraping Module**: Replaced `nodriver` with pure HTTP `requests` and Python Playwright headless instances to execute the React SPA scraping logic efficiently on the Ubuntu VPS.
- **Mac Execution Node (`mac_node_runner.py`)**: Designed a pure-Python edge deployment daemon running `playwright`. 
    - Fetches execution instructions using native SCP protocols over a secure Tailscale link.
    - **Just-In-Time Generation**: Validates that target ATS pages render successfully via Playwright *before* requesting Cover Letters and QA matrices via the Gemini API natively on the Macbook, drastically saving LLM token credits on dead job application URLs.
    - Synchronizes state using atomic filesystem locks (`.processing`).
    - Imposes exponential retry backoffs to guarantee resilience against temporary UI errors.
    - Dynamically injects cover letters and QA values into complex React applications via `page.evaluate()` closures, utilizing `Object.getOwnPropertyDescriptor().set` to trigger state validations silently.
- **Strict Payload Validation**: Hardened the Python Gateway on the VPS to enforce string and dict mapping typings upon the LLM output before generating instructions, drastically preventing invalid JSON crashes on the downstream node.
- **Artifacts Tracking Ignored**: Ignored `/execution_payloads` and `/execution_screenshots` locally via `.gitignore` to prevent leaking private residential snapshots into GitHub tracking.

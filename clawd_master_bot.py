import asyncio
import json
import os
import sys
import logging
import subprocess
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING
)

CLAWD_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_clawd_master") or os.getenv("TELEGRAM_BOT_TOKEN_CLAWD_MASTER")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROJECT_ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
SEARCH_QUERIES_FILE = PROJECT_ROOT / "search_queries.json"
QUEUE_FILE = PROJECT_ROOT / "job_queue.json"
SCORE_FILE = PROJECT_ROOT / "score_threshold.txt"
RULES_FILE = PROJECT_ROOT / "knowledge_base" / "application_rules.json"
RESUME_FILE = PROJECT_ROOT / "knowledge_base" / "honest_resume.md"

# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_queries() -> list:
    try:
        return json.loads(SEARCH_QUERIES_FILE.read_text())
    except Exception:
        return []

def save_queries(queries: list):
    SEARCH_QUERIES_FILE.write_text(json.dumps(queries, indent=4))

def get_score_threshold() -> int:
    try:
        return int(SCORE_FILE.read_text().strip())
    except Exception:
        return 9

def set_score_threshold(val: int):
    SCORE_FILE.write_text(str(val))

def load_queue_stats() -> dict:
    try:
        queue = json.loads(QUEUE_FILE.read_text())
        stats = {}
        for job in queue.values():
            s = job.get("status", "UNKNOWN")
            stats[s] = stats.get(s, 0) + 1
        return stats
    except Exception:
        return {}

def is_authorized(update: Update) -> bool:
    chat_id = str(update.effective_chat.id)
    authorized = chat_id == str(TELEGRAM_CHAT_ID)
    if not authorized:
        print(f"[CLAWD] ⚠️ Unauthorized from chat_id: {chat_id} (expected: {TELEGRAM_CHAT_ID})")
    return authorized

# ─── Commands ────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "🤖 *ClawdMasterBot — Commands*\n\n"
    "📊 *Monitoring*\n"
    "  /status — Phase \\+ queue counts\n"
    "  /stats — Full queue breakdown\n\n"
    "⏯️ *Control*\n"
    "  /pause — Pause after current job\n"
    "  /resume — Resume the daemon\n\n"
    "🎯 *Score Threshold*\n"
    "  /getscore — Current minimum match score\n"
    "  /setscore `<1-10>` — Change minimum score\n\n"
    "🔍 *Search Queries*\n"
    "  /queries — List all active search terms\n"
    "  /addquery `<term>` — Add a search term\n"
    "  /removequery `<term>` — Remove a search term\n\n"
    "📋 *Rules \\& Resume*\n"
    "  /viewrules — Show application\\_rules.json\n"
    "  /viewresume — Show first 1500 chars of resume\n\n"
    "🔄 *Updates*\n"
    "  /update — git pull \\+ restart daemon with latest code\n"
    "  /restart — Restart daemon without pulling\n\n"
    "  /help — This message"
)

async def cmd_help(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def cmd_start(update, context, pause_event, daemon_status):
    chat_id = str(update.effective_chat.id)
    if not is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized. Your chat ID is `{chat_id}`.", parse_mode="Markdown")
        return
    await update.message.reply_text("👋 *ClawdMasterBot is online!*\n\nUse /help to see all commands.", parse_mode="Markdown")

async def cmd_status(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    paused = not pause_event.is_set()
    state = "⏸️ PAUSED" if paused else f"▶️ {daemon_status.get('phase', 'Running')}"
    stats = load_queue_stats()
    pending = stats.get("PENDING", 0)
    applied = stats.get("APPLIED", 0)
    failed = stats.get("FAILED", 0) + stats.get("FAILED_PRESCREEN", 0)
    threshold = get_score_threshold()
    await update.message.reply_text(
        f"🤖 *OpenClaw Status*\n\n"
        f"*State:* {state}\n"
        f"*Min Score:* {threshold}/10\n\n"
        f"📋 *Queue:*\n"
        f"  • Pending: {pending}\n"
        f"  • Applied: {applied}\n"
        f"  • Failed/Skipped: {failed}",
        parse_mode="Markdown"
    )

async def cmd_pause(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    pause_event.clear()
    daemon_status['phase'] = 'Paused'
    await update.message.reply_text("⏸️ *Bot paused.* Send /resume to continue.", parse_mode="Markdown")

async def cmd_resume(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    pause_event.set()
    daemon_status['phase'] = 'Running'
    await update.message.reply_text("▶️ *Bot resumed.* Next cycle will run shortly.", parse_mode="Markdown")

async def cmd_getscore(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    threshold = get_score_threshold()
    await update.message.reply_text(f"🎯 Current minimum match score: *{threshold}/10*\n\nUse `/setscore 8` to change it.", parse_mode="Markdown")

async def cmd_setscore(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/setscore 9`\n\nProvide a number between 1 and 10.", parse_mode="Markdown")
        return
    val = int(context.args[0])
    if not 1 <= val <= 10:
        await update.message.reply_text("❌ Score must be between 1 and 10.", parse_mode="Markdown")
        return
    set_score_threshold(val)
    await update.message.reply_text(f"✅ Minimum match score set to *{val}/10*.\n\nTakes effect on the next job evaluated.", parse_mode="Markdown")

async def cmd_queries(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    queries = load_queries()
    if not queries:
        await update.message.reply_text("No search queries found.")
        return
    lines = "\n".join(f"  `{i+1}.` {q}" for i, q in enumerate(queries))
    await update.message.reply_text(f"🔍 *Active Search Queries ({len(queries)}):*\n\n{lines}", parse_mode="Markdown")

async def cmd_addquery(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    if not context.args:
        await update.message.reply_text("Usage: `/addquery Data Engineer Intern`", parse_mode="Markdown")
        return
    term = " ".join(context.args)
    queries = load_queries()
    if term.lower() in [q.lower() for q in queries]:
        await update.message.reply_text(f"⚠️ `{term}` is already in the list.", parse_mode="Markdown")
        return
    queries.append(term)
    save_queries(queries)
    await update.message.reply_text(f"✅ Added `{term}`.\n\nTakes effect on the next scout cycle.", parse_mode="Markdown")

async def cmd_removequery(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    if not context.args:
        await update.message.reply_text("Usage: `/removequery Data Engineer Intern`", parse_mode="Markdown")
        return
    term = " ".join(context.args)
    queries = load_queries()
    new_queries = [q for q in queries if q.lower() != term.lower()]
    if len(new_queries) == len(queries):
        await update.message.reply_text(f"❌ `{term}` not found. Use /queries to see the list.", parse_mode="Markdown")
        return
    save_queries(new_queries)
    await update.message.reply_text(f"✅ Removed `{term}`.", parse_mode="Markdown")

async def cmd_stats(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    stats = load_queue_stats()
    total = sum(stats.values())
    lines = "\n".join(f"  • {k}: {v}" for k, v in sorted(stats.items()))
    await update.message.reply_text(f"📊 *Job Queue Stats* (Total: {total})\n\n{lines}", parse_mode="Markdown")

async def cmd_viewrules(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    try:
        content = RULES_FILE.read_text(encoding="utf-8")
        # Escape Markdown special chars for safe display
        await update.message.reply_text(f"📋 *application\\_rules.json:*\n\n```json\n{content[:3500]}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Could not read rules file: {e}")

async def cmd_viewresume(update, context, pause_event, daemon_status):
    if not is_authorized(update): return
    try:
        content = RESUME_FILE.read_text(encoding="utf-8")
        await update.message.reply_text(f"📄 *honest\\_resume.md* (first 1500 chars):\n\n{content[:1500]}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Could not read resume: {e}")

async def cmd_update(update, context, pause_event, daemon_status):
    """Run git pull then restart the daemon process in-place."""
    if not is_authorized(update): return
    await update.message.reply_text("🔄 Pulling latest code from GitHub...")
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "pull"],
            capture_output=True, text=True, timeout=30
        )
        output = (result.stdout + result.stderr).strip() or "No output."
        await update.message.reply_text(f"```\n{output[:1500]}\n```", parse_mode="Markdown")
        if "Already up to date" in output:
            await update.message.reply_text("✅ Already up to date. No restart needed.")
        else:
            await update.message.reply_text("✅ Update pulled! Restarting daemon now...")
            await asyncio.sleep(2)
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        await update.message.reply_text(f"❌ Update failed: {e}")

async def cmd_restart(update, context, pause_event, daemon_status):
    """Restart the daemon in-place without pulling."""
    if not is_authorized(update): return
    await update.message.reply_text("🔄 Restarting daemon...")
    await asyncio.sleep(2)
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ─── Entry Point ─────────────────────────────────────────────────────────────

async def run_clawd_bot(pause_event: asyncio.Event, daemon_status: dict):
    if not CLAWD_TOKEN:
        print("[CLAWD] WARNING: TELEGRAM_BOT_TOKEN_clawd_master not set. Control bot disabled.")
        return

    print(f"[CLAWD] Starting with token ...{CLAWD_TOKEN[-6:]} | Authorized chat: {TELEGRAM_CHAT_ID}")

    app = ApplicationBuilder().token(CLAWD_TOKEN).build()

    def make_handler(fn):
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await fn(update, context, pause_event, daemon_status)
        return handler

    handlers = [
        ("start",       cmd_start),
        ("help",        cmd_help),
        ("status",      cmd_status),
        ("pause",       cmd_pause),
        ("resume",      cmd_resume),
        ("getscore",    cmd_getscore),
        ("setscore",    cmd_setscore),
        ("queries",     cmd_queries),
        ("addquery",    cmd_addquery),
        ("removequery", cmd_removequery),
        ("stats",       cmd_stats),
        ("viewrules",   cmd_viewrules),
        ("viewresume",  cmd_viewresume),
        ("update",      cmd_update),
        ("restart",     cmd_restart),
    ]
    for cmd, fn in handlers:
        app.add_handler(CommandHandler(cmd, make_handler(fn)))

    print("[CLAWD] ✅ ClawdMasterBot control interface online.")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

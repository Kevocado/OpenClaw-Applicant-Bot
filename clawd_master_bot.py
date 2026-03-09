import asyncio
import json
import os
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING
)

CLAWD_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_clawd_master") or os.getenv("TELEGRAM_BOT_TOKEN_CLAWD_MASTER")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SEARCH_QUERIES_FILE = Path(PROJECT_ROOT) / "search_queries.json"
QUEUE_FILE = Path(PROJECT_ROOT) / "job_queue.json"

def load_queries() -> list:
    try:
        return json.loads(SEARCH_QUERIES_FILE.read_text())
    except Exception:
        return []

def save_queries(queries: list):
    SEARCH_QUERIES_FILE.write_text(json.dumps(queries, indent=4))

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
        print(f"[CLAWD] ⚠️ Unauthorized access attempt from chat_id: {chat_id} (expected: {TELEGRAM_CHAT_ID})")
    return authorized

# ─── Commands ────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "🤖 *ClawdMasterBot — Command Reference*\n\n"
    "📊 *Monitoring*\n"
    "  /status — Current phase \\+ queue counts\n"
    "  /stats — Full breakdown of all job statuses\n\n"
    "⏯️ *Control*\n"
    "  /pause — Pause after current job finishes\n"
    "  /resume — Resume the daemon\n\n"
    "🔍 *Search Queries*\n"
    "  /queries — List all active search terms\n"
    "  /addquery `<term>` — Add a new search term\n"
    "  /removequery `<term>` — Remove a search term\n\n"
    "❓ *Help*\n"
    "  /help — Show this message"
)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE, pause_event: asyncio.Event, daemon_status: dict):
    if not is_authorized(update): return
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE, pause_event: asyncio.Event, daemon_status: dict):
    """Always respond to /start to confirm the bot is alive."""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(update):
        await update.message.reply_text(f"⛔ Unauthorized. Your chat ID is `{chat_id}`.", parse_mode="Markdown")
        return
    await update.message.reply_text(
        "👋 *ClawdMasterBot is online!*\n\nUse /help to see all available commands.",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE, pause_event: asyncio.Event, daemon_status: dict):
    if not is_authorized(update): return
    paused = not pause_event.is_set()
    state = "⏸️ PAUSED" if paused else f"▶️ {daemon_status.get('phase', 'Running')}"
    stats = load_queue_stats()
    pending = stats.get("PENDING", 0)
    applied = stats.get("APPLIED", 0)
    failed = stats.get("FAILED", 0) + stats.get("FAILED_PRESCREEN", 0)
    await update.message.reply_text(
        f"🤖 *OpenClaw Status*\n\n"
        f"*State:* {state}\n\n"
        f"📋 *Queue:*\n"
        f"  • Pending: {pending}\n"
        f"  • Applied: {applied}\n"
        f"  • Failed/Skipped: {failed}",
        parse_mode="Markdown"
    )

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE, pause_event: asyncio.Event, daemon_status: dict):
    if not is_authorized(update): return
    pause_event.clear()
    daemon_status['phase'] = 'Paused'
    await update.message.reply_text("⏸️ *Bot paused.* The current job will finish, then the daemon will hold.\n\nSend /resume to continue.", parse_mode="Markdown")

async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE, pause_event: asyncio.Event, daemon_status: dict):
    if not is_authorized(update): return
    pause_event.set()
    daemon_status['phase'] = 'Running'
    await update.message.reply_text("▶️ *Bot resumed.* Scouting and applying will continue on the next cycle.", parse_mode="Markdown")

async def cmd_queries(update: Update, context: ContextTypes.DEFAULT_TYPE, pause_event: asyncio.Event, daemon_status: dict):
    if not is_authorized(update): return
    queries = load_queries()
    if not queries:
        await update.message.reply_text("No search queries found.")
        return
    lines = "\n".join(f"  `{i+1}.` {q}" for i, q in enumerate(queries))
    await update.message.reply_text(f"🔍 *Active Search Queries ({len(queries)}):*\n\n{lines}", parse_mode="Markdown")

async def cmd_addquery(update: Update, context: ContextTypes.DEFAULT_TYPE, pause_event: asyncio.Event, daemon_status: dict):
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
    await update.message.reply_text(f"✅ Added `{term}` to search queries.\n\nTakes effect on the next scout cycle.", parse_mode="Markdown")

async def cmd_removequery(update: Update, context: ContextTypes.DEFAULT_TYPE, pause_event: asyncio.Event, daemon_status: dict):
    if not is_authorized(update): return
    if not context.args:
        await update.message.reply_text("Usage: `/removequery Data Engineer Intern`", parse_mode="Markdown")
        return
    term = " ".join(context.args)
    queries = load_queries()
    new_queries = [q for q in queries if q.lower() != term.lower()]
    if len(new_queries) == len(queries):
        await update.message.reply_text(f"❌ `{term}` not found. Use /queries to see the current list.", parse_mode="Markdown")
        return
    save_queries(new_queries)
    await update.message.reply_text(f"✅ Removed `{term}` from search queries.", parse_mode="Markdown")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, pause_event: asyncio.Event, daemon_status: dict):
    if not is_authorized(update): return
    stats = load_queue_stats()
    total = sum(stats.values())
    lines = "\n".join(f"  • {k}: {v}" for k, v in sorted(stats.items()))
    await update.message.reply_text(
        f"📊 *Job Queue Stats* (Total: {total})\n\n{lines}",
        parse_mode="Markdown"
    )

# ─── Entry Point ─────────────────────────────────────────────────────────────

async def run_clawd_bot(pause_event: asyncio.Event, daemon_status: dict):
    """Run the ClawdMasterBot polling loop as an asyncio task."""
    if not CLAWD_TOKEN:
        print("[CLAWD] WARNING: TELEGRAM_BOT_TOKEN_clawd_master not set. Control bot disabled.")
        return

    print(f"[CLAWD] Starting with token ...{CLAWD_TOKEN[-6:]} | Authorized chat: {TELEGRAM_CHAT_ID}")

    app = ApplicationBuilder().token(CLAWD_TOKEN).build()

    def make_handler(fn):
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await fn(update, context, pause_event, daemon_status)
        return handler

    app.add_handler(CommandHandler("start", make_handler(cmd_start)))
    app.add_handler(CommandHandler("help", make_handler(cmd_help)))
    app.add_handler(CommandHandler("status", make_handler(cmd_status)))
    app.add_handler(CommandHandler("pause", make_handler(cmd_pause)))
    app.add_handler(CommandHandler("resume", make_handler(cmd_resume)))
    app.add_handler(CommandHandler("queries", make_handler(cmd_queries)))
    app.add_handler(CommandHandler("addquery", make_handler(cmd_addquery)))
    app.add_handler(CommandHandler("removequery", make_handler(cmd_removequery)))
    app.add_handler(CommandHandler("stats", make_handler(cmd_stats)))

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

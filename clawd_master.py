import json
import os
import subprocess
import re
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Explicitly load the cross-project .env file
load_dotenv("/root/OpenClaw-Applicant-Bot/.env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

chat_id_str = os.getenv("ALLOWED_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
ALLOWED_CHAT_ID = int(chat_id_str) if chat_id_str else 0

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel('gemini-2.5-flash')

# 🧠 THE MASTER REGISTRY
# Add future bots to this dictionary as you build them!
BOT_REGISTRY = {
    "applicant_bot": {
        "path": "/root/OpenClaw-Applicant-Bot/openclaw.json",
        "description": "Searches for jobs and applies to them."
    },
    # Example for the future:
    # "real_estate_bot": {
    #     "path": "/root/OpenClaw-RealEstate/target_zips.json",
    #     "description": "Scrapes apartment listings."
    # }
}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        print(f"⚠️ UNAUTHORIZED MESSAGE IGNORED: Received from Chat ID {update.effective_chat.id}, but expected {ALLOWED_CHAT_ID}")
        return

    user_text = update.message.text
    print(f"📩 Received authorized command from Kevin: {user_text}")
    await update.message.reply_chat_action(action="typing")

    # STEP 1: ROUTING - Which bot does Kevin want to talk to?
    routing_prompt = f"""
    The user request is: "{user_text}"
    Available bots: {list(BOT_REGISTRY.keys())}
    Which bot is the user trying to configure? Return ONLY the exact dictionary key string. 
    If the user is asking you to run a script, check logs, or execute a server command, return 'sys_command'.
    If unsure, return 'unknown'.
    """
    router_response = model.generate_content(routing_prompt).text.strip()
    
    if router_response == "sys_command":
        cmd_prompt = f"""
        The user wants to run a command on their Ubuntu VPS.
        User Request: "{user_text}"
        Return ONLY the raw bash command to execute. No markdown, no explanation.
        """
        cmd_to_run = model.generate_content(cmd_prompt).text.strip()
        cmd_to_run = re.sub(r"```bash|```", "", cmd_to_run).strip()
        
        try:
            result = subprocess.run(cmd_to_run, shell=True, capture_output=True, text=True, timeout=60, cwd="/root/OpenClaw-Applicant-Bot")
            out = result.stdout.strip()[-3000:] if result.stdout else "No standard output."
            err = result.stderr.strip()[-1000:] if result.stderr else ""
            
            msg = f"🖥️ <b>Command Executed:</b>\n<pre>{cmd_to_run}</pre>\n\n<b>Output:</b>\n<pre>{out}</pre>"
            if err:
                 msg += f"\n<b>Errors:</b>\n<pre>{err}</pre>"
            await update.message.reply_text(msg, parse_mode='HTML')
        except subprocess.TimeoutExpired:
            await update.message.reply_text(f"⚠️ <b>Command Timed Out (60s limit).</b>", parse_mode='HTML')
        except Exception as e:
            await update.message.reply_text(f"⚠️ <b>Command Failed:</b>\n<pre>{str(e)}</pre>", parse_mode='HTML')
        return

    if router_response not in BOT_REGISTRY:
        await update.message.reply_text("🤔 I'm not sure which bot you want to update. Please clarify.")
        return

    target_bot = BOT_REGISTRY[router_response]
    target_path = target_bot["path"]

    # STEP 2: LOAD & EDIT CONFIG
    try:
        with open(target_path, "r") as f:
            current_config = json.load(f)
            
        # Load the user's context from the knowledge base directory
        kb_text = ""
        try:
            repo_dir = os.path.dirname(target_path)
            kb_dir = os.path.join(repo_dir, "knowledge_base")
            if os.path.exists(kb_dir):
                for filename in os.listdir(kb_dir):
                    if filename.endswith(".txt"):
                        with open(os.path.join(kb_dir, filename), "r") as kb_file:
                            kb_text += f"\n--- {filename} ---\n{kb_file.read()}\n"
        except Exception as e:
            print(f"Warning: Could not load knowledge base: {e}")

        edit_prompt = f"""
        You are an intelligent configuration manager for the {router_response}.
        
        The user has provided their background context here:
        {kb_text}
        
        Current Config: {json.dumps(current_config)}
        
        User Request: "{user_text}"
        
        INSTRUCTIONS: 
        Analyze the User Request and the User's Background Context. If the user asks you to find the "best jobs" for them, or if their target roles don't match their context (e.g. they are a Data Analyst but the config says Software Engineer), aggressively rewrite the config's `target_roles` and `keywords` arrays to perfectly match their actual background and visa requirements!
        
        Return ONLY valid JSON with the requested updates. No markdown formatting.
        """
        
        edit_response = model.generate_content(edit_prompt).text.strip()
        clean_json = re.sub(r"```json|```", "", edit_response).strip()
        new_config = json.loads(clean_json)
        
        with open(target_path, "w") as f:
            json.dump(new_config, f, indent=4)
            
        # Push changes to GitHub
        try:
            repo_dir = os.path.dirname(target_path)
            subprocess.run(["git", "add", target_path], cwd=repo_dir, check=True)
            subprocess.run(["git", "commit", "-m", f"bot: auto-update {router_response} config via Telegram"], cwd=repo_dir, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=repo_dir, check=True)
            git_status = " 🐙 (Synced to GitHub)"
        except Exception as git_err:
            git_status = f" ⚠️ (Git Sync Failed: {git_err})"
            
        # Use HTML parsing to avoid strict MarkdownV2 escaping issues
        success_msg = f"✅ <b>{router_response} Updated!</b>{git_status}\n\n<pre><code class='language-json'>{json.dumps(new_config, indent=2)}</code></pre>"
        await update.message.reply_text(success_msg, parse_mode='HTML')

    except Exception as e:
        error_msg = f"⚠️ <b>Error:</b> {str(e)}"
        await update.message.reply_text(error_msg, parse_mode='HTML')

if __name__ == "__main__":
    print("🤖 Master ClawdBot Online.")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

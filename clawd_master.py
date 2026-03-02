import json
import os
import re
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID"))
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
        return

    user_text = update.message.text
    await update.message.reply_chat_action(action="typing")

    # STEP 1: ROUTING - Which bot does Kevin want to talk to?
    routing_prompt = f"""
    The user request is: "{user_text}"
    Available bots: {list(BOT_REGISTRY.keys())}
    Which bot is the user trying to configure? Return ONLY the exact dictionary key string. If unsure, return 'unknown'.
    """
    router_response = model.generate_content(routing_prompt).text.strip()
    
    if router_response not in BOT_REGISTRY:
        await update.message.reply_text("🤔 I'm not sure which bot you want to update. Please clarify.")
        return

    target_bot = BOT_REGISTRY[router_response]
    target_path = target_bot["path"]

    # STEP 2: LOAD & EDIT CONFIG
    try:
        with open(target_path, "r") as f:
            current_config = json.load(f)
            
        edit_prompt = f"""
        You are configuring the {router_response}.
        Current Config: {json.dumps(current_config)}
        User Request: "{user_text}"
        Return ONLY valid JSON with the requested updates. No markdown formatting.
        """
        
        edit_response = model.generate_content(edit_prompt).text.strip()
        clean_json = re.sub(r"```json|```", "", edit_response).strip()
        new_config = json.loads(clean_json)
        
        with open(target_path, "w") as f:
            json.dump(new_config, f, indent=4)
            
        await update.message.reply_text(f"✅ *{router_response} Updated!*\n\n```json\n{json.dumps(new_config, indent=2)}\n```", parse_mode='MarkdownV2')

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

if __name__ == "__main__":
    print("🤖 Master ClawdBot Online.")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

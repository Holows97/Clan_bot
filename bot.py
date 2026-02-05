#!/usr/bin/env python3
"""
BOT DEL CLAN - VERSIÓN RENDER.COM
Compatible con python-telegram-bot v20.7
"""
import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# ========== VERIFICAR VERSIÓN ==========
import telegram
print(f"🔍 VERSIÓN INSTALADA: {telegram.__version__}")
if telegram.__version__ != "20.7":
    print(f"❌ ERROR: Versión incorrecta. Se esperaba 20.7, se encontró {telegram.__version__}")
    print("💡 Render está usando caché vieja. Forzando reinstalación...")
else:
    print("✅ Versión correcta: 20.7")

TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    print("❌ ERROR: BOT_TOKEN no configurado")
    exit(1)
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

print("=" * 60)
print("🤖 BOT DEL CLAN INICIADO")
print(f"👑 Admin: {ADMIN_ID}")
print("=" * 50)

USERNAME, ATTACK, DEFENSE = range(3)
DATA_FILE = 'clan_data.json'

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("📊 Ranking", callback_data='ranking')],
        [InlineKeyboardButton("📝 Registrar cuenta", callback_data='register')],
        [InlineKeyboardButton("🆔 Mi ID", callback_data='getid')]
    ]
    if user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin", callback_data='admin')])
    await update.message.reply_text(
        f"¡Hola {user.first_name}! 🏰\n\nBot del Clan - Gestión de cuentas\nSelecciona una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def getid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(f"🆔 Tu ID: `{user.id}`", parse_mode='Markdown')

async def ranking_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data:
        msg = "📭 No hay cuentas registradas."
    else:
        all_accounts = []
        for user_data in data.values():
            all_accounts.extend(user_data.get('accounts', []))
        if not all_accounts:
            msg = "📭 No hay cuentas registradas."
        else:
            all_accounts.sort(key=lambda x: x.get('attack', 0), reverse=True)
            msg = "🏆 **RANKING** 🏆\n\n"
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            for i, acc in enumerate(all_accounts[:5]):
                if i < len(medals):
                    msg += f"{medals[i]} {acc['username']}\n⚔️ {acc.get('attack', 0):,} 🛡️ {acc.get('defense', 0):,}\n\n"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'ranking':
        await ranking_cmd(update, context)
    elif query.data == 'register':
        await query.edit_message_text("📍 Para registrar datos, ve al chat privado con el bot.")
    elif query.data == 'getid':
        await query.edit_message_text(f"🆔 Tu ID: `{query.from_user.id}`", parse_mode='Markdown')
    elif query.data == 'admin':
        if query.from_user.id == ADMIN_ID:
            data = load_data()
            total_accounts = sum(len(u['accounts']) for u in data.values())
            await query.edit_message_text(f"👑 **ADMIN PANEL**\n\n📊 Cuentas: {total_accounts}\n👥 Usuarios: {len(data)}", parse_mode='Markdown')
        else:
            await query.answer("⛔ Solo admin", show_alert=True)

def main():
    print("🚀 Iniciando bot...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getid", getid_cmd))
    app.add_handler(CommandHandler("ranking", ranking_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("✅ Bot listo. Iniciando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

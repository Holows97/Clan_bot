#!/usr/bin/env python3
"""
BOT DEL CLAN - VERSIÓN RENDER.COM
Simple y funcional
"""

import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    print("❌ ERROR: BOT_TOKEN no configurado en Render")
    exit(1)

ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

print("=" * 50)
print("🤖 BOT DEL CLAN INICIADO")
print(f"👑 Admin: {ADMIN_ID}")
print("=" * 50)

# Estados para registro
USERNAME, ATTACK, DEFENSE = range(3)

# Archivo de datos
DATA_FILE = 'data.json'

# ========== FUNCIONES DATOS ==========
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

# ========== COMANDOS ==========
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
        f"¡Hola {user.first_name}! 🏰\n\n"
        "Bot del Clan - Gestión de cuentas\n"
        "Selecciona una opción:",
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
        # Recolectar todas las cuentas
        all_accounts = []
        for user_data in data.values():
            all_accounts.extend(user_data.get('accounts', []))
        
        if not all_accounts:
            msg = "📭 No hay cuentas registradas."
        else:
            # Ordenar por ataque
            all_accounts.sort(key=lambda x: x.get('attack', 0), reverse=True)
            
            msg = "🏆 **RANKING** 🏆\n\n"
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            
            for i, acc in enumerate(all_accounts[:5]):
                if i < len(medals):
                    msg += f"{medals[i]} {acc['username']}\n"
                    msg += f"⚔️ {acc.get('attack', 0):,} 🛡️ {acc.get('defense', 0):,}\n\n"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')

# ========== REGISTRO ==========
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Envía el nombre de usuario de tu cuenta:")
    return USERNAME

async def get_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['username'] = update.message.text
    await update.message.reply_text("✅ Nombre guardado.\n\nAhora envía el ATAQUE (solo números):")
    return ATTACK

async def get_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        attack = int(update.message.text)
        context.user_data['attack'] = attack
        await update.message.reply_text(f"⚔️ Ataque: {attack:,}\n\nAhora envía la DEFENSA:")
        return DEFENSE
    except:
        await update.message.reply_text("❌ Solo números. Intenta de nuevo:")
        return ATTACK

async def get_defense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        defense = int(update.message.text)
        username = context.user_data['username']
        attack = context.user_data['attack']
        user_id = update.effective_user.id
        
        # Guardar
        data = load_data()
        user_key = str(user_id)
        
        if user_key not in data:
            data[user_key] = {'accounts': [], 'name': update.effective_user.first_name}
        
        # Buscar si ya existe
        for acc in data[user_key]['accounts']:
            if acc['username'] == username:
                acc.update({'attack': attack, 'defense': defense})
                break
        else:
            data[user_key]['accounts'].append({
                'username': username,
                'attack': attack,
                'defense': defense,
                'date': datetime.now().isoformat()
            })
        
        save_data(data)
        context.user_data.clear()
        
        await update.message.reply_text(
            f"✅ **¡Registrado!**\n\n"
            f"👤 {username}\n"
            f"⚔️ {attack:,}\n"
            f"🛡️ {defense:,}"
        )
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Error. Intenta de nuevo:")
        return DEFENSE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelado.")
    return ConversationHandler.END

# ========== ADMIN ==========
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo admin")
        return
    
    data = load_data()
    total_accounts = sum(len(u['accounts']) for u in data.values())
    
    await update.message.reply_text(
        f"👑 **ADMIN PANEL**\n\n"
        f"📊 Cuentas: {total_accounts}\n"
        f"👥 Usuarios: {len(data)}\n\n"
        "Para autorizar usuario:\n"
        "`/auth 123456789`",
        parse_mode='Markdown'
    )

async def auth_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo admin")
        return
    
    if not context.args:
        await update.message.reply_text("Uso: /auth <id_usuario>")
        return
    
    try:
        user_id = int(context.args[0])
        # En esta versión simple, todos pueden usar el bot
        await update.message.reply_text(f"✅ Usuario {user_id} puede usar el bot ahora.")
    except:
        await update.message.reply_text("❌ ID inválido")

# ========== HANDLER BOTONES ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'ranking':
        await ranking_cmd(update, context)
    elif query.data == 'register':
        if query.message.chat.type != "private":
            await query.edit_message_text("📍 Ve al privado para registrar: @tu_bot")
            return
        
        await query.edit_message_text("📝 Envía el nombre de usuario de tu cuenta:")
        context.user_data['state'] = 'username'
    elif query.data == 'getid':
        await query.edit_message_text(f"🆔 Tu ID: `{query.from_user.id}`", parse_mode='Markdown')
    elif query.data == 'admin':
        await admin_cmd(update, context)

# ========== HANDLER MENSAJES ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')
    
    if state == 'username':
        context.user_data['username'] = update.message.text
        context.user_data['state'] = 'attack'
        await update.message.reply_text("✅ Nombre guardado.\n\nEnvía el ATAQUE (número):")
    
    elif state == 'attack':
        try:
            attack = int(update.message.text)
            context.user_data['attack'] = attack
            context.user_data['state'] = 'defense'
            await update.message.reply_text(f"⚔️ Ataque: {attack:,}\n\nEnvía la DEFENSA:")
        except:
            await update.message.reply_text("❌ Solo números. Intenta de nuevo:")
    
    elif state == 'defense':
        try:
            defense = int(update.message.text)
            username = context.user_data['username']
            attack = context.user_data['attack']
            user_id = update.effective_user.id
            
            # Guardar
            data = load_data()
            user_key = str(user_id)
            
            if user_key not in data:
                data[user_key] = {'accounts': []}
            
            data[user_key]['accounts'].append({
                'username': username,
                'attack': attack,
                'defense': defense
            })
            
            save_data(data)
            context.user_data.clear()
            
            await update.message.reply_text(
                f"✅ **¡Registrado!**\n\n"
                f"👤 {username}\n"
                f"⚔️ {attack:,}\n"
                f"🛡️ {defense:,}"
            )
        except:
            await update.message.reply_text("❌ Error. Intenta de nuevo:")

# ========== MAIN ==========
def main():
    print("🚀 Iniciando bot...")
    
    app = Application.builder().token(TOKEN).build()
    
    # Conversación para registro
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('register', register_start)],
        states={
            USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_username)],
            ATTACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_attack)],
            DEFENSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_defense)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getid", getid_cmd))
    app.add_handler(CommandHandler("ranking", ranking_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("auth", auth_user))
    
    # Conversación y botones
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Mensajes normales
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Bot listo. Iniciando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN ==========
TOKEN = os.getenv('TELEGRAM_TOKEN', 'PON_TU_TOKEN_AQUI')
ADMIN_ID = int(os.getenv('ADMIN_USER_ID', '123456789'))

# Archivos de datos
DATA_FILE = 'clan_data.json'
USERS_FILE = 'auth_users.json'

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== FUNCIONES DE DATOS ==========
def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f).get('users', [ADMIN_ID])
    except:
        return [ADMIN_ID]

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump({'users': users}, f, indent=2)

# ========== COMANDOS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if user_id not in load_users():
        await update.message.reply_text(
            f"Hola {user.first_name}! 🔒\n\n"
            "ID necesario: `/getid`\n"
            "Envía tu ID al admin."
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Registrar cuenta", callback_data='register')],
        [InlineKeyboardButton("📊 Ver ranking", callback_data='ranking')],
        [InlineKeyboardButton("📋 Mis cuentas", callback_data='my_accounts')]
    ]
    
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin", callback_data='admin')])
    
    await update.message.reply_text(
        f"¡Hola {user.first_name}! 🏰\n\n"
        "Bot del Clan - Gestión de cuentas\n"
        "Selecciona una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 **Tu ID:** `{user.id}`\n\n"
        "📤 Envía este número al administrador.",
        parse_mode='Markdown'
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **BOT DEL CLAN**\n\n"
        "📋 Comandos:\n"
        "/start - Iniciar bot\n"
        "/getid - Obtener tu ID\n"
        "/help - Esta ayuda\n\n"
        "📍 En grupo: /ranking para ver top"
    )

async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    
    if not data:
        await update.message.reply_text("📭 No hay datos aún.")
        return
    
    # Calcular ranking
    all_accounts = []
    for user_id, user_data in data.items():
        for acc in user_data.get('accounts', []):
            all_accounts.append({
                'user': acc['username'],
                'attack': acc['attack'],
                'defense': acc['defense']
            })
    
    all_accounts.sort(key=lambda x: x['attack'], reverse=True)
    
    msg = "🏆 **RANKING DEL CLAN** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    
    for i, acc in enumerate(all_accounts[:5]):
        if i < len(medals):
            msg += f"{medals[i]} **{acc['user']}**\n"
            msg += f"   ⚔️ {acc['attack']:,}  🛡️ {acc['defense']:,}\n"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')

# ========== HANDLERS ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'ranking':
        await ranking(update, context)
    elif query.data == 'register':
        await register_account(update, context)
    elif query.data == 'admin':
        if query.from_user.id == ADMIN_ID:
            await admin_panel(update, context)

async def register_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text(
        "📝 **REGISTRO DE CUENTA**\n\n"
        "Envía el nombre de usuario de tu cuenta:"
    )
    context.user_data['state'] = 'awaiting_user'

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')
    
    if state == 'awaiting_user':
        context.user_data['username'] = update.message.text
        context.user_data['state'] = 'awaiting_attack'
        await update.message.reply_text("✅ Usuario guardado\n\nAhora envía el ATAQUE (número):")
    
    elif state == 'awaiting_attack':
        try:
            attack = int(update.message.text)
            context.user_data['attack'] = attack
            context.user_data['state'] = 'awaiting_defense'
            await update.message.reply_text(f"⚔️ Ataque: {attack:,}\n\nAhora envía la DEFENSA:")
        except:
            await update.message.reply_text("❌ Solo números. Intenta de nuevo:")
    
    elif state == 'awaiting_defense':
        try:
            defense = int(update.message.text)
            username = context.user_data['username']
            attack = context.user_data['attack']
            user_id = update.effective_user.id
            
            # Guardar datos
            data = load_data()
            user_str = str(user_id)
            
            if user_str not in data:
                data[user_str] = {'accounts': []}
            
            data[user_str]['accounts'].append({
                'username': username,
                'attack': attack,
                'defense': defense
            })
            
            save_data(data)
            context.user_data.clear()
            
            await update.message.reply_text(
                f"✅ **¡Cuenta registrada!**\n\n"
                f"👤 {username}\n"
                f"⚔️ {attack:,}\n"
                f"🛡️ {defense:,}"
            )
        except:
            await update.message.reply_text("❌ Error. Intenta de nuevo.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    data = load_data()
    total_accounts = sum(len(user['accounts']) for user in data.values())
    
    msg = f"👑 **PANEL ADMIN**\n\n"
    msg += f"📊 Total cuentas: {total_accounts}\n"
    msg += f"👥 Usuarios: {len(data)}\n\n"
    msg += "Para añadir usuario:\n"
    msg += "`/adduser 123456789`"
    
    await query.edit_message_text(msg, parse_mode='Markdown')

async def adduser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo admin")
        return
    
    if not context.args:
        await update.message.reply_text("Uso: /adduser <id>")
        return
    
    try:
        new_id = int(context.args[0])
        users = load_users()
        
        if new_id not in users:
            users.append(new_id)
            save_users(users)
            await update.message.reply_text(f"✅ Usuario {new_id} añadido")
        else:
            await update.message.reply_text("✅ Ya estaba autorizado")
    except:
        await update.message.reply_text("❌ ID inválido")

# ========== INICIAR BOT ==========
def main():
    print("🚀 Iniciando Bot del Clan...")
    
    app = Application.builder().token(TOKEN).build()
    
    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getid", getid))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ranking", ranking))
    app.add_handler(CommandHandler("adduser", adduser_cmd))
    
    # Botones
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Mensajes
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Bot listo. Iniciando...")
    app.run_polling()

if __name__ == '__main__':
    main()

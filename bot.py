#!/usr/bin/env python3
"""
BOT DEL CLAN - VERSIÓN FUNCIONAL
Compatible con python-telegram-bot v20.7
"""
import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ========== VERIFICAR VERSIÓN ==========
import telegram
print(f"🔍 VERSIÓN INSTALADA: {telegram.__version__}")
if telegram.__version__ != "20.7":
    print(f"❌ ERROR: Versión incorrecta. Se esperaba 20.7, se encontró {telegram.__version__}")
    exit(1)
else:
    print("✅ Versión correcta: 20.7")

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    print("❌ ERROR: BOT_TOKEN no configurado")
    exit(1)

ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

print("=" * 60)
print("🤖 BOT DEL CLAN INICIADO")
print(f"👑 Admin: {ADMIN_ID}")
print("=" * 60)

# Archivo de datos
DATA_FILE = 'clan_data.json'

def load_data():
    """Cargar datos del clan"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_data(data):
    """Guardar datos del clan"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except:
        return False

# ========== COMANDOS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    user = update.effective_user
    
    keyboard = [
        [InlineKeyboardButton("📊 Ranking", callback_data='ranking')],
        [InlineKeyboardButton("📝 Registrar", callback_data='register')],
        [InlineKeyboardButton("🆔 Mi ID", callback_data='getid')]
    ]
    
    if user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin", callback_data='admin')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"¡Hola {user.first_name}! 👋\n\n"
        "🏰 **Bot del Clan**\n"
        "Selecciona una opción:",
        reply_markup=reply_markup
    )

async def getid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /getid"""
    user = update.effective_user
    await update.message.reply_text(f"🆔 Tu ID: `{user.id}`", parse_mode='Markdown')

async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar ranking - funciona para comando y botón"""
    data = load_data()
    
    if not data:
        msg = "📭 No hay cuentas registradas aún."
    else:
        # Recolectar todas las cuentas
        all_accounts = []
        for user_data in data.values():
            accounts = user_data.get('accounts', [])
            all_accounts.extend(accounts)
        
        if not all_accounts:
            msg = "📭 No hay cuentas registradas."
        else:
            # Ordenar por ataque
            all_accounts.sort(key=lambda x: x.get('attack', 0), reverse=True)
            
            msg = "🏆 **RANKING DEL CLAN** 🏆\n\n"
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            
            for i, account in enumerate(all_accounts[:5]):
                if i < len(medals):
                    medal = medals[i]
                else:
                    medal = f"{i+1}."
                
                msg += f"{medal} **{account.get('username', 'Sin nombre')}**\n"
                msg += f"   ⚔️ {account.get('attack', 0):,}\n"
                msg += f"   🛡️ {account.get('defense', 0):,}\n"
                if i < 4 and i < len(all_accounts) - 1:
                    msg += "   ──────────────\n"
    
    # Determinar cómo responder
    if hasattr(update, 'callback_query') and update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar botones inline"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'ranking':
        await ranking_command(update, context)
    elif query.data == 'register':
        await query.edit_message_text(
            "📝 **Para registrar tu cuenta:**\n\n"
            "Envía este mensaje al bot:\n"
            "`/registrar <usuario> <ataque> <defensa>`\n\n"
            "Ejemplo: `/registrar GuerreroX 15000 12000`",
            parse_mode='Markdown'
        )
    elif query.data == 'getid':
        await query.edit_message_text(f"🆔 Tu ID: `{query.from_user.id}`", parse_mode='Markdown')
    elif query.data == 'admin':
        if query.from_user.id == ADMIN_ID:
            data = load_data()
            total_accounts = sum(len(u.get('accounts', [])) for u in data.values())
            await query.edit_message_text(
                f"👑 **PANEL ADMIN**\n\n"
                f"📊 Cuentas totales: {total_accounts}\n"
                f"👥 Usuarios activos: {len(data)}",
                parse_mode='Markdown'
            )
        else:
            await query.answer("⛔ Solo el administrador puede ver esto", show_alert=True)

async def registrar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /registrar"""
    if len(context.args) != 3:
        await update.message.reply_text(
            "❌ **Uso incorrecto**\n\n"
            "Formato: `/registrar <usuario> <ataque> <defensa>`\n\n"
            "Ejemplo: `/registrar MiGuerrero 15000 12000`",
            parse_mode='Markdown'
        )
        return
    
    try:
        username = context.args[0]
        attack = int(context.args[1])
        defense = int(context.args[2])
        user_id = update.effective_user.id
        
        # Validar datos
        if attack <= 0 or defense <= 0:
            await update.message.reply_text("❌ El ataque y defensa deben ser mayores a 0")
            return
        
        # Cargar y guardar datos
        data = load_data()
        user_key = str(user_id)
        
        if user_key not in data:
            data[user_key] = {
                'telegram_name': update.effective_user.first_name,
                'accounts': []
            }
        
        # Buscar si ya existe la cuenta
        accounts = data[user_key]['accounts']
        for i, acc in enumerate(accounts):
            if acc.get('username', '').lower() == username.lower():
                accounts[i] = {
                    'username': username,
                    'attack': attack,
                    'defense': defense
                }
                break
        else:
            accounts.append({
                'username': username,
                'attack': attack,
                'defense': defense
            })
        
        save_data(data)
        
        # Mostrar estadísticas
        total_accounts = len(accounts)
        user_attack_total = sum(acc.get('attack', 0) for acc in accounts)
        user_defense_total = sum(acc.get('defense', 0) for acc in accounts)
        
        await update.message.reply_text(
            f"✅ **¡Cuenta registrada!**\n\n"
            f"👤 **Usuario:** {username}\n"
            f"⚔️ **Ataque:** {attack:,}\n"
            f"🛡️ **Defensa:** {defense:,}\n\n"
            f"📊 **Tus estadísticas:**\n"
            f"• Cuentas: {total_accounts}\n"
            f"• Ataque total: {user_attack_total:,}\n"
            f"• Defensa total: {user_defense_total:,}",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text("❌ El ataque y defensa deben ser números enteros")
    except Exception as e:
        logging.error(f"Error en registro: {e}")
        await update.message.reply_text("❌ Error al registrar la cuenta")

# ========== MAIN ==========
def main():
    """Función principal"""
    print("🚀 Iniciando bot...")
    
    # Crear aplicación
    app = Application.builder().token(TOKEN).build()
    
    # Registrar handlers de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getid", getid_cmd))
    app.add_handler(CommandHandler("ranking", ranking_command))
    app.add_handler(CommandHandler("registrar", registrar_command))
    
    # Registrar handler de botones
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Bot configurado. Iniciando polling...")
    
    # Iniciar bot
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()

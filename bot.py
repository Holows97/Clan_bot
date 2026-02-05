#!/usr/bin/env python3
"""
BOT DEL CLAN - VERSIÓN 20.7 CORRECTA
NO usa Updater, usa Application
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
logger = logging.getLogger(__name__)

print("=" * 60)
print("🤖 BOT DEL CLAN - VERSIÓN 20.7")
print(f"✅ Token configurado: {'Sí' if TOKEN else 'No'}")
print(f"👑 Admin ID: {ADMIN_ID}")
print("=" * 60)

# Estados para conversación
USERNAME, ATTACK, DEFENSE = range(3)

# Archivo de datos
DATA_FILE = 'clan_data.json'

# ========== FUNCIONES DE DATOS ==========
def load_data():
    """Cargar datos del clan"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error cargando datos: {e}")
    return {}

def save_data(data):
    """Guardar datos del clan"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error guardando datos: {e}")
        return False

# ========== COMANDOS BÁSICOS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    user = update.effective_user
    
    keyboard = [
        [InlineKeyboardButton("📊 Ver ranking", callback_data='ranking')],
        [InlineKeyboardButton("📝 Registrar cuenta", callback_data='register')],
        [InlineKeyboardButton("🆔 Obtener mi ID", callback_data='getid')]
    ]
    
    if user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Panel Admin", callback_data='admin')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"¡Hola {user.first_name}! 👋\n\n"
        "🏰 **Bot del Clan** - Gestión de cuentas\n\n"
        "Selecciona una opción:",
        reply_markup=reply_markup
    )

async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /getid"""
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 **Tu ID de Telegram:**\n"
        f"`{user.id}`\n\n"
        "📤 Envía este número al administrador.",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help"""
    help_text = """
🤖 **BOT DEL CLAN - AYUDA** 🤖

**Comandos disponibles:**
/start - Menú principal
/getid - Obtener tu ID
/help - Esta ayuda
/ranking - Ver ranking del clan

**📝 Para registrar tu cuenta:**
1. Toca '📝 Registrar cuenta' en el menú
2. Sigue las instrucciones paso a paso
3. Tus datos se guardarán automáticamente

**🏆 El ranking se actualiza en tiempo real**
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ========== RANKING ==========
async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ranking"""
    data = load_data()
    
    if not data:
        message = "📭 **No hay cuentas registradas aún.**\n\n¡Sé el primero en registrar tu cuenta!"
    else:
        # Recolectar todas las cuentas
        all_accounts = []
        for user_data in data.values():
            accounts = user_data.get('accounts', [])
            for acc in accounts:
                all_accounts.append({
                    'username': acc.get('username', 'Sin nombre'),
                    'attack': acc.get('attack', 0),
                    'defense': acc.get('defense', 0)
                })
        
        if not all_accounts:
            message = "📭 **No hay cuentas registradas aún.**"
        else:
            # Ordenar por ataque (descendente)
            all_accounts.sort(key=lambda x: x['attack'], reverse=True)
            
            # Calcular totales
            total_attack = sum(acc['attack'] for acc in all_accounts)
            total_defense = sum(acc['defense'] for acc in all_accounts)
            
            # Construir mensaje
            message = "🏆 **RANKING DEL CLAN** 🏆\n\n"
            message += f"📊 **Total de cuentas:** {len(all_accounts)}\n"
            message += f"⚔️ **Ataque total:** {total_attack:,}\n"
            message += f"🛡️ **Defensa total:** {total_defense:,}\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n\n"
            
            # Mostrar top 5
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            
            for i, account in enumerate(all_accounts[:5], 1):
                medal = medals[i-1] if i <= 5 else f"{i}."
                message += f"{medal} **{account['username']}**\n"
                message += f"   ⚔️ {account['attack']:,}  🛡️ {account['defense']:,}\n"
                if i < min(5, len(all_accounts)):
                    message += "   ─────────────────\n"
            
            if len(all_accounts) > 5:
                message += f"\n📝 ... y {len(all_accounts) - 5} cuenta(s) más"
    
    # Enviar mensaje
    if update.callback_query:
        await update.callback_query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Actualizar", callback_data='ranking')],
                [InlineKeyboardButton("📝 Registrar cuenta", callback_data='register')]
            ])
        )
    else:
        await update.message.reply_text(
            message,
            parse_mode='Markdown'
        )

# ========== REGISTRO DE CUENTAS ==========
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Iniciar registro de cuenta"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "📝 **REGISTRO DE CUENTA**\n\n"
            "Por favor, envía el **nombre de usuario** de tu cuenta:\n\n"
            "Ejemplo: `Guerrero123`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "📝 **REGISTRO DE CUENTA**\n\n"
            "Por favor, envía el **nombre de usuario** de tu cuenta:\n\n"
            "Ejemplo: `Guerrero123`",
            parse_mode='Markdown'
        )
    
    return USERNAME

async def ask_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibir nombre de usuario"""
    username = update.message.text.strip()
    
    if len(username) < 3:
        await update.message.reply_text("❌ El nombre debe tener al menos 3 caracteres. Intenta de nuevo:")
        return USERNAME
    
    context.user_data['username'] = username
    
    await update.message.reply_text(
        f"👤 **Usuario:** {username}\n\n"
        "Ahora envía el **poder de ataque** (solo números):\n\n"
        "Ejemplo: `15000`",
        parse_mode='Markdown'
    )
    
    return ATTACK

async def ask_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibir ataque"""
    try:
        attack_text = update.message.text.replace(',', '').replace('.', '').strip()
        attack = int(attack_text)
        
        if attack <= 0:
            await update.message.reply_text("❌ El ataque debe ser mayor a 0. Intenta de nuevo:")
            return ATTACK
        
        context.user_data['attack'] = attack
        
        await update.message.reply_text(
            f"⚔️ **Ataque:** {attack:,}\n\n"
            "Ahora envía el **poder de defensa** (solo números):\n\n"
            "Ejemplo: `12000`",
            parse_mode='Markdown'
        )
        
        return DEFENSE
    
    except ValueError:
        await update.message.reply_text("❌ Por favor, envía solo números. Intenta de nuevo:")
        return ATTACK

async def ask_defense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibir defensa y guardar cuenta"""
    try:
        defense_text = update.message.text.replace(',', '').replace('.', '').strip()
        defense = int(defense_text)
        
        if defense <= 0:
            await update.message.reply_text("❌ La defensa debe ser mayor a 0. Intenta de nuevo:")
            return DEFENSE
        
        # Obtener datos del contexto
        username = context.user_data.get('username')
        attack = context.user_data.get('attack')
        user_id = update.effective_user.id
        
        if not username or not attack:
            await update.message.reply_text("❌ Error: Datos incompletos. Comienza de nuevo.")
            return ConversationHandler.END
        
        # Guardar en datos
        data = load_data()
        user_str = str(user_id)
        
        if user_str not in data:
            data[user_str] = {
                'telegram_name': update.effective_user.first_name,
                'accounts': []
            }
        
        # Verificar si ya existe la cuenta
        accounts = data[user_str]['accounts']
        account_updated = False
        
        for i, acc in enumerate(accounts):
            if acc.get('username', '').lower() == username.lower():
                accounts[i] = {
                    'username': username,
                    'attack': attack,
                    'defense': defense,
                    'updated': datetime.now().isoformat()
                }
                account_updated = True
                break
        
        if not account_updated:
            accounts.append({
                'username': username,
                'attack': attack,
                'defense': defense,
                'added': datetime.now().isoformat()
            })
        
        # Guardar datos
        save_data(data)
        
        # Limpiar contexto
        context.user_data.clear()
        
        # Preparar respuesta
        total_accounts = len(accounts)
        user_attack_total = sum(acc.get('attack', 0) for acc in accounts)
        user_defense_total = sum(acc.get('defense', 0) for acc in accounts)
        
        message = "✅ **¡Cuenta registrada exitosamente!**\n\n"
        message += f"📝 **Datos guardados:**\n"
        message += f"• 👤 Usuario: {username}\n"
        message += f"• ⚔️ Ataque: {attack:,}\n"
        message += f"• 🛡️ Defensa: {defense:,}\n\n"
        message += f"📊 **Tus estadísticas:**\n"
        message += f"• Cuentas registradas: {total_accounts}\n"
        message += f"• Ataque total: {user_attack_total:,}\n"
        message += f"• Defensa total: {user_defense_total:,}"
        
        # Teclado para siguientes acciones
        keyboard = [
            [
                InlineKeyboardButton("➕ Otra cuenta", callback_data='register'),
                InlineKeyboardButton("📊 Ver ranking", callback_data='ranking')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END
    
    except ValueError:
        await update.message.reply_text("❌ Por favor, envía solo números. Intenta de nuevo:")
        return DEFENSE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancelar registro"""
    context.user_data.clear()
    await update.message.reply_text("❌ Registro cancelado.")
    return ConversationHandler.END

# ========== PANEL ADMIN ==========
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Panel de administración"""
    if update.effective_user.id != ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("⛔ Solo administrador", show_alert=True)
        else:
            await update.message.reply_text("⛔ Solo el administrador puede acceder.")
        return
    
    data = load_data()
    
    # Calcular estadísticas
    total_members = len(data)
    total_accounts = sum(len(user.get('accounts', [])) for user in data.values())
    total_attack = 0
    total_defense = 0
    
    for user_data in data.values():
        for acc in user_data.get('accounts', []):
            total_attack += acc.get('attack', 0)
            total_defense += acc.get('defense', 0)
    
    message = "👑 **PANEL DE ADMINISTRACIÓN** 👑\n\n"
    message += "📈 **ESTADÍSTICAS DEL CLAN**\n"
    message += f"• 👥 Miembros activos: {total_members}\n"
    message += f"• 📊 Cuentas totales: {total_accounts}\n"
    message += f"• ⚔️ Ataque total: {total_attack:,}\n"
    message += f"• 🛡️ Defensa total: {total_defense:,}\n\n"
    
    message += "🛠️ **ACCIONES DISPONIBLES:**\n"
    message += "• `/adduser <id>` - Añadir usuario autorizado\n"
    message += "• `/users` - Ver lista de usuarios\n"
    message += "• `/backup` - Descargar backup de datos"
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🔄 Actualizar", callback_data='admin')],
            [InlineKeyboardButton("📊 Ver ranking", callback_data='ranking')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            message,
            parse_mode='Markdown'
        )

async def adduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Añadir usuario autorizado"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo el administrador puede usar este comando.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "📝 **Añadir usuario**\n\n"
            "Uso: `/adduser <id_usuario>`\n\n"
            "Ejemplo: `/adduser 123456789`",
            parse_mode='Markdown'
        )
        return
    
    try:
        new_user_id = int(context.args[0])
        # En esta versión simple, todos pueden usar el bot
        await update.message.reply_text(
            f"✅ El usuario `{new_user_id}` puede usar el bot.\n\n"
            "⚠️ **Nota:** En esta versión, el bot está abierto para todos.\n"
            "En futuras versiones se implementará control de acceso.",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ ID inválido. Debe ser un número.")

# ========== HANDLER DE BOTONES ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar botones inline"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == 'ranking':
        await ranking_command(update, context)
    elif data == 'register':
        await register_start(update, context)
    elif data == 'getid':
        await getid_command(update, context)
    elif data == 'admin':
        await admin_panel(update, context)
    elif data == 'help':
        await help_command(update, context)
    else:
        await query.edit_message_text(f"❌ Opción no reconocida: {data}")

# ========== FUNCIÓN PRINCIPAL ==========
def main():
    """Función principal - Iniciar bot"""
    print("🚀 Iniciando Bot del Clan...")
    
    # Crear aplicación (v20.7 - NO Updater)
    application = Application.builder().token(TOKEN).build()
    
    # Configurar conversación para registro
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('register', register_start),
            CallbackQueryHandler(register_start, pattern='^register$')
        ],
        states={
            USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_username)
            ],
            ATTACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_attack)
            ],
            DEFENSE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_defense)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # Registrar handlers de comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getid", getid_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ranking", ranking_command))
    application.add_handler(CommandHandler("adduser", adduser_command))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    # Registrar handler de conversación
    application.add_handler(conv_handler)
    
    # Registrar handler de botones
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Iniciar el bot
    print("✅ Bot configurado correctamente")
    print("🔄 Iniciando polling...")
    
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()

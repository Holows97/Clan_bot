#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT DEL CLAN - Versión para Render (webhook)
Lee configuración desde variables de entorno:
- TOKEN
- ADMIN_USER_ID
- WEBHOOK_URL
- PORT (opcional, por defecto 8443)
- DATA_DIR (opcional, por defecto /tmp/clan_bot)
"""

import logging
import json
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ================= CONFIGURACIÓN (desde env) =================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("La variable de entorno TOKEN no está definida.")

ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # Ej: https://mi-servicio.onrender.com/<token>
PORT = int(os.environ.get("PORT", "8443"))
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/clan_bot")

# Archivos de datos (ubicación en el contenedor)
DATA_FILE = os.path.join(DATA_DIR, "clan_data.json")
AUTHORIZED_USERS_FILE = os.path.join(DATA_DIR, "authorized_users.json")

# Configurar logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Asegurar directorio de datos
os.makedirs(DATA_DIR, exist_ok=True)

# ================= FUNCIONES DE DATOS =================
def load_authorized_users():
    """Cargar usuarios autorizados desde archivo"""
    try:
        if os.path.exists(AUTHORIZED_USERS_FILE):
            with open(AUTHORIZED_USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("authorized_ids", [ADMIN_USER_ID])
    except Exception as e:
        logger.error("Error cargando usuarios autorizados: %s", e)
    return [ADMIN_USER_ID]

def save_authorized_users(user_ids):
    """Guardar usuarios autorizados"""
    try:
        with open(AUTHORIZED_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump({"authorized_ids": user_ids}, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error("Error guardando usuarios: %s", e)
        return False

def is_user_authorized(user_id):
    """Verificar si usuario está autorizado"""
    authorized_ids = load_authorized_users()
    return user_id in authorized_ids

def is_admin(user_id):
    """Verificar si es administrador"""
    return user_id == ADMIN_USER_ID

def load_data():
    """Cargar datos del clan"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error("Error cargando datos: %s", e)
    return {}

def save_data(data):
    """Guardar datos del clan"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error("Error guardando datos: %s", e)
        return False

def get_user_accounts(user_id):
    """Obtener cuentas de un usuario"""
    data = load_data()
    return data.get(str(user_id), {}).get("accounts", [])

def add_user_account(user_id, account_data):
    """Añadir cuenta de usuario"""
    data = load_data()
    user_id_str = str(user_id)
    if user_id_str not in data:
        data[user_id_str] = {
            "telegram_name": account_data.get("telegram_name", ""),
            "accounts": []
        }
    accounts = data[user_id_str].get("accounts", [])
    # Verificar si ya existe
    for i, account in enumerate(accounts):
        if account["username"].lower() == account_data["username"].lower():
            accounts[i] = account_data
            data[user_id_str]["accounts"] = accounts
            save_data(data)
            return "updated"
    # Añadir nueva
    accounts.append(account_data)
    data[user_id_str]["accounts"] = accounts
    save_data(data)
    return "added"

def delete_user_account(user_id, username):
    """Eliminar cuenta de usuario"""
    data = load_data()
    user_id_str = str(user_id)
    if user_id_str in data:
        accounts = data[user_id_str].get("accounts", [])
        new_accounts = [acc for acc in accounts if acc["username"].lower() != username.lower()]
        if len(new_accounts) < len(accounts):
            data[user_id_str]["accounts"] = new_accounts
            save_data(data)
            return True
    return False

# ================= FUNCIONES DE INFORME =================
def generate_public_report():
    """Generar informe público (sin dueños visibles)"""
    data = load_data()
    if not data:
        return "📭 **No hay datos registrados aún.**"
    # Recolectar todas las cuentas
    all_accounts = []
    for user_data in data.values():
        accounts = user_data.get("accounts", [])
        all_accounts.extend([{
            "username": acc["username"],
            "attack": acc["attack"],
            "defense": acc["defense"]
        } for acc in accounts])
    if not all_accounts:
        return "📭 **No hay cuentas registradas en el clan.**"
    # Ordenar por ataque
    all_accounts.sort(key=lambda x: x["attack"], reverse=True)
    # Limitar a 30 cuentas para no saturar
    display_limit = min(30, len(all_accounts))
    accounts_to_show = all_accounts[:display_limit]
    # Calcular totales
    total_attack = sum(acc["attack"] for acc in all_accounts)
    total_defense = sum(acc["defense"] for acc in all_accounts)
    # Generar reporte
    report = "🏰 **INFORME DEL CLAN** 🏰\n\n"
    report += f"📊 **Cuentas registradas:** {len(all_accounts)}\n"
    report += f"⚔️ **Ataque total:** {total_attack:,}\n"
    report += f"🛡️ **Defensa total:** {total_defense:,}\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    # Top cuentas
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, account in enumerate(accounts_to_show[:10], 1):
        medal = medals[i - 1] if i <= 10 else f"{i}."
        report += f"{medal} **{account['username']}**\n"
        report += f"   ⚔️ {account['attack']:,}  🛡️ {account['defense']:,}\n"
        if i < 10 and i < len(accounts_to_show):
            report += "   ─────────────────\n"
    if len(all_accounts) > display_limit:
        report += f"\n📝 ... y {len(all_accounts) - display_limit} cuenta(s) más\n"
    return report

def generate_admin_report():
    """Generar informe para administrador"""
    data = load_data()
    if not data:
        return "📭 **No hay datos registrados aún.**"
    report = "👑 **INFORME ADMINISTRADOR** 👑\n\n"
    total_members = 0
    total_accounts = 0
    total_attack = 0
    total_defense = 0
    for user_id_str, user_data in data.items():
        accounts = user_data.get("accounts", [])
        if accounts:
            total_members += 1
            total_accounts += len(accounts)
            user_attack = sum(acc["attack"] for acc in accounts)
            user_defense = sum(acc["defense"] for acc in accounts)
            total_attack += user_attack
            total_defense += user_defense
            report += f"👤 **{user_data.get('telegram_name', 'Usuario')}**\n"
            report += f"   📊 Cuentas: {len(accounts)}\n"
            report += f"   ⚔️ Ataque: {user_attack:,}\n"
            report += f"   🛡️ Defensa: {user_defense:,}\n"
            for acc in sorted(accounts, key=lambda x: x["attack"], reverse=True):
                report += f"     • {acc['username']}: ⚔️{acc['attack']:,} 🛡️{acc['defense']:,}\n"
            report += "   ─────────────────\n"
    report += f"\n📈 **ESTADÍSTICAS:**\n"
    report += f"👥 Miembros activos: {total_members}\n"
    report += f"📊 Total cuentas: {total_accounts}\n"
    report += f"⚔️ Ataque total: {total_attack:,}\n"
    report += f"🛡️ Defensa total: {total_defense:,}\n"
    return report

# ================= DECORADORES =================
def restricted(func):
    """Decorador para restringir comandos"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_user_authorized(user_id):
            if update.message:
                await update.message.reply_text(
                    "⛔ **Acceso denegado**\n\n"
                    "No estás autorizado para usar este bot.\n"
                    "Contacta al administrador y envía tu ID:\n"
                    "`/getid`",
                    parse_mode="Markdown"
                )
            elif update.callback_query:
                await update.callback_query.answer("⛔ No autorizado", show_alert=True)
            return
        return await func(update, context)
    return wrapper

def restricted_callback(func):
    """Decorador para restringir callbacks"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        if not is_user_authorized(user_id):
            await query.answer("⛔ No estás autorizado para usar este bot", show_alert=True)
            return
        return await func(update, context)
    return wrapper

# ================= COMANDOS PÚBLICOS =================
async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtener ID de usuario"""
    user = update.effective_user
    await update.message.reply_text(
        f"👤 **Tu ID de Telegram:**\n"
        f"`{user.id}`\n\n"
        f"📝 **Nombre:** {user.first_name}\n"
        f"🔗 **Username:** @{user.username if user.username else 'No tiene'}\n\n"
        "📤 **Envía este ID al administrador**\n"
        "para solicitar acceso al bot.",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando de ayuda"""
    help_text = """
🤖 **BOT DEL CLAN - AYUDA** 🤖

**📱 COMANDOS DISPONIBLES:**

**Para todos:**
/start - Iniciar el bot
/getid - Obtener tu ID de Telegram
/help - Mostrar esta ayuda

**Para miembros autorizados:**
/register - Registrar tus cuentas (en privado)
/report - Ver informe del clan

**Para administrador:**
/admin - Vista de administrador
/adduser <id> - Añadir usuario autorizado

**📝 CÓMO REGISTRARSE:**
1. Usa /getid para obtener tu ID
2. Envía tu ID al administrador
3. Cuando te autorice, usa /register
4. Sigue las instrucciones en privado

**🔒 PRIVACIDAD:**
• Solo tú y el admin ven tus datos completos
• El informe público muestra solo ranking anónimo
• Los datos se guardan de forma segura
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ================= MANEJO DE START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando start - diferenciado por tipo de chat"""
    user = update.effective_user
    chat_type = update.effective_chat.type
    if chat_type == "private":
        await handle_private_start(update, context)
    else:
        await handle_group_start(update, context)

async def handle_private_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start en chat privado"""
    user = update.effective_user
    # Verificar autorización
    if not is_user_authorized(user.id):
        keyboard = [[InlineKeyboardButton("📤 Enviar ID al admin", callback_data="send_id_request")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Hola {user.first_name}! 👋\n\n"
            "🔒 **Acceso restringido**\n\n"
            "Para usar este bot necesitas autorización.\n"
            "Usa /getid para obtener tu ID y envíalo al administrador.\n\n"
            "ID del admin: `" + str(ADMIN_USER_ID) + "`",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    # Usuario autorizado
    accounts = get_user_accounts(user.id)
    keyboard = [
        [
            InlineKeyboardButton("➕ Añadir cuenta", callback_data="add_account"),
            InlineKeyboardButton("📋 Mis cuentas", callback_data="my_accounts")
        ],
        [
            InlineKeyboardButton("📊 Informe clan", callback_data="clan_report"),
            InlineKeyboardButton("📈 Mi ranking", callback_data="my_ranking")
        ]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("👑 Vista Admin", callback_data="admin_report")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = f"¡Hola {user.first_name}! 👋\n\n"
    welcome_text += "🏰 **Bot del Clan** 🏰\n\n"
    if accounts:
        total_attack = sum(acc["attack"] for acc in accounts)
        total_defense = sum(acc["defense"] for acc in accounts)
        welcome_text += f"📊 **Tus estadísticas:**\n"
        welcome_text += f"• Cuentas: {len(accounts)}\n"
        welcome_text += f"• Ataque total: {total_attack:,}\n"
        welcome_text += f"• Defensa total: {total_defense:,}\n\n"
    else:
        welcome_text += "📭 Aún no tienes cuentas registradas.\n"
        welcome_text += "¡Añade tu primera cuenta!\n\n"
    welcome_text += "Selecciona una opción:"
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start en grupo"""
    user = update.effective_user
    keyboard = [
        [
            InlineKeyboardButton("🤖 Ir al privado", url=f"https://t.me/{context.bot.username}?start=menu"),
            InlineKeyboardButton("📊 Ver informe", callback_data="group_report")
        ]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("👑 Admin", callback_data="group_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Hola {user.first_name}! 👋\n\n"
        "🏰 **Bot del Clan** 🏰\n\n"
        "**En este grupo puedes:**\n"
        "• 📊 Ver ranking del clan\n"
        "• 🏆 Ver top jugadores\n\n"
        "**En privado puedes:**\n"
        "• ➕ Registrar tus cuentas\n"
        "• 📋 Gestionar tus datos\n"
        "• 📈 Ver estadísticas personales\n\n"
        "Usa '🤖 Ir al privado' para gestionar tus datos.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# ================= REGISTRO DE CUENTAS =================
@restricted
async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /register - inicia registro de cuenta"""
    if update.effective_chat.type != "private":
        keyboard = [[InlineKeyboardButton("🤖 Ir al privado", url=f"https://t.me/{context.bot.username}?start=add")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "📝 **Registro de cuentas**\n\n"
            "Para registrar tus datos debes hacerlo en **chat privado**.\n"
            "Haz clic en el botón para ir al privado.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    await ask_account_username(update, context)

@restricted_callback
async def ask_account_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preguntar nombre de usuario de la cuenta"""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "📝 **REGISTRO DE CUENTA**\n\n"
            "Por favor, envía el **nombre de usuario**\n"
            "de esta cuenta en el juego:\n\n"
            "Ejemplo: `Guerrero123`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "📝 **REGISTRO DE CUENTA**\n\n"
            "Por favor, envía el **nombre de usuario**\n"
            "de esta cuenta en el juego:\n\n"
            "Ejemplo: `Guerrero123`",
            parse_mode="Markdown"
        )
    context.user_data["state"] = "awaiting_username"

@restricted
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar mensajes de texto"""
    user_id = update.effective_user.id
    state = context.user_data.get("state")
    if state == "awaiting_username":
        username = update.message.text.strip()
        if len(username) < 3:
            await update.message.reply_text("❌ El nombre de usuario debe tener al menos 3 caracteres. Intenta de nuevo:")
            return
        context.user_data["username"] = username
        context.user_data["state"] = "awaiting_attack"
        await update.message.reply_text(
            f"👤 **Usuario:** {username}\n\n"
            "Ahora envía el **poder de ataque** de esta cuenta:\n"
            "(Solo números, sin puntos ni comas)\n\n"
            "Ejemplo: `15000`",
            parse_mode="Markdown"
        )
    elif state == "awaiting_attack":
        try:
            attack = int(update.message.text.replace(".", "").replace(",", "").strip())
            if attack <= 0:
                await update.message.reply_text("❌ El ataque debe ser mayor a 0. Intenta de nuevo:")
                return
            context.user_data["attack"] = attack
            context.user_data["state"] = "awaiting_defense"
            await update.message.reply_text(
                f"⚔️ **Ataque:** {attack:,}\n\n"
                "Ahora envía el **poder de defensa** de esta cuenta:\n"
                "(Solo números, sin puntos ni comas)\n\n"
                "Ejemplo: `12000`",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Por favor, envía solo números. Intenta de nuevo:")
    elif state == "awaiting_defense":
        try:
            defense = int(update.message.text.replace(".", "").replace(",", "").strip())
            if defense <= 0:
                await update.message.reply_text("❌ La defensa debe ser mayor a 0. Intenta de nuevo:")
                return
            username = context.user_data["username"]
            attack = context.user_data["attack"]
            # Guardar cuenta
            account_data = {
                "username": username,
                "attack": attack,
                "defense": defense,
                "telegram_name": update.effective_user.first_name,
                "added_date": datetime.now().isoformat()
            }
            result = add_user_account(user_id, account_data)
            # Limpiar estado
            context.user_data.clear()
            # Preparar respuesta
            accounts = get_user_accounts(user_id)
            total_attack = sum(acc["attack"] for acc in accounts)
            total_defense = sum(acc["defense"] for acc in accounts)
            if result == "updated":
                message = "✅ **Cuenta actualizada exitosamente!**\n\n"
            else:
                message = "✅ **Cuenta registrada exitosamente!**\n\n"
            message += f"📝 **Datos registrados:**\n"
            message += f"• 👤 Usuario: {username}\n"
            message += f"• ⚔️ Ataque: {attack:,}\n"
            message += f"• 🛡️ Defensa: {defense:,}\n\n"
            message += f"📊 **Tus estadísticas:**\n"
            message += f"• Cuentas: {len(accounts)}\n"
            message += f"• Ataque total: {total_attack:,}\n"
            message += f"• Defensa total: {total_defense:,}\n\n"
            message += "¿Qué deseas hacer ahora?"
            keyboard = [
                [
                    InlineKeyboardButton("➕ Otra cuenta", callback_data="add_account"),
                    InlineKeyboardButton("📋 Mis cuentas", callback_data="my_accounts")
                ],
                [
                    InlineKeyboardButton("📊 Informe clan", callback_data="clan_report"),
                    InlineKeyboardButton("🏠 Menú", callback_data="back_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("❌ Por favor, envía solo números. Intenta de nuevo:")

# ================= COMANDO REPORT =================
@restricted
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /report - mostrar informe del clan"""
    report = generate_public_report()
    if update.effective_chat.type == "private":
        keyboard = [
            [InlineKeyboardButton("🔄 Actualizar", callback_data="clan_report")],
            [InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")]
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("🤖 Ir al privado", url=f"https://t.me/{context.bot.username}?start=menu"),
                InlineKeyboardButton("🔄 Actualizar", callback_data="group_report")
            ]
        ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(report, reply_markup=reply_markup, parse_mode="Markdown")

# ================= CALLBACK QUERY HANDLER =================
@restricted_callback
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar todas las consultas de callback"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    # Manejo de callbacks simples
    if data == "add_account":
        await ask_account_username(update, context)
    elif data == "my_accounts":
        await show_my_accounts(update, context)
    elif data == "clan_report":
        await show_clan_report(update, context)
    elif data == "my_ranking":
        await show_my_ranking(update, context)
    elif data == "admin_report":
        if is_admin(user_id):
            await show_admin_report(update, context)
        else:
            await query.edit_message_text("⛔ Solo el administrador puede ver esto")
    elif data == "back_menu":
        await handle_private_start(update, context)
    elif data == "group_report":
        await show_group_report(update, context)
    elif data == "group_admin":
        if is_admin(user_id):
            await show_admin_report(update, context)
        else:
            await query.answer("⛔ Solo el administrador puede ver esto", show_alert=True)
    elif data == "send_id_request":
        await send_id_request(update, context)
    elif data == "delete_account_menu":
        await delete_account_menu(update, context)
    elif data and data.startswith("delete:"):
        # formato delete:username
        username = data.split(":", 1)[1]
        await handle_delete_account(update, context, username)

# ================= FUNCIONES AUXILIARES =================
async def send_id_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enviar solicitud de ID al admin"""
    query = update.callback_query
    user = query.from_user
    try:
        # Enviar mensaje al admin
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"🆔 **SOLICITUD DE ACCESO**\n\n"
                 f"👤 Usuario: {user.first_name}\n"
                 f"📛 ID: `{user.id}`\n"
                 f"🔗 Username: @{user.username if user.username else 'No tiene'}\n\n"
                 f"Para autorizar usa: `/adduser {user.id}`",
            parse_mode="Markdown"
        )
        await query.edit_message_text(
            "✅ **Solicitud enviada al administrador**\n\n"
            "Te notificaré cuando hayas sido autorizado.\n"
            "Por favor, espera la confirmación.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error("Error enviando solicitud: %s", e)
        await query.edit_message_text(
            "❌ **Error al enviar solicitud**\n\n"
            f"Contacta manualmente al admin:\nID: `{ADMIN_USER_ID}`",
            parse_mode="Markdown"
        )

async def show_my_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar cuentas del usuario"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        keyboard = [[InlineKeyboardButton("➕ Añadir cuenta", callback_data="add_account")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📭 **No tienes cuentas registradas**\n\n"
            "¡Añade tu primera cuenta!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    total_attack = sum(acc["attack"] for acc in accounts)
    total_defense = sum(acc["defense"] for acc in accounts)
    text = f"📋 **TUS CUENTAS** ({len(accounts)})\n\n"
    for i, account in enumerate(sorted(accounts, key=lambda x: x["attack"], reverse=True), 1):
        text += f"{i}. **{account['username']}**\n"
        text += f"   ⚔️ {account['attack']:,}  🛡️ {account['defense']:,}\n"
        text += "   ─────────────────\n"
    text += f"\n📊 **TOTALES:**\n"
    text += f"• ⚔️ Ataque: {total_attack:,}\n"
    text += f"• 🛡️ Defensa: {total_defense:,}\n"
    keyboard = [
        [
            InlineKeyboardButton("➕ Añadir cuenta", callback_data="add_account"),
            InlineKeyboardButton("🗑️ Eliminar cuenta", callback_data="delete_account_menu")
        ],
        [InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def show_clan_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar informe del clan"""
    query = update.callback_query
    report = generate_public_report()
    keyboard = [[InlineKeyboardButton("🔄 Actualizar", callback_data="clan_report")]]
    if query.message.chat.type == "private":
        keyboard.append([InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(report, reply_markup=reply_markup, parse_mode="Markdown")

async def show_admin_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar informe del administrador"""
    query = update.callback_query
    report = generate_admin_report()
    keyboard = [[InlineKeyboardButton("🔄 Actualizar", callback_data="admin_report")]]
    if query.message.chat.type == "private":
        keyboard.append([InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(report, reply_markup=reply_markup, parse_mode="Markdown")

async def show_my_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar ranking personal"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        keyboard = [[InlineKeyboardButton("➕ Añadir cuenta", callback_data="add_account")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📭 **No tienes cuentas registradas**\n\n"
            "¡Añade tu primera cuenta!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    total_attack = sum(acc["attack"] for acc in accounts)
    total_defense = sum(acc["defense"] for acc in accounts)
    avg_attack = total_attack // len(accounts)
    avg_defense = total_defense // len(accounts)
    best_account = max(accounts, key=lambda x: x["attack"])
    text = f"📈 **TU RANKING PERSONAL**\n\n"
    text += f"📊 **Estadísticas:**\n"
    text += f"• Cuentas: {len(accounts)}\n"
    text += f"• ⚔️ Ataque total: {total_attack:,}\n"
    text += f"• 🛡️ Defensa total: {total_defense:,}\n"
    text += f"• ⚔️ Ataque promedio: {avg_attack:,}\n"
    text += f"• 🛡️ Defensa promedio: {avg_defense:,}\n\n"
    text += f"🏆 **Mejor cuenta:**\n"
    text += f"• {best_account['username']}\n"
    text += f"• ⚔️ {best_account['attack']:,}\n"
    text += f"• 🛡️ {best_account['defense']:,}\n"
    keyboard = [
        [
            InlineKeyboardButton("📋 Mis cuentas", callback_data="my_accounts"),
            InlineKeyboardButton("📊 Informe clan", callback_data="clan_report")
        ],
        [InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def show_group_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar informe en grupo"""
    query = update.callback_query
    report = generate_public_report()
    keyboard = [
        [
            InlineKeyboardButton("🤖 Ir al privado", url=f"https://t.me/{context.bot.username}?start=menu"),
            InlineKeyboardButton("🔄 Actualizar", callback_data="group_report")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(report, reply_markup=reply_markup, parse_mode="Markdown")

async def delete_account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar menú para eliminar cuentas del usuario"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        await query.edit_message_text("📭 No tienes cuentas para eliminar.", parse_mode="Markdown")
        return
    keyboard = []
    for acc in sorted(accounts, key=lambda x: x["username"].lower()):
        keyboard.append([InlineKeyboardButton(f"🗑️ {acc['username']}", callback_data=f"delete:{acc['username']}")])
    keyboard.append([InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Selecciona la cuenta que deseas eliminar:", reply_markup=reply_markup, parse_mode="Markdown")

async def handle_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Eliminar cuenta seleccionada"""
    query = update.callback_query
    user_id = query.from_user.id
    success = delete_user_account(user_id, username)
    if success:
        await query.edit_message_text(f"✅ Cuenta *{username}* eliminada.", parse_mode="Markdown")
    else:
        await query.edit_message_text(f"❌ No se encontró la cuenta *{username}*.", parse_mode="Markdown")

# ================= COMANDOS ADMIN =================
@restricted
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /admin - vista rápida para admin"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Solo el administrador puede usar este comando.")
        return
    report = generate_admin_report()
    keyboard = [
        [InlineKeyboardButton("🔄 Actualizar", callback_data="admin_report")],
        [InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(report, reply_markup=reply_markup, parse_mode="Markdown")

@restricted
async def adduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /adduser <id> - añadir usuario autorizado (solo admin)"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Solo el administrador puede usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /adduser <telegram_id>")
        return
    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID inválido. Debe ser un número.")
        return
    users = load_authorized_users()
    if new_id in users:
        await update.message.reply_text("Ese usuario ya está autorizado.")
        return
    users.append(new_id)
    save_authorized_users(users)
    await update.message.reply_text(f"✅ Usuario {new_id} autorizado correctamente.")
    try:
        await context.bot.send_message(chat_id=new_id, text="✅ Has sido autorizado para usar el Bot del Clan. Usa /start en privado.")
    except Exception:
        pass

# ================= REGISTRO DE HANDLERS Y ARRANQUE (webhook) =================
def build_application():
    app = Application.builder().token(TOKEN).build()
    # Comandos públicos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getid", getid))
    app.add_handler(CommandHandler("help", help_command))
    # Comandos restringidos
    app.add_handler(CommandHandler("register", register_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("adduser", adduser_command))
    # Callbacks y mensajes
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app

def main():
    if not WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL no está definida. En Render configura WEBHOOK_URL a la URL pública de tu servicio (ej: https://mi-app.onrender.com/<token>).")
    app = build_application()
    webhook_path = f"/{TOKEN}"
    listen_addr = "0.0.0.0"
    logger.info("Estableciendo webhook en %s (path %s) en el puerto %s", WEBHOOK_URL, webhook_path, PORT)
    app.run_webhook(
        listen=listen_addr,
        port=PORT,
        webhook_url=WEBHOOK_URL,
        webhook_path=webhook_path,
    )

if __name__ == "__main__":
    main()

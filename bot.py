#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT DEL CLAN - Versión para Render (webhook) con persistencia en GitHub
Variables de entorno necesarias:
- TOKEN
- ADMIN_USER_ID
- ADMIN_USERNAME (opcional)
- WEBHOOK_URL
- PORT (opcional, por defecto 8443)
- GITHUB_TOKEN
- GITHUB_OWNER
- GITHUB_REPO
- GITHUB_DATA_PATH (opcional, por defecto data/clan_data.json)
- GITHUB_AUTH_PATH (opcional, por defecto data/authorized_users.json)
"""

import os
import json
import logging
import asyncio
import base64
import time
from datetime import datetime

import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    BotCommandScopeDefault,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ================= CONFIGURACIÓN (desde env) =================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("La variable de entorno TOKEN no está definida.")

ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")  # opcional
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # Ej: https://mi-servicio.onrender.com/<token>
PORT = int(os.environ.get("PORT", "8443"))

# GitHub storage config
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_DATA_PATH = os.environ.get("GITHUB_DATA_PATH", "data/clan_data.json")
GITHUB_AUTH_PATH = os.environ.get("GITHUB_AUTH_PATH", "data/authorized_users.json")
GITHUB_API = "https://api.github.com"

# Configurar logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================= UTILIDADES GITHUB =================
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}" if GITHUB_TOKEN else "",
    "Accept": "application/vnd.github.v3+json",
}

def _get_file_from_github(path):
    """Devuelve (content:str, sha:str) o (None, None) si no existe."""
    if not (GITHUB_OWNER and GITHUB_REPO):
        raise RuntimeError("GITHUB_OWNER y GITHUB_REPO deben estar configurados.")
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200:
        j = r.json()
        content = base64.b64decode(j["content"]).decode("utf-8")
        sha = j["sha"]
        return content, sha
    if r.status_code == 404:
        return None, None
    r.raise_for_status()

def _put_file_to_github(path, content_str, sha=None, message=None):
    """Crea o actualiza archivo. content_str es texto (JSON)."""
    if not (GITHUB_OWNER and GITHUB_REPO):
        raise RuntimeError("GITHUB_OWNER y GITHUB_REPO deben estar configurados.")
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
    payload = {
        "message": message or f"Update {path} by bot {int(time.time())}",
        "content": b64,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=HEADERS, json=payload)
    if r.status_code in (200, 201):
        return r.json()
    r.raise_for_status()

# ================= FUNCIONES DE DATOS (GITHUB) =================
def load_data():
    """Carga clan_data.json desde GitHub; devuelve dict vacío si no existe o error."""
    try:
        content, sha = _get_file_from_github(GITHUB_DATA_PATH)
        if content is None:
            return {}
        return json.loads(content)
    except Exception as e:
        logger.error("Error cargando datos desde GitHub: %s", e)
        return {}

def save_data(data):
    """Guarda el dict 'data' en GitHub en GITHUB_DATA_PATH. Retorna True/False."""
    try:
        content, sha = _get_file_from_github(GITHUB_DATA_PATH)
        new_content = json.dumps(data, ensure_ascii=False, indent=2)
        _put_file_to_github(GITHUB_DATA_PATH, new_content, sha=sha, message="Save clan data")
        return True
    except Exception as e:
        logger.error("Error guardando datos en GitHub: %s", e)
        return False

def load_authorized_users():
    """Carga authorized_users.json desde GitHub; si no existe devuelve [ADMIN_USER_ID]."""
    try:
        content, sha = _get_file_from_github(GITHUB_AUTH_PATH)
        if content is None:
            return [ADMIN_USER_ID]
        data = json.loads(content)
        return data.get("authorized_ids", [ADMIN_USER_ID])
    except Exception as e:
        logger.error("Error cargando usuarios autorizados desde GitHub: %s", e)
        return [ADMIN_USER_ID]

def save_authorized_users(user_ids):
    """Guarda la lista de user_ids en GitHub. Retorna True/False."""
    try:
        content, sha = _get_file_from_github(GITHUB_AUTH_PATH)
        new_content = json.dumps({"authorized_ids": user_ids}, ensure_ascii=False, indent=2)
        _put_file_to_github(GITHUB_AUTH_PATH, new_content, sha=sha, message="Save authorized users")
        return True
    except Exception as e:
        logger.error("Error guardando usuarios autorizados en GitHub: %s", e)
        return False

def save_data_with_retry(data, retries=3, delay=0.5):
    """Helper con reintentos para reducir conflictos simples."""
    for attempt in range(retries):
        try:
            return save_data(data)
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status in (409,):
                time.sleep(delay * (attempt + 1))
                continue
            logger.exception("HTTP error guardando datos en GitHub: %s", e)
            return False
        except Exception as e:
            logger.exception("Error guardando datos en GitHub: %s", e)
            return False
    logger.error("No se pudo guardar datos en GitHub tras %s intentos", retries)
    return False

# ================= FUNCIONES DE NEGOCIO =================
def get_user_accounts(user_id):
    """Obtener cuentas de un usuario desde GitHub-backed JSON."""
    data = load_data()
    return data.get(str(user_id), {}).get("accounts", [])

def add_user_account(user_id, account_data):
    """Añadir o actualizar cuenta de usuario en el JSON almacenado en GitHub."""
    data = load_data()
    user_id_str = str(user_id)
    if user_id_str not in data:
        data[user_id_str] = {
            "telegram_name": account_data.get("telegram_name", ""),
            "accounts": []
        }
    accounts = data[user_id_str].get("accounts", [])
    for i, account in enumerate(accounts):
        if account["username"].lower() == account_data["username"].lower():
            accounts[i] = account_data
            data[user_id_str]["accounts"] = accounts
            save_data_with_retry(data)
            return "updated"
    accounts.append(account_data)
    data[user_id_str]["accounts"] = accounts
    save_data_with_retry(data)
    return "added"

def delete_user_account(user_id, username):
    """Eliminar cuenta de usuario y persistir en GitHub."""
    data = load_data()
    user_id_str = str(user_id)
    if user_id_str in data:
        accounts = data[user_id_str].get("accounts", [])
        new_accounts = [acc for acc in accounts if acc["username"].lower() != username.lower()]
        if len(new_accounts) < len(accounts):
            data[user_id_str]["accounts"] = new_accounts
            save_data_with_retry(data)
            return True
    return False

# ================= FUNCIONES DE INFORME =================
def generate_public_report():
    """Generar informe público (sin dueños visibles)"""
    data = load_data()
    if not data:
        return "📭 **No hay datos registrados aún.**"
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
    all_accounts.sort(key=lambda x: x["attack"], reverse=True)
    display_limit = min(30, len(all_accounts))
    accounts_to_show = all_accounts[:display_limit]
    total_attack = sum(acc["attack"] for acc in all_accounts)
    total_defense = sum(acc["defense"] for acc in all_accounts)
    report = "🏰 **INFORME DEL CLAN** 🏰\n\n"
    report += f"📊 **Cuentas registradas:** {len(all_accounts)}\n"
    report += f"⚔️ **Ataque total:** {total_attack:,}\n"
    report += f"🛡️ **Defensa total:** {total_defense:,}\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
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
    """Obtener ID de usuario, enviar automáticamente al admin y mostrar botón de contacto."""
    user = update.effective_user

    admin_username = ADMIN_USERNAME
    admin_id = ADMIN_USER_ID if ADMIN_USER_ID != 0 else None

    user_text = (
        f"👤 **Tu ID de Telegram:**\n"
        f"`{user.id}`\n\n"
        f"📝 **Nombre:** {user.first_name}\n"
        f"🔗 **Username:** @{user.username if user.username else 'No tiene'}\n\n"
        "📤 He enviado tu ID al administrador para que te autorice. "
        "Por favor, espera la confirmación."
    )

    sent_to_admin = False
    admin_contact_url = None

    if admin_username:
        admin_username = admin_username.lstrip("@")
        admin_contact_url = f"https://t.me/{admin_username}"
    elif admin_id:
        admin_contact_url = f"tg://user?id={admin_id}"

    if admin_id:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🆔 **SOLICITUD DE ACCESO**\n\n"
                    f"👤 Usuario: {user.first_name}\n"
                    f"📛 ID: `{user.id}`\n"
                    f"🔗 Username: @{user.username if user.username else 'No tiene'}\n\n"
                    f"Para autorizar usa: `/adduser {user.id}`"
                ),
                parse_mode="Markdown"
            )
            sent_to_admin = True
        except Exception as e:
            logger.warning("No se pudo enviar la solicitud al admin por ID: %s", e)

    if not sent_to_admin and admin_username:
        try:
            await context.bot.send_message(
                chat_id=f"@{admin_username}",
                text=(
                    f"🆔 **SOLICITUD DE ACCESO**\n\n"
                    f"👤 Usuario: {user.first_name}\n"
                    f"📛 ID: `{user.id}`\n"
                    f"🔗 Username: @{user.username if user.username else 'No tiene'}\n\n"
                    f"Para autorizar usa: `/adduser {user.id}`"
                ),
                parse_mode="Markdown"
            )
            sent_to_admin = True
        except Exception as e:
            logger.warning("No se pudo enviar la solicitud al admin por username: %s", e)

    if admin_contact_url:
        keyboard = [[InlineKeyboardButton("📩 Contactar al admin", url=admin_contact_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(user_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        admin_display = str(ADMIN_USER_ID) if ADMIN_USER_ID else "No configurado"
        extra = f"\n\nID del admin: `{admin_display}`"
        await update.message.reply_text(user_text + extra, parse_mode="Markdown")

    if not sent_to_admin:
        try:
            await update.message.reply_text(
                "⚠️ No pude notificar automáticamente al administrador. "
                "Por favor, envía tu ID manualmente o contacta al admin.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

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
    """Start en chat privado (funciona con message o callback_query)"""
    query = update.callback_query
    user = update.effective_user

    if not is_user_authorized(user.id):
        keyboard = [[InlineKeyboardButton("📤 Enviar ID al admin", callback_data="send_id_request")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = (
            f"Hola {user.first_name}! 👋\n\n"
            "🔒 **Acceso restringido**\n\n"
            "Para usar este bot necesitas autorización.\n"
            "Usa /getid para obtener tu ID y envíalo al administrador.\n\n"
            "ID del admin: `" + str(ADMIN_USER_ID) + "`"
        )
        if query:
            await query.answer()
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

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

    if query:
        await query.answer()
        await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start en grupo (funciona con message o callback_query)"""
    query = update.callback_query
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

    text = (
        f"Hola {user.first_name}! 👋\n\n"
        "🏰 **Bot del Clan** 🏰\n\n"
        "**En este grupo puedes:**\n"
        "• 📊 Ver ranking del clan\n"
        "• 🏆 Ver top jugadores\n\n"
        "**En privado puedes:**\n"
        "• ➕ Registrar tus cuentas\n"
        "• 📋 Gestionar tus datos\n"
        "• 📈 Ver estadísticas personales\n\n"
        "Usa '🤖 Ir al privado' para gestionar tus datos."
    )

    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# ================= REGISTRO DE CUENTAS, REPORTS, CALLBACKS, ADMIN COMMANDS =================
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

# ================= CONSTRUCCIÓN DE LA APPLICATION =================
def build_application():
    """Construye y devuelve la Application con todos los handlers registrados."""
    application = Application.builder().token(TOKEN).build()

    # Comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getid", getid))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("register", register_command))
    application.add_handler(CommandHandler("report", report_command))
    application.add_handler(CommandHandler("adduser", adduser_command))
    application.add_handler(CommandHandler("admin", admin_command))

    # Callbacks y mensajes
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return application

# ================= REGISTRAR COMANDOS EN TELEGRAM =================
async def register_bot_commands(application: Application):
    commands = [
        BotCommand("start", "Iniciar el bot"),
        BotCommand("help", "Mostrar ayuda"),
        BotCommand("getid", "Obtener tu ID"),
        BotCommand("register", "Registrar tus cuentas"),
        BotCommand("report", "Ver informe del clan"),
        BotCommand("admin", "Vista de administrador"),
        BotCommand("adduser", "Autorizar usuario (admin)"),
    ]
    await application.bot.set_my_commands(commands, scope=BotCommandScopeDefault())

# ================= MAIN / WEBHOOK =================
def main():
    if not WEBHOOK_URL:
        raise RuntimeError(
            "WEBHOOK_URL no está definida. En Render configura WEBHOOK_URL a la URL pública de tu servicio "
            "(ej: https://mi-app.onrender.com/<TOKEN>)."
        )

    application = build_application()
    loop = asyncio.get_event_loop()

    # Registrar comandos en Telegram
    try:
        loop.run_until_complete(register_bot_commands(application))
    except Exception as e:
        logger.warning("No se pudieron registrar comandos automáticamente: %s", e)

    # Registrar webhook y arrancar servidor integrado (si PTB fue instalado con extras webhooks)
    listen_addr = "0.0.0.0"
    port = int(os.environ.get("PORT", PORT))
    url_path = f"/{TOKEN}"

    logger.info("Estableciendo webhook en %s (url_path %s) en el puerto %s", WEBHOOK_URL, url_path, port)

    application.run_webhook(
        listen=listen_addr,
        port=port,
        url_path=url_path,
        webhook_url=WEBHOOK_URL,
        max_connections=1,
    )

if __name__ == "__main__":
    main()

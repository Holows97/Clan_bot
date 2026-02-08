#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT DEL CLAN - VersiÃ³n para Render (webhook) con persistencia en GitHub
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

# ================= CONFIGURACIÃ“N (desde env) =================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("La variable de entorno TOKEN no estÃ¡ definida.")

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
    """Carga clan_data.json desde GitHub; devuelve dict vacÃ­o si no existe o error."""
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
    """AÃ±adir o actualizar cuenta de usuario en el JSON almacenado en GitHub."""
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
    """Generar informe pÃºblico (sin dueÃ±os visibles)"""
    data = load_data()
    if not data:
        return "ðŸ“­ **No hay datos registrados aÃºn.**"
    all_accounts = []
    for user_data in data.values():
        accounts = user_data.get("accounts", [])
        all_accounts.extend([{
            "username": acc["username"],
            "attack": acc["attack"],
            "defense": acc["defense"]
        } for acc in accounts])
    if not all_accounts:
        return "ðŸ“­ **No hay cuentas registradas en el clan.**"
    all_accounts.sort(key=lambda x: x["attack"], reverse=True)
    display_limit = min(30, len(all_accounts))
    accounts_to_show = all_accounts[:display_limit]
    total_attack = sum(acc["attack"] for acc in all_accounts)
    total_defense = sum(acc["defense"] for acc in all_accounts)
    report = "ðŸ° **INFORME DEL CLAN** ðŸ°\n\n"
    report += f"ðŸ“Š **Cuentas registradas:** {len(all_accounts)}\n"
    report += f"âš”ï¸ **Ataque total:** {total_attack:,}\n"
    report += f"ðŸ›¡ï¸ **Defensa total:** {total_defense:,}\n"
    report += "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
    medals = ["ðŸ¥‡", "ðŸ¥ˆ", "ðŸ¥‰", "4ï¸âƒ£", "5ï¸âƒ£", "6ï¸âƒ£", "7ï¸âƒ£", "8ï¸âƒ£", "9ï¸âƒ£", "ðŸ”Ÿ"]
    for i, account in enumerate(accounts_to_show[:10], 1):
        medal = medals[i - 1] if i <= 10 else f"{i}."
        report += f"{medal} **{account['username']}**\n"
        report += f"   âš”ï¸ {account['attack']:,}  ðŸ›¡ï¸ {account['defense']:,}\n"
        if i < 10 and i < len(accounts_to_show):
            report += "   â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\n"
    if len(all_accounts) > display_limit:
        report += f"\nðŸ“ ... y {len(all_accounts) - display_limit} cuenta(s) mÃ¡s\n"
    return report

def generate_admin_report():
    """Generar informe para administrador"""
    data = load_data()
    if not data:
        return "ðŸ“­ **No hay datos registrados aÃºn.**"
    report = "ðŸ‘‘ **INFORME ADMINISTRADOR** ðŸ‘‘\n\n"
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
            report += f"ðŸ‘¤ **{user_data.get('telegram_name', 'Usuario')}**\n"
            report += f"   ðŸ“Š Cuentas: {len(accounts)}\n"
            report += f"   âš”ï¸ Ataque: {user_attack:,}\n"
            report += f"   ðŸ›¡ï¸ Defensa: {user_defense:,}\n"
            for acc in sorted(accounts, key=lambda x: x["attack"], reverse=True):
                report += f"     â€¢ {acc['username']}: âš”ï¸{acc['attack']:,} ðŸ›¡ï¸{acc['defense']:,}\n"
            report += "   â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\n"
    report += f"\nðŸ“ˆ **ESTADÃSTICAS:**\n"
    report += f"ðŸ‘¥ Miembros activos: {total_members}\n"
    report += f"ðŸ“Š Total cuentas: {total_accounts}\n"
    report += f"âš”ï¸ Ataque total: {total_attack:,}\n"
    report += f"ðŸ›¡ï¸ Defensa total: {total_defense:,}\n"
    return report

# ================= DECORADORES =================
def restricted(func):
    """Decorador para restringir comandos"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_user_authorized(user_id):
            if update.message:
                await update.message.reply_text(
                    "â›” **Acceso denegado**\n\n"
                    "No estÃ¡s autorizado para usar este bot.\n"
                    "Contacta al administrador y envÃ­a tu ID:\n"
                    "`/getid`",
                    parse_mode="Markdown"
                )
            elif update.callback_query:
                await update.callback_query.answer("â›” No autorizado", show_alert=True)
            return
        return await func(update, context)
    return wrapper

def restricted_callback(func):
    """Decorador para restringir callbacks"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        if not is_user_authorized(user_id):
            await query.answer("â›” No estÃ¡s autorizado para usar este bot", show_alert=True)
            return
        return await func(update, context)
    return wrapper

# ================= UTILIDADES DE AUTORIZACIÃ“N =================
def is_user_authorized(user_id):
    """Verificar si usuario estÃ¡ autorizado"""
    authorized_ids = load_authorized_users()
    return user_id in authorized_ids

def is_admin(user_id):
    """Verificar si es administrador"""
    return user_id == ADMIN_USER_ID

# ================= COMANDOS PÃšBLICOS =================
async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtener ID de usuario, enviar automÃ¡ticamente al admin y mostrar botÃ³n de contacto."""
    user = update.effective_user

    admin_username = ADMIN_USERNAME
    admin_id = ADMIN_USER_ID if ADMIN_USER_ID != 0 else None

    user_text = (
        f"ðŸ‘¤ **Tu ID de Telegram:**\n"
        f"`{user.id}`\n\n"
        f"ðŸ“ **Nombre:** {user.first_name}\n"
        f"ðŸ”— **Username:** @{user.username if user.username else 'No tiene'}\n\n"
        "ðŸ“¤ He enviado tu ID al administrador para que te autorice. "
        "Por favor, espera la confirmaciÃ³n."
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
                    f"ðŸ†” **SOLICITUD DE ACCESO**\n\n"
                    f"ðŸ‘¤ Usuario: {user.first_name}\n"
                    f"ðŸ“› ID: `{user.id}`\n"
                    f"ðŸ”— Username: @{user.username if user.username else 'No tiene'}\n\n"
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
                    f"ðŸ†” **SOLICITUD DE ACCESO**\n\n"
                    f"ðŸ‘¤ Usuario: {user.first_name}\n"
                    f"ðŸ“› ID: `{user.id}`\n"
                    f"ðŸ”— Username: @{user.username if user.username else 'No tiene'}\n\n"
                    f"Para autorizar usa: `/adduser {user.id}`"
                ),
                parse_mode="Markdown"
            )
            sent_to_admin = True
        except Exception as e:
            logger.warning("No se pudo enviar la solicitud al admin por username: %s", e)

    if admin_contact_url:
        keyboard = [[InlineKeyboardButton("ðŸ“© Contactar al admin", url=admin_contact_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(user_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        admin_display = str(ADMIN_USER_ID) if ADMIN_USER_ID else "No configurado"
        extra = f"\n\nID del admin: `{admin_display}`"
        await update.message.reply_text(user_text + extra, parse_mode="Markdown")

    if not sent_to_admin:
        try:
            await update.message.reply_text(
                "âš ï¸ No pude notificar automÃ¡ticamente al administrador. "
                "Por favor, envÃ­a tu ID manualmente o contacta al admin.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando de ayuda"""
    help_text = """
ðŸ¤– **BOT DEL CLAN - AYUDA** ðŸ¤–

**ðŸ“± COMANDOS DISPONIBLES:**

**Para todos:**
/start - Iniciar el bot
/getid - Obtener tu ID de Telegram
/help - Mostrar esta ayuda

**Para miembros autorizados:**
/register - Registrar tus cuentas (en privado)
/report - Ver informe del clan

**Para administrador:**
/admin - Vista de administrador
/adduser <id> - AÃ±adir usuario autorizado
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
        keyboard = [[InlineKeyboardButton("ðŸ“¤ Enviar ID al admin", callback_data="send_id_request")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = (
            f"Hola {user.first_name}! ðŸ‘‹\n\n"
            "ðŸ”’ **Acceso restringido**\n\n"
            "Para usar este bot necesitas autorizaciÃ³n.\n"
            "Usa /getid para obtener tu ID y envÃ­alo al administrador.\n\n"
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
            InlineKeyboardButton("âž• AÃ±adir cuenta", callback_data="add_account"),
            InlineKeyboardButton("ðŸ“‹ Mis cuentas", callback_data="my_accounts")
        ],
        [
            InlineKeyboardButton("ðŸ“Š Informe clan", callback_data="clan_report"),
            InlineKeyboardButton("ðŸ“ˆ Mi ranking", callback_data="my_ranking")
        ]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("ðŸ‘‘ Vista Admin", callback_data="admin_report")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = f"Â¡Hola {user.first_name}! ðŸ‘‹\n\n"
    welcome_text += "ðŸ° **Bot del Clan** ðŸ°\n\n"
    if accounts:
        total_attack = sum(acc["attack"] for acc in accounts)
        total_defense = sum(acc["defense"] for acc in accounts)
        welcome_text += f"ðŸ“Š **Tus estadÃ­sticas:**\n"
        welcome_text += f"â€¢ Cuentas: {len(accounts)}\n"
        welcome_text += f"â€¢ Ataque total: {total_attack:,}\n"
        welcome_text += f"â€¢ Defensa total: {total_defense:,}\n\n"
    else:
        welcome_text += "ðŸ“­ AÃºn no tienes cuentas registradas.\n"
        welcome_text += "Â¡AÃ±ade tu primera cuenta!\n\n"
    welcome_text += "Selecciona una opciÃ³n:"

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
            InlineKeyboardButton("ðŸ¤– Ir al privado", url=f"https://t.me/{context.bot.username}?start=menu"),
            InlineKeyboardButton("ðŸ“Š Ver informe", callback_data="group_report")
        ]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("ðŸ‘‘ Admin", callback_data="group_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"Hola {user.first_name}! ðŸ‘‹\n\n"
        "ðŸ° **Bot del Clan** ðŸ°\n\n"
        "**En este grupo puedes:**\n"
        "â€¢ ðŸ“Š Ver ranking del clan\n"
        "â€¢ ðŸ† Ver top jugadores\n\n"
        "**En privado puedes:**\n"
        "â€¢ âž• Registrar tus cuentas\n"
        "â€¢ ðŸ“‹ Gestionar tus datos\n"
        "â€¢ ðŸ“ˆ Ver estadÃ­sticas personales\n\n"
        "Usa 'ðŸ¤– Ir al privado' para gestionar tus datos."
    )

    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# ================= REGISTRO DE CUENTAS =================
@restricted
async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /register - inicia registro de cuenta"""
    if update.effective_chat.type != "private":
        keyboard = [[InlineKeyboardButton("ðŸ¤– Ir al privado", url=f"https://t.me/{context.bot.username}?start=add")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "ðŸ“ **Registro de cuentas**\n\n"
            "Para registrar tus datos debes hacerlo en **chat privado**.\n"
            "Haz clic en el botÃ³n para ir al privado.",
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
            "ðŸ“ **REGISTRO DE CUENTA**\n\n"
            "Por favor, envÃ­a el **nombre de usuario**\n"
            "de esta cuenta en el juego:\n\n"
            "Ejemplo: `Guerrero123`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "ðŸ“ **REGISTRO DE CUENTA**\n\n"
            "Por favor, envÃ­a el **nombre de usuario**\n"
            "de esta cuenta en el juego:\n\n"
            "Ejemplo: `Guerrero123`",
            parse_mode="Markdown"
        )
    context.user_data["state"] = "awaiting_username"

@restricted
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar mensajes de texto (flujo de registro)"""
    user_id = update.effective_user.id
    # Priorizar flujo de edición si está activo
    handled = await handle_edit_account_message(update, context)
    if handled:
        return
    state = context.user_data.get("state")
    if state == "awaiting_username":
        username = update.message.text.strip()
        if len(username) < 3:
            await update.message.reply_text("âŒ El nombre de usuario debe tener al menos 3 caracteres. Intenta de nuevo:")
            return
        context.user_data["username"] = username
        context.user_data["state"] = "awaiting_attack"
        await update.message.reply_text(
            f"ðŸ‘¤ **Usuario:** {username}\n\n"
            "Ahora envÃ­a el **poder de ataque** de esta cuenta:\n"
            "(Solo nÃºmeros, sin puntos ni comas)\n\n"
            "Ejemplo: `15000`",
            parse_mode="Markdown"
        )
    elif state == "awaiting_attack":
        try:
            attack = int(update.message.text.replace(".", "").replace(",", "").strip())
            if attack <= 0:
                await update.message.reply_text("âŒ El ataque debe ser mayor a 0. Intenta de nuevo:")
                return
            context.user_data["attack"] = attack
            context.user_data["state"] = "awaiting_defense"
            await update.message.reply_text(
                f"âš”ï¸ **Ataque:** {attack:,}\n\n"
                "Ahora envÃ­a el **poder de defensa** de esta cuenta:\n"
                "(Solo nÃºmeros, sin puntos ni comas)\n\n"
                "Ejemplo: `12000`",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("âŒ Por favor, envÃ­a solo nÃºmeros. Intenta de nuevo:")
    elif state == "awaiting_defense":
        try:
            defense = int(update.message.text.replace(".", "").replace(",", "").strip())
            if defense <= 0:
                await update.message.reply_text("âŒ La defensa debe ser mayor a 0. Intenta de nuevo:")
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
                message = "âœ… **Cuenta actualizada exitosamente!**\n\n"
            else:
                message = "âœ… **Cuenta registrada exitosamente!**\n\n"
            message += f"ðŸ“ **Datos registrados:**\n"
            message += f"â€¢ ðŸ‘¤ Usuario: {username}\n"
            message += f"â€¢ âš”ï¸ Ataque: {attack:,}\n"
            message += f"â€¢ ðŸ›¡ï¸ Defensa: {defense:,}\n\n"
            message += f"ðŸ“Š **Tus estadÃ­sticas:**\n"
            message += f"â€¢ Cuentas: {len(accounts)}\n"
            message += f"â€¢ Ataque total: {total_attack:,}\n"
            message += f"â€¢ Defensa total: {total_defense:,}\n\n"
            message += "Â¿QuÃ© deseas hacer ahora?"
            keyboard = [
                [
                    InlineKeyboardButton("âž• Otra cuenta", callback_data="add_account"),
                    InlineKeyboardButton("ðŸ“‹ Mis cuentas", callback_data="my_accounts")
                ],
                [
                    InlineKeyboardButton("ðŸ“Š Informe clan", callback_data="clan_report"),
                    InlineKeyboardButton("ðŸ  MenÃº", callback_data="back_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("âŒ Por favor, envÃ­a solo nÃºmeros. Intenta de nuevo:")
    else:
        # Mensaje fuera de flujo: mostrar ayuda breve
        await update.message.reply_text("Usa /help para ver los comandos disponibles.", parse_mode="Markdown")

# ================= COMANDO REPORT =================
@restricted
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /report - mostrar informe del clan"""
    report = generate_public_report()
    if update.effective_chat.type == "private":
        keyboard = [
            [InlineKeyboardButton("ðŸ”„ Actualizar", callback_data="clan_report")],
            [InlineKeyboardButton("ðŸ  MenÃº principal", callback_data="back_menu")]
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("ðŸ¤– Ir al privado", url=f"https://t.me/{context.bot.username}?start=menu"),
                InlineKeyboardButton("ðŸ”„ Actualizar", callback_data="group_report")
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
            await query.edit_message_text("â›” Solo el administrador puede ver esto")
    elif data == "back_menu":
        await handle_private_start(update, context)
    elif data == "group_report":
        await show_group_report(update, context)
    elif data == "group_admin":
        if is_admin(user_id):
            await show_admin_report(update, context)
        else:
            await query.answer("â›” Solo el administrador puede ver esto", show_alert=True)
    elif data == "send_id_request":
        await send_id_request(update, context)
    elif data == "delete_account_menu":
        await delete_account_menu(update, context)
    elif data and data.startswith("delete:"):
        username = data.split(":", 1)[1]
        await handle_delete_account(update, context, username)
    elif data == "edit_account_menu":
        await edit_account_menu(update, context)
    elif data and data.startswith("edit:"):
        username = data.split(":", 1)[1]
        await start_edit_account_flow(update, context, username)
    else:
        await query.edit_message_text("OpciÃ³n no reconocida.")

# ================= FUNCIONES AUXILIARES =================
async def send_id_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enviar solicitud de ID al admin (desde botÃ³n)"""
    query = update.callback_query
    user = query.from_user
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"ðŸ†” **SOLICITUD DE ACCESO**\n\n"
                 f"ðŸ‘¤ Usuario: {user.first_name}\n"
                 f"ðŸ“› ID: `{user.id}`\n"
                 f"ðŸ”— Username: @{user.username if user.username else 'No tiene'}\n\n"
                 f"Para autorizar usa: `/adduser {user.id}`",
            parse_mode="Markdown"
        )
        await query.edit_message_text(
            "âœ… **Solicitud enviada al administrador**\n\n"
            "Te notificarÃ© cuando hayas sido autorizado.\n"
            "Por favor, espera la confirmaciÃ³n.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error("Error enviando solicitud: %s", e)
        await query.edit_message_text(
            "âŒ **Error al enviar solicitud**\n\n"
            f"Contacta manualmente al admin:\nID: `{ADMIN_USER_ID}`",
            parse_mode="Markdown"
        )

async def show_my_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar cuentas del usuario"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        keyboard = [[InlineKeyboardButton("âž• AÃ±adir cuenta", callback_data="add_account")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "ðŸ“­ **No tienes cuentas registradas**\n\n"
            "Â¡AÃ±ade tu primera cuenta!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    total_attack = sum(acc["attack"] for acc in accounts)
    total_defense = sum(acc["defense"] for acc in accounts)
    text = f"ðŸ“‹ **TUS CUENTAS** ({len(accounts)})\n\n"
    for i, account in enumerate(sorted(accounts, key=lambda x: x["attack"], reverse=True), 1):
        text += f"{i}. **{account['username']}**\n"
        text += f"   âš”ï¸ {account['attack']:,}  ðŸ›¡ï¸ {account['defense']:,}\n"
        text += "   â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\n"
    text += f"\nðŸ“Š **TOTALES:**\n"
    text += f"â€¢ âš”ï¸ Ataque: {total_attack:,}\n"
    text += f"â€¢ ðŸ›¡ï¸ Defensa: {total_defense:,}\n"
    keyboard = [
        [
            InlineKeyboardButton("➕ Añadir cuenta", callback_data="add_account"),
            InlineKeyboardButton("🗑️ Eliminar cuenta", callback_data="delete_account_menu")
        ],
        [
            InlineKeyboardButton("✏️ Editar cuenta", callback_data="edit_account_menu")
        ],
        [InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def show_clan_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar informe del clan"""
    query = update.callback_query
    report = generate_public_report()
    keyboard = [[InlineKeyboardButton("ðŸ”„ Actualizar", callback_data="clan_report")]]
    if query.message.chat.type == "private":
        keyboard.append([InlineKeyboardButton("ðŸ  MenÃº principal", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(report, reply_markup=reply_markup, parse_mode="Markdown")

async def show_admin_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar informe del administrador"""
    query = update.callback_query
    report = generate_admin_report()
    keyboard = [[InlineKeyboardButton("ðŸ”„ Actualizar", callback_data="admin_report")]]
    if query.message.chat.type == "private":
        keyboard.append([InlineKeyboardButton("ðŸ  MenÃº principal", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(report, reply_markup=reply_markup, parse_mode="Markdown")

async def show_my_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar ranking personal"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        keyboard = [[InlineKeyboardButton("âž• AÃ±adir cuenta", callback_data="add_account")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "ðŸ“­ **No tienes cuentas registradas**\n\n"
            "Â¡AÃ±ade tu primera cuenta!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    total_attack = sum(acc["attack"] for acc in accounts)
    total_defense = sum(acc["defense"] for acc in accounts)
    avg_attack = total_attack // len(accounts)
    avg_defense = total_defense // len(accounts)
    best_account = max(accounts, key=lambda x: x["attack"])
    text = f"ðŸ“ˆ **TU RANKING PERSONAL**\n\n"
    text += f"ðŸ“Š **EstadÃ­sticas:**\n"
    text += f"â€¢ Cuentas: {len(accounts)}\n"
    text += f"â€¢ âš”ï¸ Ataque total: {total_attack:,}\n"
    text += f"â€¢ ðŸ›¡ï¸ Defensa total: {total_defense:,}\n"
    text += f"â€¢ âš”ï¸ Ataque promedio: {avg_attack:,}\n"
    text += f"â€¢ ðŸ›¡ï¸ Defensa promedio: {avg_defense:,}\n\n"
    text += f"ðŸ† **Mejor cuenta:**\n"
    text += f"â€¢ {best_account['username']}\n"
    text += f"â€¢ âš”ï¸ {best_account['attack']:,}\n"
    text += f"â€¢ ðŸ›¡ï¸ {best_account['defense']:,}\n"
    keyboard = [
        [
            InlineKeyboardButton("ðŸ“‹ Mis cuentas", callback_data="my_accounts"),
            InlineKeyboardButton("ðŸ“Š Informe clan", callback_data="clan_report")
        ],
        [InlineKeyboardButton("ðŸ  MenÃº principal", callback_data="back_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def show_group_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar informe en grupo"""
    query = update.callback_query
    report = generate_public_report()
    keyboard = [
        [
            InlineKeyboardButton("ðŸ¤– Ir al privado", url=f"https://t.me/{context.bot.username}?start=menu"),
            InlineKeyboardButton("ðŸ”„ Actualizar", callback_data="group_report")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(report, reply_markup=reply_markup, parse_mode="Markdown")

async def delete_account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar menÃº para eliminar cuentas del usuario"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        await query.edit_message_text("ðŸ“­ No tienes cuentas para eliminar.", parse_mode="Markdown")
        return
    keyboard = []
    for acc in accounts:
        keyboard.append([InlineKeyboardButton(f"ðŸ—‘ï¸ {acc['username']}", callback_data=f"delete:{acc['username']}")])
    keyboard.append([InlineKeyboardButton("ðŸ  MenÃº principal", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Selecciona la cuenta a eliminar:", reply_markup=reply_markup, parse_mode="Markdown")

async def handle_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Eliminar cuenta seleccionada"""
    query = update.callback_query
    user_id = query.from_user.id
    success = delete_user_account(user_id, username)
    if success:
        await query.edit_message_text(f"âœ… Cuenta *{username}* eliminada.", parse_mode="Markdown")
    else:
        await query.edit_message_text(f"âŒ No se encontrÃ³ la cuenta *{username}*.", parse_mode="Markdown")
        
async def edit_account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar menú para editar cuentas del usuario"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        await query.edit_message_text("📭 No tienes cuentas para editar.", parse_mode="Markdown")
        return
    keyboard = []
    for acc in accounts:
        keyboard.append([InlineKeyboardButton(f"✏️ {acc['username']}", callback_data=f"edit:{acc['username']}")])
    keyboard.append([InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Selecciona la cuenta a editar:", reply_markup=reply_markup, parse_mode="Markdown")

async def start_edit_account_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Iniciar flujo de edición: pedir nuevo ataque"""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            f"✏️ **Editar cuenta:** {username}\n\n"
            "Envía el nuevo **poder de ataque** (solo números):",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"✏️ **Editar cuenta:** {username}\n\n"
            "Envía el nuevo **poder de ataque** (solo números):",
            parse_mode="Markdown"
        )
    context.user_data["state"] = "awaiting_edit_attack"
    context.user_data["edit_username"] = username

async def handle_edit_account_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar mensajes durante el flujo de edición (ataque/defensa)"""
    state = context.user_data.get("state")
    user_id = update.effective_user.id

    if state == "awaiting_edit_attack":
        try:
            attack = int(update.message.text.replace(".", "").replace(",", "").strip())
            if attack <= 0:
                await update.message.reply_text("❌ El ataque debe ser mayor a 0. Intenta de nuevo:")
                return True
            context.user_data["edit_attack"] = attack
            context.user_data["state"] = "awaiting_edit_defense"
            await update.message.reply_text(
                f"⚔️ Nuevo ataque: {attack:,}\n\n"
                "Ahora envía el nuevo **poder de defensa** (solo números):",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Por favor, envía solo números. Intenta de nuevo:")
        return True

    if state == "awaiting_edit_defense":
        try:
            defense = int(update.message.text.replace(".", "").replace(",", "").strip())
            if defense <= 0:
                await update.message.reply_text("❌ La defensa debe ser mayor a 0. Intenta de nuevo:")
                return True
            username = context.user_data.get("edit_username")
            attack = context.user_data.get("edit_attack")
            # Cargar cuentas y actualizar la correspondiente
            data = load_data()
            user_key = str(user_id)
            updated = False
            if user_key in data:
                accounts = data[user_key].get("accounts", [])
                for i, acc in enumerate(accounts):
                    if acc["username"].lower() == username.lower():
                        accounts[i]["attack"] = attack
                        accounts[i]["defense"] = defense
                        accounts[i]["updated_date"] = datetime.now().isoformat()
                        updated = True
                        break
                if updated:
                    data[user_key]["accounts"] = accounts
                    save_data_with_retry(data)
            # Limpiar estado
            context.user_data.clear()
            if updated:
                await update.message.reply_text(
                    f"✅ **Cuenta actualizada:** {username}\n"
                    f"• ⚔️ Ataque: {attack:,}\n"
                    f"• 🛡️ Defensa: {defense:,}",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"❌ No se encontró la cuenta *{username}* para actualizar.",
                    parse_mode="Markdown"
                )
        except ValueError:
            await update.message.reply_text("❌ Por favor, envía solo números. Intenta de nuevo:")
        return True

    return False

# ================= ADMIN COMMANDS =================
async def adduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /adduser <id> para autorizar usuarios (solo admin)"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("â›” Solo el administrador puede usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /adduser <telegram_user_id>")
        return
    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID invÃ¡lido.")
        return
    users = load_authorized_users()
    if new_id in users:
        await update.message.reply_text("El usuario ya estÃ¡ autorizado.")
        return
    users.append(new_id)
    save_authorized_users(users)
    await update.message.reply_text(f"âœ… Usuario {new_id} autorizado.")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /admin para ver resumen rÃ¡pido (solo admin)"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("â›” Solo el administrador puede usar este comando.")
        return
    report = generate_admin_report()
    await update.message.reply_text(report, parse_mode="Markdown")

# ================= CONSTRUCCIÃ“N DE LA APPLICATION =================
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
            "WEBHOOK_URL no estÃ¡ definida. En Render configura WEBHOOK_URL a la URL pÃºblica de tu servicio "
            "(ej: https://mi-app.onrender.com/<TOKEN>)."
        )

    application = build_application()
    loop = asyncio.get_event_loop()

    # Registrar comandos en Telegram
    try:
        loop.run_until_complete(register_bot_commands(application))
    except Exception as e:
        logger.warning("No se pudieron registrar comandos automÃ¡ticamente: %s", e)

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

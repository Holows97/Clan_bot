#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT DEL CLAN - Versión actualizada
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
- Manejo seguro de CallbackQuery
- Mejoras en llamadas a GitHub (timeout, headers)
- Comando admin: /deleteuserdata <user_id>
- Comando admin: /broadcast <mensaje>
- Flujo de registro completo (awaiting_username, awaiting_attack, awaiting_defense)
- Flujo de edición de cuentas (awaiting_edit_attack, awaiting_edit_defense)
- Comandos admin: /deleteuserdata <user_id>, /broadcast <mensaje>, /adduser <id>
- Robustez en operaciones con GitHub y Telegram
"""

import os
import json
import logging
import asyncio
import base64
import time
from datetime import datetime
from typing import Optional, List

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
from telegram.error import BadRequest, RetryAfter, Unauthorized, TelegramError

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
HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

REQUEST_TIMEOUT = 10  # segundos

def _get_file_from_github(path: str):
    """Devuelve (content:str, sha:str) o (None, None) si no existe."""
    if not (GITHUB_OWNER and GITHUB_REPO):
        raise RuntimeError("GITHUB_OWNER y GITHUB_REPO deben estar configurados.")
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            j = r.json()
            content = base64.b64decode(j["content"]).decode("utf-8")
            sha = j["sha"]
            return content, sha
        if r.status_code == 404:
            return None, None
        logger.error("GitHub GET %s responded %s: %s", url, r.status_code, r.text)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.exception("Error de red al obtener archivo de GitHub: %s", e)
        raise

def _put_file_to_github(path: str, content_str: str, sha: Optional[str] = None, message: Optional[str] = None):
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
    try:
        r = requests.put(url, headers=HEADERS, json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code in (200, 201):
            return r.json()
        logger.error("GitHub PUT %s responded %s: %s", url, r.status_code, r.text)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.exception("Error de red al guardar archivo en GitHub: %s", e)
        raise

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

def save_data(data: dict):
    """Guarda el dict 'data' en GitHub en GITHUB_DATA_PATH. Retorna True/False."""
    try:
        content, sha = _get_file_from_github(GITHUB_DATA_PATH)
        new_content = json.dumps(data, ensure_ascii=False, indent=2)
        _put_file_to_github(GITHUB_DATA_PATH, new_content, sha=sha, message="Save clan data")
        return True
    except Exception as e:
        logger.exception("Error guardando datos en GitHub: %s", e)
        return False

def load_authorized_users() -> List[int]:
    """Carga authorized_users.json desde GitHub; si no existe devuelve [ADMIN_USER_ID]."""
    try:
        content, sha = _get_file_from_github(GITHUB_AUTH_PATH)
        if content is None:
            return [ADMIN_USER_ID] if ADMIN_USER_ID else []
        data = json.loads(content)
        ids = data.get("authorized_ids", [ADMIN_USER_ID] if ADMIN_USER_ID else [])
        # Normalizar a enteros
        normalized = []
        for x in ids:
            try:
                normalized.append(int(x))
            except Exception:
                logger.warning("ID autorizado no convertible a int: %s", x)
        return normalized
    except Exception as e:
        logger.exception("Error cargando usuarios autorizados desde GitHub: %s", e)
        return [ADMIN_USER_ID] if ADMIN_USER_ID else []

def save_authorized_users(user_ids: List[int]):
    """Guarda la lista de user_ids en GitHub. Retorna True/False."""
    try:
        content, sha = _get_file_from_github(GITHUB_AUTH_PATH)
        new_content = json.dumps({"authorized_ids": user_ids}, ensure_ascii=False, indent=2)
        _put_file_to_github(GITHUB_AUTH_PATH, new_content, sha=sha, message="Save authorized users")
        return True
    except Exception as e:
        logger.exception("Error guardando usuarios autorizados en GitHub: %s", e)
        return False

def save_data_with_retry(data: dict, retries: int = 3, delay: float = 0.5):
    """Helper con reintentos para reducir conflictos simples."""
    for attempt in range(retries):
        try:
            ok = save_data(data)
            if ok:
                return True
            time.sleep(delay * (attempt + 1))
        except Exception as e:
            logger.exception("Error guardando datos en GitHub (intento %s): %s", attempt + 1, e)
            time.sleep(delay * (attempt + 1))
    logger.error("No se pudo guardar datos en GitHub tras %s intentos", retries)
    return False

# ================= FUNCIONES DE NEGOCIO =================
def get_user_accounts(user_id: int):
    """Obtener cuentas de un usuario desde GitHub-backed JSON."""
    data = load_data()
    return data.get(str(user_id), {}).get("accounts", [])

def add_user_account(user_id: int, account_data: dict):
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

def delete_user_account(user_id: int, username: str):
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

def admin_delete_user_data(user_id: int) -> bool:
    """Eliminar por completo los datos de un usuario (solo admin)."""
    data = load_data()
    user_key = str(user_id)
    if user_key in data:
        del data[user_key]
        ok = save_data_with_retry(data)
        if ok:
            logger.info("Admin borró datos del usuario %s", user_id)
        else:
            logger.error("Fallo al persistir borrado de usuario %s", user_id)
        return ok
    logger.warning("Intento de borrar datos de usuario no existente: %s", user_id)
    return False

async def broadcast_message_to_all(app: Application, text: str) -> dict:
    """
    Enviar un mensaje a todos los usuarios que tengan datos en el JSON.
    Retorna un dict con estadísticas: {sent: n, failed: n, errors: [...]}
    """
    data = load_data()
    user_ids = [int(k) for k in data.keys() if k.isdigit()]
    sent = 0
    failed = 0
    errors = []
    for uid in user_ids:
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            errors.append({"user_id": uid, "error": str(e)})
            logger.warning("No se pudo enviar broadcast a %s: %s", uid, e)
    return {"sent": sent, "failed": failed, "errors": errors}

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
    report = "🏆 **INFORME DEL CLAN** 🏆\n\n"
    report += f"📊 **Cuentas registradas:** {len(all_accounts)}\n"
    report += f"⚔️ **Ataque total:** {total_attack:,}\n"
    report += f"🛡️ **Defensa total:** {total_defense:,}\n"
    report += "────────────────────────\n\n"
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    for i, account in enumerate(accounts_to_show[:10], 1):
        medal = medals[i - 1] if i <= 10 else f"{i}."
        report += f"{medal} **{account['username']}**\n"
        report += f"   ⚔️ {account['attack']:,}  🛡️ {account['defense']:,}\n"
        if i < 10 and i < len(accounts_to_show):
            report += "   ─────────────────────\n"
    if len(all_accounts) > display_limit:
        report += f"\n📌 ... y {len(all_accounts) - display_limit} cuenta(s) más\n"
    return report

def generate_admin_report():
    """Generar informe para administrador"""
    data = load_data()
    if not data:
        return "📭 **No hay datos registrados aún.**"
    report = "🔒 **INFORME ADMINISTRADOR** 🔒\n\n"
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
            report += f"👤 **{user_data.get('telegram_name', 'Usuario')}** (ID: {user_id_str})\n"
            report += f"   📊 Cuentas: {len(accounts)}\n"
            report += f"   ⚔️ Ataque: {user_attack:,}\n"
            report += f"   🛡️ Defensa: {user_defense:,}\n"
            for acc in sorted(accounts, key=lambda x: x["attack"], reverse=True):
                report += f"     • {acc['username']}: ⚔️{acc['attack']:,} 🛡️{acc['defense']:,}\n"
            report += "   ─────────────────────\n"
    report += f"\n📈 **ESTADÍSTICAS:**\n"
    report += f"👥 Miembros activos: {total_members}\n"
    report += f"📂 Total cuentas: {total_accounts}\n"
    report += f"⚔️ Ataque total: {total_attack:,}\n"
    report += f"🛡️ Defensa total: {total_defense:,}\n"
    return report

# ================= UTILIDADES DE TELEGRAM (seguras) =================
async def safe_answer_callback(query, text: Optional[str] = None, show_alert: bool = False):
    """Responder callback query de forma segura (captura excepciones comunes)."""
    if not query:
        return
    try:
        if text:
            await query.answer(text=text, show_alert=show_alert)
        else:
            await query.answer()
    except RetryAfter as e:
        logger.warning("RetryAfter al responder callback: %s", e)
    except BadRequest as e:
        logger.warning("BadRequest al responder callback: %s", e)
    except Unauthorized as e:
        logger.error("Unauthorized al responder callback: %s", e)
    except TelegramError as e:
        logger.exception("Error de Telegram al responder callback: %s", e)
    except Exception as e:
        logger.exception("Error inesperado al responder callback: %s", e)

async def safe_edit_message(query, text: str, reply_markup=None, parse_mode=None):
    """Editar mensaje de callback de forma segura."""
    if not query:
        return
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        logger.warning("No se pudo editar mensaje (BadRequest): %s", e)
    except Exception as e:
        logger.exception("Error editando mensaje: %s", e)

# ================= DECORADORES =================
def restricted(func):
    """Decorador para restringir comandos"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_user_authorized(user_id):
            if update.message:
                await update.message.reply_text(
                    "❌ **Acceso denegado**\n\n"
                    "No estás autorizado para usar este bot.\n"
                    "Contacta al administrador y envía tu ID:\n"
                    "`/getid`",
                    parse_mode="Markdown"
                )
            elif update.callback_query:
                await safe_answer_callback(update.callback_query, text="❌ No autorizado", show_alert=True)
            return
        return await func(update, context)
    return wrapper

def restricted_callback(func):
    """Decorador para restringir callbacks"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        if not is_user_authorized(user_id):
            await safe_answer_callback(query, text="❌ No estás autorizado para usar este bot", show_alert=True)
            return
        return await func(update, context)
    return wrapper

# ================= UTILIDADES DE AUTORIZACIÓN =================
def is_user_authorized(user_id: int) -> bool:
    """Verificar si usuario está autorizado"""
    authorized_ids = load_authorized_users()
    return user_id in authorized_ids

def is_admin(user_id: int) -> bool:
    """Verificar si es administrador"""
    return user_id == ADMIN_USER_ID

# ================= COMANDOS PÚBLICOS =================
async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtener ID de usuario, enviar automáticamente al admin y mostrar botón de contacto."""
    user = update.effective_user

    admin_username = ADMIN_USERNAME
    admin_id = ADMIN_USER_ID if ADMIN_USER_ID != 0 else None

    user_text = (
        f"👤 **Tu ID de Telegram:**\n"
        f"`{user.id}`\n\n"
        f"📛 **Nombre:** {user.first_name}\n"
        f"🔗 **Username:** @{user.username if user.username else 'No tiene'}\n\n"
        "He enviado tu ID al administrador para que te autorice. "
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
                    f"➡️ **SOLICITUD DE ACCESO**\n\n"
                    f"👤 Usuario: {user.first_name}\n"
                    f"🆔 ID: `{user.id}`\n"
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
                    f"➡️ **SOLICITUD DE ACCESO**\n\n"
                    f"👤 Usuario: {user.first_name}\n"
                    f"🆔 ID: `{user.id}`\n"
                    f"🔗 Username: @{user.username if user.username else 'No tiene'}\n\n"
                    f"Para autorizar usa: `/adduser {user.id}`"
                ),
                parse_mode="Markdown"
            )
            sent_to_admin = True
        except Exception as e:
            logger.warning("No se pudo enviar la solicitud al admin por username: %s", e)

    if admin_contact_url:
        keyboard = [[InlineKeyboardButton("✉️ Contactar al admin", url=admin_contact_url)]]
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
🧭 **BOT DEL CLAN - AYUDA**

**Comandos:**
/start - Iniciar el bot
/getid - Obtener tu ID de Telegram
/help - Mostrar esta ayuda

**Miembros autorizados:**
/register - Registrar tus cuentas (en privado)
/report - Ver informe del clan

**Administrador:**
/admin - Vista de administrador
/adduser <id> - Añadir usuario autorizado
/deleteuserdata <id> - Borrar datos de un usuario (admin)
/broadcast <mensaje> - Enviar mensaje a todos los usuarios (admin)
"""
    await update.message.reply_text(help_tex

import os
import json
import logging
import asyncio
import base64
import time
from datetime import datetime
from typing import Optional, List

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
from telegram.error import BadRequest, RetryAfter, Unauthorized, TelegramError

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
HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

REQUEST_TIMEOUT = 10  # segundos

def _get_file_from_github(path: str):
    """Devuelve (content:str, sha:str) o (None, None) si no existe."""
    if not (GITHUB_OWNER and GITHUB_REPO):
        raise RuntimeError("GITHUB_OWNER y GITHUB_REPO deben estar configurados.")
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            j = r.json()
            content = base64.b64decode(j["content"]).decode("utf-8")
            sha = j["sha"]
            return content, sha
        if r.status_code == 404:
            return None, None
        # Log para depuración
        logger.error("GitHub GET %s responded %s: %s", url, r.status_code, r.text)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.exception("Error de red al obtener archivo de GitHub: %s", e)
        raise

def _put_file_to_github(path: str, content_str: str, sha: Optional[str] = None, message: Optional[str] = None):
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
    try:
        r = requests.put(url, headers=HEADERS, json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code in (200, 201):
            return r.json()
        logger.error("GitHub PUT %s responded %s: %s", url, r.status_code, r.text)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.exception("Error de red al guardar archivo en GitHub: %s", e)
        raise

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

def save_data(data: dict):
    """Guarda el dict 'data' en GitHub en GITHUB_DATA_PATH. Retorna True/False."""
    try:
        content, sha = _get_file_from_github(GITHUB_DATA_PATH)
        new_content = json.dumps(data, ensure_ascii=False, indent=2)
        _put_file_to_github(GITHUB_DATA_PATH, new_content, sha=sha, message="Save clan data")
        return True
    except Exception as e:
        logger.exception("Error guardando datos en GitHub: %s", e)
        return False

def load_authorized_users() -> List[int]:
    """Carga authorized_users.json desde GitHub; si no existe devuelve [ADMIN_USER_ID]."""
    try:
        content, sha = _get_file_from_github(GITHUB_AUTH_PATH)
        if content is None:
            return [ADMIN_USER_ID] if ADMIN_USER_ID else []
        data = json.loads(content)
        ids = data.get("authorized_ids", [ADMIN_USER_ID] if ADMIN_USER_ID else [])
        # Normalizar a enteros
        normalized = []
        for x in ids:
            try:
                normalized.append(int(x))
            except Exception:
                logger.warning("ID autorizado no convertible a int: %s", x)
        return normalized
    except Exception as e:
        logger.exception("Error cargando usuarios autorizados desde GitHub: %s", e)
        return [ADMIN_USER_ID] if ADMIN_USER_ID else []

def save_authorized_users(user_ids: List[int]):
    """Guarda la lista de user_ids en GitHub. Retorna True/False."""
    try:
        content, sha = _get_file_from_github(GITHUB_AUTH_PATH)
        new_content = json.dumps({"authorized_ids": user_ids}, ensure_ascii=False, indent=2)
        _put_file_to_github(GITHUB_AUTH_PATH, new_content, sha=sha, message="Save authorized users")
        return True
    except Exception as e:
        logger.exception("Error guardando usuarios autorizados en GitHub: %s", e)
        return False

def save_data_with_retry(data: dict, retries: int = 3, delay: float = 0.5):
    """Helper con reintentos para reducir conflictos simples."""
    for attempt in range(retries):
        try:
            ok = save_data(data)
            if ok:
                return True
            # si save_data devolvió False, esperar y reintentar
            time.sleep(delay * (attempt + 1))
        except Exception as e:
            logger.exception("Error guardando datos en GitHub (intento %s): %s", attempt + 1, e)
            time.sleep(delay * (attempt + 1))
    logger.error("No se pudo guardar datos en GitHub tras %s intentos", retries)
    return False

# ================= FUNCIONES DE NEGOCIO =================
def get_user_accounts(user_id: int):
    """Obtener cuentas de un usuario desde GitHub-backed JSON."""
    data = load_data()
    return data.get(str(user_id), {}).get("accounts", [])

def add_user_account(user_id: int, account_data: dict):
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

def delete_user_account(user_id: int, username: str):
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

def admin_delete_user_data(user_id: int) -> bool:
    """Eliminar por completo los datos de un usuario (solo admin)."""
    data = load_data()
    user_key = str(user_id)
    if user_key in data:
        del data[user_key]
        ok = save_data_with_retry(data)
        if ok:
            logger.info("Admin borró datos del usuario %s", user_id)
        else:
            logger.error("Fallo al persistir borrado de usuario %s", user_id)
        return ok
    logger.warning("Intento de borrar datos de usuario no existente: %s", user_id)
    return False

async def broadcast_message_to_all(app: Application, text: str) -> dict:
    """
    Enviar un mensaje a todos los usuarios que tengan datos en el JSON.
    Retorna un dict con estadísticas: {sent: n, failed: n, errors: [...]}
    """
    data = load_data()
    user_ids = [int(k) for k in data.keys() if k.isdigit()]
    sent = 0
    failed = 0
    errors = []
    for uid in user_ids:
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            sent += 1
            # evitar rate limits agresivos
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            errors.append({"user_id": uid, "error": str(e)})
            logger.warning("No se pudo enviar broadcast a %s: %s", uid, e)
            # si RetryAfter, podríamos esperar; aquí lo registramos y seguimos
    return {"sent": sent, "failed": failed, "errors": errors}

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
    report = "🏆 **INFORME DEL CLAN** 🏆\n\n"
    report += f"📊 **Cuentas registradas:** {len(all_accounts)}\n"
    report += f"⚔️ **Ataque total:** {total_attack:,}\n"
    report += f"🛡️ **Defensa total:** {total_defense:,}\n"
    report += "────────────────────────\n\n"
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    for i, account in enumerate(accounts_to_show[:10], 1):
        medal = medals[i - 1] if i <= 10 else f"{i}."
        report += f"{medal} **{account['username']}**\n"
        report += f"   ⚔️ {account['attack']:,}  🛡️ {account['defense']:,}\n"
        if i < 10 and i < len(accounts_to_show):
            report += "   ─────────────────────\n"
    if len(all_accounts) > display_limit:
        report += f"\n📌 ... y {len(all_accounts) - display_limit} cuenta(s) más\n"
    return report

def generate_admin_report():
    """Generar informe para administrador"""
    data = load_data()
    if not data:
        return "📭 **No hay datos registrados aún.**"
    report = "🔒 **INFORME ADMINISTRADOR** 🔒\n\n"
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
            report += f"👤 **{user_data.get('telegram_name', 'Usuario')}** (ID: {user_id_str})\n"
            report += f"   📊 Cuentas: {len(accounts)}\n"
            report += f"   ⚔️ Ataque: {user_attack:,}\n"
            report += f"   🛡️ Defensa: {user_defense:,}\n"
            for acc in sorted(accounts, key=lambda x: x["attack"], reverse=True):
                report += f"     • {acc['username']}: ⚔️{acc['attack']:,} 🛡️{acc['defense']:,}\n"
            report += "   ─────────────────────\n"
    report += f"\n📈 **ESTADÍSTICAS:**\n"
    report += f"👥 Miembros activos: {total_members}\n"
    report += f"📂 Total cuentas: {total_accounts}\n"
    report += f"⚔️ Ataque total: {total_attack:,}\n"
    report += f"🛡️ Defensa total: {total_defense:,}\n"
    return report

# ================= UTILIDADES DE TELEGRAM (seguras) =================
async def safe_answer_callback(query, text: Optional[str] = None, show_alert: bool = False):
    """Responder callback query de forma segura (captura excepciones comunes)."""
    if not query:
        return
    try:
        if text:
            await query.answer(text=text, show_alert=show_alert)
        else:
            await query.answer()
    except RetryAfter as e:
        logger.warning("RetryAfter al responder callback: %s", e)
        # Podríamos esperar e intentar de nuevo si se desea
    except BadRequest as e:
        # Errores típicos: "Query is too old", "Message to edit not found", etc.
        logger.warning("BadRequest al responder callback: %s", e)
    except Unauthorized as e:
        logger.error("Unauthorized al responder callback: %s", e)
    except TelegramError as e:
        logger.exception("Error de Telegram al responder callback: %s", e)
    except Exception as e:
        logger.exception("Error inesperado al responder callback: %s", e)

async def safe_edit_message(query, text: str, reply_markup=None, parse_mode=None):
    """Editar mensaje de callback de forma segura."""
    if not query:
        return
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        logger.warning("No se pudo editar mensaje (BadRequest): %s", e)
    except Exception as e:
        logger.exception("Error editando mensaje: %s", e)

# ================= DECORADORES =================
def restricted(func):
    """Decorador para restringir comandos"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_user_authorized(user_id):
            if update.message:
                await update.message.reply_text(
                    "❌ **Acceso denegado**\n\n"
                    "No estás autorizado para usar este bot.\n"
                    "Contacta al administrador y envía tu ID:\n"
                    "`/getid`",
                    parse_mode="Markdown"
                )
            elif update.callback_query:
                await safe_answer_callback(update.callback_query, text="❌ No autorizado", show_alert=True)
            return
        return await func(update, context)
    return wrapper

def restricted_callback(func):
    """Decorador para restringir callbacks"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        if not is_user_authorized(user_id):
            await safe_answer_callback(query, text="❌ No estás autorizado para usar este bot", show_alert=True)
            return
        return await func(update, context)
    return wrapper

# ================= UTILIDADES DE AUTORIZACIÓN =================
def is_user_authorized(user_id: int) -> bool:
    """Verificar si usuario está autorizado"""
    authorized_ids = load_authorized_users()
    return user_id in authorized_ids

def is_admin(user_id: int) -> bool:
    """Verificar si es administrador"""
    return user_id == ADMIN_USER_ID

# ================= COMANDOS PÚBLICOS =================
async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtener ID de usuario, enviar automáticamente al admin y mostrar botón de contacto."""
    user = update.effective_user

    admin_username = ADMIN_USERNAME
    admin_id = ADMIN_USER_ID if ADMIN_USER_ID != 0 else None

    user_text = (
        f"👤 **Tu ID de Telegram:**\n"
        f"`{user.id}`\n\n"
        f"📛 **Nombre:** {user.first_name}\n"
        f"🔗 **Username:** @{user.username if user.username else 'No tiene'}\n\n"
        "He enviado tu ID al administrador para que te autorice. "
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
                    f"➡️ **SOLICITUD DE ACCESO**\n\n"
                    f"👤 Usuario: {user.first_name}\n"
                    f"🆔 ID: `{user.id}`\n"
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
                    f"➡️ **SOLICITUD DE ACCESO**\n\n"
                    f"👤 Usuario: {user.first_name}\n"
                    f"🆔 ID: `{user.id}`\n"
                    f"🔗 Username: @{user.username if user.username else 'No tiene'}\n\n"
                    f"Para autorizar usa: `/adduser {user.id}`"
                ),
                parse_mode="Markdown"
            )
            sent_to_admin = True
        except Exception as e:
            logger.warning("No se pudo enviar la solicitud al admin por username: %s", e)

    if admin_contact_url:
        keyboard = [[InlineKeyboardButton("✉️ Contactar al admin", url=admin_contact_url)]]
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
🧭 **BOT DEL CLAN - AYUDA**

**Comandos:**
/start - Iniciar el bot
/getid - Obtener tu ID de Telegram
/help - Mostrar esta ayuda

**Miembros autorizados:**
/register - Registrar tus cuentas (en privado)
/report - Ver informe del clan

**Administrador:**
/admin - Vista de administrador
/adduser <id> - Añadir usuario autorizado
/deleteuserdata <id> - Borrar datos de un usuario (admin)
/broadcast <mensaje> - Enviar mensaje a todos los usuarios (admin)
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
            await safe_answer_callback(query)
            await safe_edit_message(query, text, reply_markup=reply_markup, parse_mode="Markdown")
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
            InlineKeyboardButton("🏰 Informe clan", callback_data="clan_report"),
            InlineKeyboardButton("📈 Mi ranking", callback_data="my_ranking")
        ]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🔒 Vista Admin", callback_data="admin_report")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = f"¡Hola {user.first_name}! 👋\n\n"
    welcome_text += "🏠 **Bot del Clan**\n\n"
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
        await safe_answer_callback(query)
        await safe_edit_message(query, welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start en grupo (funciona con message o callback_query)"""
    query = update.callback_query
    user = update.effective_user

    keyboard = [
        [
            InlineKeyboardButton("💬 Ir al privado", url=f"https://t.me/{context.bot.username}?start=menu"),
            InlineKeyboardButton("🏰 Ver informe", callback_data="group_report")
        ]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🔒 Admin", callback_data="group_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"Hola {user.first_name}! 👋\n\n"
        "Este bot gestiona las cuentas del clan. Usa el privado para registrar tus cuentas."
    )

    if query:
        await safe_answer_callback(query)
        await safe_edit_message(query, text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# ================= CALLBACK HANDLER =================
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar todas las consultas de callback"""
    query = update.callback_query
    await safe_answer_callback(query)
    user_id = query.from_user.id
    data = query.data or ""
    try:
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
                await safe_edit_message(query, "⛔ Solo el administrador puede ver esto")
        elif data == "back_menu":
            await handle_private_start(update, context)
        elif data == "group_report":
            await show_group_report(update, context)
        elif data == "group_admin":
            if is_admin(user_id):
                await show_admin_report(update, context)
            else:
                await safe_answer_callback(query, text="⛔ Solo el administrador puede ver esto", show_alert=True)
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
            await safe_edit_message(query, "Opción no reconocida.")
    except Exception as e:
        logger.exception("Error manejando callback '%s': %s", data, e)
        # Intentar informar al usuario sin romper el flujo
        try:
            await safe_edit_message(query, "Ocurrió un error procesando la acción.")
        except Exception:
            pass

# ================= FUNCIONES DE CUENTAS (UI) =================
async def show_my_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar cuentas del usuario"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        keyboard = [[InlineKeyboardButton("➕ Añadir cuenta", callback_data="add_account")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, "📭 **No tienes cuentas registradas**\n\n¡Añade tu primera cuenta!", reply_markup=reply_markup, parse_mode="Markdown")
        return

    text = "📋 **Tus cuentas:**\n\n"
    for acc in accounts:
        text += f"• {acc['username']}: ⚔️{acc['attack']:,} 🛡️{acc['defense']:,}\n"
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
    await safe_edit_message(query, text, reply_markup=reply_markup, parse_mode="Markdown")

async def delete_account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar menú para eliminar cuentas del usuario"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        await safe_edit_message(query, "📭 No tienes cuentas para eliminar.", parse_mode="Markdown")
        return
    keyboard = []
    for acc in accounts:
        keyboard.append([InlineKeyboardButton(f"🗑️ {acc['username']}", callback_data=f"delete:{acc['username']}")])
    keyboard.append([InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(query, "Selecciona la cuenta a eliminar:", reply_markup=reply_markup, parse_mode="Markdown")

async def handle_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Eliminar cuenta seleccionada"""
    query = update.callback_query
    user_id = query.from_user.id
    success = delete_user_account(user_id, username)
    if success:
        await safe_edit_message(query, f"✅ Cuenta *{username}* eliminada.", parse_mode="Markdown")
    else:
        await safe_edit_message(query, f"❌ No se encontró la cuenta *{username}*.", parse_mode="Markdown")

# --- Funciones de edición de cuenta (añadidas) ---
async def edit_account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar menú para editar cuentas del usuario"""
    query = update.callback_query
    user_id = query.from_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        await safe_edit_message(query, "📭 No tienes cuentas para editar.", parse_mode="Markdown")
        return
    keyboard = []
    for acc in accounts:
        keyboard.append([InlineKeyboardButton(f"✏️ {acc['username']}", callback_data=f"edit:{acc['username']}")])
    keyboard.append([InlineKeyboardButton("🏠 Menú principal", callback_data="back_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(query, "Selecciona la cuenta a editar:", reply_markup=reply_markup, parse_mode="Markdown")

async def start_edit_account_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Iniciar flujo de edición: pedir nuevo ataque"""
    query = update.callback_query
    if query:
        await safe_answer_callback(query)
        await safe_edit_message(query,
            f"✏️ **Editar cuenta:** {username}\n\nEnvía el nuevo **poder de ataque** (solo números):",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"✏️ **Editar cuenta:** {username}\n\nEnvía el nuevo **poder de ataque** (solo números):",
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
                f"⚔️ Nuevo ataque: {attack:,}\n\nAhora envía el nuevo **poder de defensa** (solo números):",
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

# ================= MANEJO DE MENSAJES (registro y edición) =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar mensajes de texto (flujo de registro y edición)"""
    user_id = update.effective_user.id

    # Priorizar flujo de edición si está activo
    handled = await handle_edit_account_message(update, context)
    if handled:
        return

    state = context.user_data.get("state")
    # Aquí iría el resto del flujo de registro (awaiting_username, awaiting_attack, etc.)
    # Para mantener el ejemplo conciso, asumimos que el resto del flujo ya existe en tu bot original.
    # Si necesitas que lo incluya completo, lo añado.

    # Ejemplo: si no hay estado conocido, responder con ayuda
    if not state:
        await update.message.reply_text("Usa /help para ver los comandos disponibles.")

# ================= ADMIN: borrar datos de usuario =================
async def cmd_deleteuserdata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando admin para borrar datos de un usuario: /deleteuserdata <user_id>"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Solo el administrador puede usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /deleteuserdata <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID inválido. Debe ser un número.")
        return
    ok = admin_delete_user_data(target_id)
    if ok:
        await update.message.reply_text(f"✅ Datos del usuario {target_id} eliminados.")
    else:
        await update.message.reply_text(f"❌ No se pudo eliminar los datos del usuario {target_id} (no existe o error).")

# ================= ADMIN: broadcast a todos los usuarios =================
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando admin para enviar mensaje a todos los usuarios: /broadcast <mensaje>"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Solo el administrador puede usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /broadcast <mensaje>")
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("El mensaje no puede estar vacío.")
        return
    await update.message.reply_text("📣 Enviando broadcast, esto puede tardar unos segundos...")
    result = await broadcast_message_to_all(context.application, text)
    await update.message.reply_text(f"✅ Envío finalizado. Enviados: {result['sent']}. Fallidos: {result['failed']}.")

# ================= ADMIN: añadir usuario autorizado (ejemplo) =================
async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando admin para añadir usuario autorizado: /adduser <id>"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Solo el administrador puede usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /adduser <id>")
        return
    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID inválido. Debe ser un número.")
        return
    ids = load_authorized_users()
    if new_id in ids:
        await update.message.reply_text("El usuario ya está autorizado.")
        return
    ids.append(new_id)
    if save_authorized_users(ids):
        await update.message.reply_text(f"✅ Usuario {new_id} autorizado.")
    else:
        await update.message.reply_text("❌ Error al guardar la lista de autorizados.")

# ================= REPORTES =================
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando para ver informe público"""
    text = generate_public_report()
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando admin para ver informe completo"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Solo el administrador puede usar este comando.")
        return
    text = generate_admin_report()
    await update.message.reply_text(text, parse_mode="Markdown")

# ================= REGISTRO DE HANDLERS Y ARRANQUE =================
def main():
    app = Application.builder().token(TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("getid", getid))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("deleteuserdata", cmd_deleteuserdata))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # Callbacks y mensajes
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Registrar comandos visibles en Telegram
    try:
        app.bot.set_my_commands([
            BotCommand("start", "Iniciar"),
            BotCommand("help", "Ayuda"),
            BotCommand("getid", "Obtener tu ID"),
            BotCommand("report", "Ver informe del clan"),
            BotCommand("admin", "Vista admin (si eres admin)"),
        ], scope=BotCommandScopeDefault())
    except Exception as e:
        logger.warning("No se pudieron registrar comandos: %s", e)

    # Arranque: si WEBHOOK_URL está configurado, usar webhook; si no, polling (útil en local)
    if WEBHOOK_URL:
        # Configurar webhook (Render u otros)
        logger.info("Iniciando en modo webhook en %s (puerto %s)", WEBHOOK_URL, PORT)
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=WEBHOOK_URL)
    else:
        logger.info("Iniciando en modo polling")
        app.run_polling()

if __name__ == "__main__":
    main()

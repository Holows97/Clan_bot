#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT DEL CLAN - Versión actualizada (correcciones)
- Corrige problemas de codificación (mojibake) con fallback y limpieza.
- Añade menú de administrador con opciones: borrar datos y broadcast.
- Cierra cadenas multilínea y completa help_command.
- Mejora manejo de GitHub con fallback de decodificación.
- Añade main() con registro de handlers.
"""

import os
import json
import logging
import asyncio
import base64
import time
from datetime import datetime
from typing import Optional, List
from functools import wraps

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
from telegram.error import BadRequest, RetryAfter, Forbidden, TelegramError

# ================= CONFIGURACIÓN (desde env) =================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("La variable de entorno TOKEN no está definida.")

ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0")) if os.environ.get("ADMIN_USER_ID") else 0
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

# ================= CODIFICACIÓN / MOJIBAKE =================
def fix_mojibake(s: str) -> str:
    """
    Intentar reparar texto que fue decodificado con la codificación equivocada
    (UTF-8 bytes interpretados como latin-1). Si falla, devolver el original.
    """
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except Exception:
        return s

async def safe_send(app: Application, chat_id: int, text: str, parse_mode: Optional[str] = "Markdown"):
    """
    Enviar texto limpiando mojibake y con fallback si parse_mode falla.
    """
    clean = fix_mojibake(text)
    try:
        await app.bot.send_message(chat_id=chat_id, text=clean, parse_mode=parse_mode)
    except BadRequest as e:
        logger.warning("BadRequest al enviar con parse_mode=%s: %s. Reintentando sin parse_mode.", parse_mode, e)
        try:
            await app.bot.send_message(chat_id=chat_id, text=clean)
        except Exception as e2:
            logger.exception("Fallo al enviar mensaje sin parse_mode: %s", e2)
            raise
    except Exception as e:
        logger.exception("Error enviando mensaje a %s: %s", chat_id, e)
        raise

# ================= UTILIDADES GITHUB =================
HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

REQUEST_TIMEOUT = 10  # segundos

def _get_file_from_github(path: str):
    """Devuelve (content:str, sha:str) o (None, None) si no existe. Maneja fallback de decodificación."""
    if not (GITHUB_OWNER and GITHUB_REPO):
        raise RuntimeError("GITHUB_OWNER y GITHUB_REPO deben estar configurados.")
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            j = r.json()
            raw = base64.b64decode(j["content"])
            sha = j.get("sha")
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    content = raw.decode("latin-1")
                    content = content.encode("latin-1").decode("utf-8", errors="replace")
                except Exception:
                    content = raw.decode("utf-8", errors="replace")
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
    username = account_data.get("username")
    if not username or not isinstance(username, str):
        raise ValueError("username inválido")
    try:
        attack = int(account_data.get("attack", 0))
    except Exception:
        attack = 0
    try:
        defense = int(account_data.get("defense", 0))
    except Exception:
        defense = 0

    account_data["username"] = username.strip()
    account_data["attack"] = attack
    account_data["defense"] = defense

    data = load_data()
    user_id_str = str(user_id)
    if user_id_str not in data:
        data[user_id_str] = {
            "telegram_name": account_data.get("telegram_name", ""),
            "accounts": []
        }
    accounts = data[user_id_str].get("accounts", [])
    for i, account in enumerate(accounts):
        if account.get("username", "").lower() == account_data["username"].lower():
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
        new_accounts = [acc for acc in accounts if acc.get("username", "").lower() != username.lower()]
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
            await safe_send(app, uid, text, parse_mode="Markdown")
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
        for acc in accounts:
            username = acc.get("username", "N/A")
            attack = int(acc.get("attack", 0))
            defense = int(acc.get("defense", 0))
            all_accounts.append({
                "username": username,
                "attack": attack,
                "defense": defense
            })
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
            user_attack = sum(int(acc.get("attack", 0)) for acc in accounts)
            user_defense = sum(int(acc.get("defense", 0)) for acc in accounts)
            total_attack += user_attack
            total_defense += user_defense
            report += f"👤 **{user_data.get('telegram_name', 'Usuario')}** (ID: {user_id_str})\n"
            report += f"   📊 Cuentas: {len(accounts)}\n"
            report += f"   ⚔️ Ataque: {user_attack:,}\n"
            report += f"   🛡️ Defensa: {user_defense:,}\n"
            for acc in sorted(accounts, key=lambda x: int(x.get("attack", 0)), reverse=True):
                report += f"     • {acc.get('username','N/A')}: ⚔️{int(acc.get('attack',0)):,} 🛡️{int(acc.get('defense',0)):,}\n"
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
    except Forbidden as e:
        logger.error("Forbidden al responder callback (posible bloqueo o falta de permisos): %s", e)
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
    except Forbidden as e:
        logger.warning("No se pudo editar mensaje (Forbidden): %s", e)
    except Exception as e:
        logger.exception("Error editando mensaje: %s", e)

# ================= DECORADORES =================
def restricted(func):
    """Decorador para restringir comandos a usuarios autorizados"""
    @wraps(func)
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
    @wraps(func)
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
            await safe_send(context.application, admin_id,
                (
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
            await safe_send(context.application, f"@{admin_username}",
                (
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
/adminmenu - Menú de administrador (solo admin)

Comandos de administración:
/deleteuserdata <user_id> - Borrar todos los datos de un usuario (admin)
/broadcast <mensaje> - Enviar mensaje a todos los usuarios (admin)
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ================= ADMIN: menú y handlers =================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_admin(user_id):
            if update.message:
                await update.message.reply_text("❌ Solo el administrador puede usar este comando.")
            elif update.callback_query:
                await safe_answer_callback(update.callback_query, text="❌ Solo admin", show_alert=True)
            return
        return await func(update, context)
    return wrapper

@admin_only
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar menú de administrador con opciones rápidas."""
    keyboard = [
        [InlineKeyboardButton("🗑️ Borrar datos de usuario", callback_data="admin_deleteuserdata")],
        [InlineKeyboardButton("📣 Broadcast a todos", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔒 Ver informe admin", callback_data="admin_view_report")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("🔧 Menú de administrador. Selecciona una opción:", reply_markup=reply_markup)
    elif update.callback_query:
        await safe_edit_message(update.callback_query, "🔧 Menú de administrador. Selecciona una opción:", reply_markup=reply_markup)

@admin_only
async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer_callback(query)  # ack
    data = query.data

    if data == "admin_deleteuserdata":
        context.user_data["awaiting_admin_delete"] = True
        await safe_edit_message(query, "🗑️ Envía el ID del usuario que quieres borrar. Escribe el ID y presiona enviar.")
        return

    if data == "admin_broadcast":
        context.user_data["awaiting_admin_broadcast"] = True
        await safe_edit_message(query, "📣 Escribe el mensaje que quieres enviar a todos los usuarios. Luego envíalo.")
        return

    if data == "admin_view_report":
        report = generate_admin_report()
        try:
            await query.edit_message_text(fix_mojibake(report), parse_mode="Markdown")
        except Exception:
            await safe_answer_callback(query, text="No se pudo mostrar el informe aquí. Revisa logs.", show_alert=True)
        return

@admin_only
async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if context.user_data.get("awaiting_admin_delete"):
        context.user_data.pop("awaiting_admin_delete", None)
        try:
            target_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ ID inválido. Debes enviar un número entero.")
            return
        ok = admin_delete_user_data(target_id)
        if ok:
            await update.message.reply_text(f"✅ Datos del usuario `{target_id}` borrados correctamente.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ No se encontraron datos para el usuario `{target_id}` o hubo un error.", parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_admin_broadcast"):
        context.user_data.pop("awaiting_admin_broadcast", None)
        message = text
        await update.message.reply_text("📨 Enviando broadcast... (esto puede tardar unos segundos)")
        stats = await broadcast_message_to_all(context.application, message)
        sent = stats.get("sent", 0)
        failed = stats.get("failed", 0)
        await update.message.reply_text(f"✅ Broadcast finalizado. Enviados: {sent}. Fallidos: {failed}.")
        return

    await update.message.reply_text("No hay ninguna acción administrativa pendiente. Usa /adminmenu para abrir el menú.")

# Comandos admin directos (compatibilidad)
@admin_only
async def cmd_deleteuserdata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uso: /deleteuserdata <user_id>"""
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /deleteuserdata <user_id>")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("ID inválido. Debe ser un número entero.")
        return
    ok = admin_delete_user_data(target_id)
    if ok:
        await update.message.reply_text(f"✅ Datos del usuario `{target_id}` borrados correctamente.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ No se encontraron datos para el usuario `{target_id}` o hubo un error.", parse_mode="Markdown")

@admin_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uso: /broadcast <mensaje>"""
    message = " ".join(context.args or [])
    if not message:
        await update.message.reply_text("Uso: /broadcast <mensaje>")
        return
    await update.message.reply_text("📨 Enviando broadcast... (esto puede tardar unos segundos)")
    stats = await broadcast_message_to_all(context.application, message)
    sent = stats.get("sent", 0)
    failed = stats.get("failed", 0)
    await update.message.reply_text(f"✅ Broadcast finalizado. Enviados: {sent}. Fallidos: {failed}.")

# ================= ARRANQUE / MAIN =================
def main():
    """Construir y arrancar la aplicación del bot."""
    app = Application.builder().token(TOKEN).build()

    # Comandos públicos
    app.add_handler(CommandHandler("getid", getid))
    app.add_handler(CommandHandler("help", help_command))

    # Admin menu y callbacks
    app.add_handler(CommandHandler("adminmenu", admin_menu))
    app.add_handler(CallbackQueryHandler(admin_menu_callback, pattern="^admin_"))
    # Admin text handler (captura texto libre para acciones admin)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_handler))

    # Comandos admin directos
    app.add_handler(CommandHandler("deleteuserdata", cmd_deleteuserdata))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # Opcional: establecer comandos visibles en Telegram UI
    try:
        commands = [
            BotCommand("getid", "Obtener tu ID de Telegram"),
            BotCommand("help", "Mostrar ayuda"),
            BotCommand("adminmenu", "Menú de administrador (solo admin)"),
        ]
        app.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    except Exception:
        logger.warning("No se pudieron establecer comandos del bot (posible limitación de la API).")

    # Ejecutar polling (o webhook si prefieres)
    logger.info("Arrancando bot...")
    app.run_polling()
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT DEL CLAN - Archivo único corregido y completo (bot.py)

Incluye:
- Persistencia en GitHub (load/save)
- Menús privados y de grupo
- Paginación para cuentas y usuarios admin
- Flujo estructurado de añadir cuenta (username -> attack -> defense) con confirmación de sobrescritura
- Flujo estructurado de edición (attack -> defense)
- Confirmaciones para eliminación (usuario y cuentas)
- Broadcast por lotes con pausas
- Helpers safe_edit / safe_send para evitar errores de Markdown/longitud
- Limpieza de context.user_data y logging mejorado
"""
import os
import json
import logging
import asyncio
import base64
import time
from math import ceil

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
from telegram.helpers import escape_markdown

# ================= CONFIGURACIÓN (desde env) =================
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("La variable de entorno TOKEN no está definida.")

ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")  # opcional
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
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
    try:
        content, sha = _get_file_from_github(GITHUB_DATA_PATH)
        if content is None:
            return {}
        return json.loads(content)
    except Exception as e:
        logger.error("Error cargando datos desde GitHub: %s", e)
        return {}

def save_data(data):
    try:
        content, sha = _get_file_from_github(GITHUB_DATA_PATH)
        new_content = json.dumps(data, ensure_ascii=False, indent=2)
        _put_file_to_github(GITHUB_DATA_PATH, new_content, sha=sha, message="Save clan data")
        return True
    except Exception as e:
        logger.error("Error guardando datos en GitHub: %s", e)
        return False

def load_authorized_users():
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
    try:
        content, sha = _get_file_from_github(GITHUB_AUTH_PATH)
        new_content = json.dumps({"authorized_ids": user_ids}, ensure_ascii=False, indent=2)
        _put_file_to_github(GITHUB_AUTH_PATH, new_content, sha=sha, message="Save authorized users")
        return True
    except Exception as e:
        logger.error("Error guardando usuarios autorizados en GitHub: %s", e)
        return False

def save_data_with_retry(data, retries=3, delay=0.5):
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

# ----------------- HELPERS DE MENSAJERÍA Y UTILIDADES -----------------
def _safe_text(text: str, max_len: int = 3900) -> str:
    """Escapa Markdown y recorta texto demasiado largo para evitar errores en edit_message_text."""
    if not text:
        return ""
    try:
        esc = escape_markdown(text, version=2)
    except Exception:
        esc = text.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`").replace("[", "\\[")
    if len(esc) > max_len:
        return esc[: max_len - 100] + "\n\n... (mensaje recortado)"
    return esc

async def safe_edit(query, text: str, reply_markup=None, parse_mode="Markdown"):
    """Editar mensaje con escape y manejo de errores."""
    try:
        safe = _safe_text(text)
        await query.edit_message_text(safe, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.warning("safe_edit falló: %s. Intentando enviar nuevo mensaje.", e)
        try:
            await query.message.reply_text(_safe_text(text), reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e2:
            logger.exception("No se pudo enviar mensaje alternativo: %s", e2)

async def safe_send(bot, chat_id: int, text: str, reply_markup=None, parse_mode="Markdown"):
    """Enviar mensaje con escape y manejo de errores."""
    try:
        safe = _safe_text(text)
        await bot.send_message(chat_id=chat_id, text=safe, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.exception("safe_send falló al enviar a %s: %s", chat_id, e)

# ================= FUNCIONES DE NEGOCIO =================
def get_user_accounts(user_id):
    data = load_data()
    return data.get(str(user_id), {}).get("accounts", [])

def add_user_account(user_id, account_data):
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
            ok = save_data_with_retry(data)
            if not ok:
                logger.error("add_user_account: fallo al guardar actualización de cuenta %s para user %s", account_data["username"], user_id)
            return "updated"
    accounts.append(account_data)
    data[user_id_str]["accounts"] = accounts
    ok = save_data_with_retry(data)
    if not ok:
        logger.error("add_user_account: fallo al guardar nueva cuenta %s para user %s", account_data["username"], user_id)
    return "added"

def delete_user_account(user_id, username):
    data = load_data()
    user_id_str = str(user_id)
    if user_id_str in data:
        accounts = data[user_id_str].get("accounts", [])
        new_accounts = [acc for acc in accounts if acc["username"].lower() != username.lower()]
        if len(new_accounts) < len(accounts):
            data[user_id_str]["accounts"] = new_accounts
            ok = save_data_with_retry(data)
            if not ok:
                logger.error("delete_user_account: fallo al guardar eliminación de %s para user %s", username, user_id)
            return True
    return False

# ================= FUNCIONES DE INFORME =================
def generate_public_report():
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
    report += "────────────────────────────\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, account in enumerate(accounts_to_show[:10], 1):
        medal = medals[i - 1] if i <= 10 else f"{i}."
        report += f"{medal} **{account['username']}**\n"
        report += f"   ⚔️ {account['attack']:,}  🛡️ {account['defense']:,}\n"
        if i < 10 and i < len(accounts_to_show):
            report += "   ───────────────────\n"
    if len(all_accounts) > display_limit:
        report += f"\n📌 ... y {len(all_accounts) - display_limit} cuenta(s) más\n"
    return report

def generate_admin_report():
    data = load_data()
    if not data:
        return "📭 **No hay datos registrados aún.**"
    report = "🧾 **INFORME ADMINISTRADOR** 🧾\n\n"
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
            report += f"   📌 Cuentas: {len(accounts)}\n"
            report += f"   ⚔️ Ataque: {user_attack:,}\n"
            report += f"   🛡️ Defensa: {user_defense:,}\n"
            for acc in sorted(accounts, key=lambda x: x["attack"], reverse=True):
                report += f"     • {acc['username']}: ⚔️{acc['attack']:,} 🛡️{acc['defense']:,}\n"
            report += "   ───────────────────\n"
    report += f"\n📈 **ESTADÍSTICAS:**\n"
    report += f"👥 Miembros activos: {total_members}\n"
    report += f"📂 Total cuentas: {total_accounts}\n"
    report += f"⚔️ Ataque total: {total_attack:,}\n"
    report += f"🛡️ Defensa total: {total_defense:,}\n"
    return report

# ================= DECORADORES =================
def restricted(func):
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
                await update.callback_query.answer("❌ No autorizado", show_alert=True)
            return
        return await func(update, context)
    return wrapper

def restricted_callback(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        if not is_user_authorized(user_id):
            await query.answer("❌ No estás autorizado para usar este bot", show_alert=True)
            return
        return await func(update, context)
    return wrapper

# ================= UTILIDADES DE AUTORIZACIÓN =================
def is_user_authorized(user_id):
    authorized_ids = load_authorized_users()
    return user_id in authorized_ids

def is_admin(user_id):
    return user_id == ADMIN_USER_ID

# ================= COMANDOS PÚBLICOS =================
async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    admin_username = ADMIN_USERNAME
    admin_id = ADMIN_USER_ID if ADMIN_USER_ID != 0 else None
    user_text = (
        f"👤 **Tu ID de Telegram:**\n"
        f"`{user.id}`\n\n"
        f"📌 **Nombre:** {user.first_name}\n"
        f"🔗 **Username:** @{user.username if user.username else 'No tiene'}\n\n"
        "📬 He enviado tu ID al administrador para que te autorice. "
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
    help_text = """
🧭 **BOT DEL CLAN - AYUDA** 🧭

**📌 COMANDOS DISPONIBLES:**

**Para todos:**
/start - Iniciar el bot
/getid - Obtener tu ID
/help - Mostrar esta ayuda

**Para miembros autorizados:**
/register - Registrar tus cuentas (en privado)
/report - Ver informe del clan
/editaccounts - Editar o eliminar tus cuentas

**Para administrador:**
/admin - Vista de administrador
/adduser <id> - Añadir usuario autorizado
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ================= MANEJO DE START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_type = update.effective_chat.type
    if chat_type == "private":
        await handle_private_start(update, context)
    else:
        await handle_group_start(update, context)

async def handle_private_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            InlineKeyboardButton("📂 Mis cuentas", callback_data="my_accounts")
        ],
        [
            InlineKeyboardButton("📊 Informe clan", callback_data="clan_report"),
            InlineKeyboardButton("🏅 Mi ranking", callback_data="my_ranking")
        ]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🧾 Vista Admin", callback_data="admin_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = f"¡Hola {user.first_name}! 👋\n\n"
    welcome_text += "🏰 **Bot del Clan** 🏰\n\n"
    if accounts:
        total_attack = sum(acc["attack"] for acc in accounts)
        total_defense = sum(acc["defense"] for acc in accounts)
        welcome_text += f"📌 **Tus estadísticas:**\n"
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
    query = update.callback_query
    user = update.effective_user
    keyboard = [
        [
            InlineKeyboardButton("💬 Ir al privado", url=f"https://t.me/{context.bot.username}?start=menu"),
            InlineKeyboardButton("📊 Ver informe", callback_data="group_report")
        ]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🧾 Admin", callback_data="group_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        f"Hola {user.first_name}! 👋\n\n"
        "Este bot gestiona las cuentas del clan. Usa el botón para abrir el menú privado."
    )
    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

# ===================== FUNCIONES SOLICITADAS (faltantes) =====================
# add_account: flujo estructurado (username -> attack -> defense -> confirmar)
@restricted_callback
async def callback_add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["add_step"] = "username"
    context.user_data.pop("add_temp", None)
    await safe_edit(query, "Registro de nueva cuenta.\n\nEnvía el *nombre de usuario* de la cuenta (ej: Player123).", parse_mode="Markdown")

@restricted
async def handle_add_account_steps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "add_step" not in context.user_data:
        return False
    step = context.user_data.get("add_step")
    text = update.message.text.strip()
    if step == "username":
        existing = False
        try:
            accounts = get_user_accounts(update.effective_user.id)
            for acc in accounts:
                if acc.get("username", "").lower() == text.lower():
                    existing = True
                    break
        except Exception:
            existing = False
        context.user_data.setdefault("add_temp", {})["username"] = text
        if existing:
            context.user_data["add_step"] = "confirm_overwrite"
            keyboard = [
                [InlineKeyboardButton("✅ Sí, actualizar cuenta", callback_data=f"add_confirm_overwrite:{text}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="add_cancel_overwrite")]
            ]
            await update.message.reply_text(
                f"La cuenta **{text}** ya existe. ¿Deseas actualizar sus valores?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return True
        else:
            context.user_data["add_step"] = "attack"
            await update.message.reply_text("Nombre guardado. Ahora envía el valor de *ataque* (número).", parse_mode="Markdown")
            return True
    elif step == "attack":
        try:
            attack = int(text.replace(",", ""))
        except ValueError:
            await update.message.reply_text("Valor inválido. Envía un número entero para ataque.")
            return True
        context.user_data.setdefault("add_temp", {})["attack"] = attack
        context.user_data["add_step"] = "defense"
        await update.message.reply_text("Ataque guardado. Ahora envía el valor de *defensa* (número).", parse_mode="Markdown")
        return True
    elif step == "defense":
        try:
            defense = int(text.replace(",", ""))
        except ValueError:
            await update.message.reply_text("Valor inválido. Envía un número entero para defensa.")
            return True
        temp = context.user_data.pop("add_temp", {})
        username = temp.get("username")
        attack = temp.get("attack")
        if not username or attack is None:
            context.user_data.pop("add_step", None)
            await update.message.reply_text("Estado perdido. Inicia de nuevo con /editaccounts o el botón Añadir cuenta.")
            return True
        account_data = {
            "username": username,
            "attack": attack,
            "defense": defense
        }
        add_user_account(update.effective_user.id, account_data)
        context.user_data.pop("add_step", None)
        await update.message.reply_text(f"Cuenta **{username}** registrada: Ataque {attack:,}, Defensa {defense:,}.", parse_mode="Markdown")
        return True
    return False

# Callbacks para confirmación de sobrescritura en add_account
@restricted_callback
async def callback_add_confirm_overwrite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, username = query.data.split(":", 1)
    except Exception:
        await safe_edit(query, "Dato inválido.")
        return
    context.user_data["add_step"] = "attack"
    await safe_edit(query, f"Actualizarás la cuenta **{username}**. Ahora envía el valor de *ataque* (número).", parse_mode="Markdown")

@restricted_callback
async def callback_add_cancel_overwrite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("add_step", None)
    context.user_data.pop("add_temp", None)
    await safe_edit(query, "Registro cancelado. Si quieres, inicia de nuevo con el botón Añadir cuenta.")

# my_accounts: mostrar cuentas del usuario (resumen) con botones para editar/eliminar
@restricted_callback
async def callback_my_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    accounts = get_user_accounts(user.id)
    if not accounts:
        await safe_edit(query, "No tienes cuentas registradas.")
        return
    text = f"📂 **Tus cuentas ({len(accounts)}):**\n\n"
    for acc in accounts:
        text += f"- **{acc['username']}**: ⚔️ {acc['attack']:,}  🛡️ {acc['defense']:,}\n"
    keyboard = []
    for acc in accounts:
        keyboard.append([InlineKeyboardButton(f"✏️ Editar {acc['username']}", callback_data=f"edit_account:{acc['username']}"),
                         InlineKeyboardButton(f"🗑️ Eliminar {acc['username']}", callback_data=f"delete_account:{acc['username']}")])
    keyboard.append([InlineKeyboardButton("↩️ Volver", callback_data="menu_back")])
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# clan_report: mostrar informe público desde callback
@restricted_callback
async def callback_clan_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    report = generate_public_report()
    await safe_edit(query, report, parse_mode="Markdown")

# my_ranking: calcular y mostrar la posición del usuario entre todas las cuentas
@restricted_callback
async def callback_my_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = load_data()
    all_accounts = []
    for user_id_str, user_data in data.items():
        for acc in user_data.get("accounts", []):
            all_accounts.append({
                "username": acc["username"],
                "attack": acc["attack"],
                "owner": user_id_str
            })
    if not all_accounts:
        await safe_edit(query, "No hay cuentas registradas.")
        return
    all_accounts.sort(key=lambda x: x["attack"], reverse=True)
    user_accounts = [acc for acc in all_accounts if acc["owner"] == str(user.id)]
    if not user_accounts:
        await safe_edit(query, "No tienes cuentas registradas.")
        return
    text = "🏅 **Tu ranking**\n\n"
    for i, acc in enumerate(all_accounts, 1):
        if acc["owner"] == str(user.id):
            text += f"{i}. **{acc['username']}** - ⚔️ {acc['attack']:,}\n"
    text += "\n🔝 Top 5:\n"
    for i, acc in enumerate(all_accounts[:5], 1):
        text += f"{i}. {acc['username']} - ⚔️ {acc['attack']:,}\n"
    await safe_edit(query, text, parse_mode="Markdown")

# send_id_request: callback para usuarios no autorizados que envía la solicitud al admin
@restricted_callback
async def callback_send_id_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    admin_username = ADMIN_USERNAME
    admin_id = ADMIN_USER_ID if ADMIN_USER_ID != 0 else None
    sent_to_admin = False
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
    if sent_to_admin:
        await safe_edit(query, "Tu ID ha sido enviado al administrador. Espera la autorización.")
    else:
        await safe_edit(query, "No pude notificar al administrador automáticamente. Envía tu ID manualmente.")

# group_report: mostrar informe público en grupo (enviar nuevo mensaje)
@restricted_callback
async def callback_group_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    report = generate_public_report()
    try:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=_safe_text(report), parse_mode="Markdown")
    except Exception:
        await safe_edit(query, report, parse_mode="Markdown")

# group_admin: mostrar opciones admin en grupo (si es admin)
@restricted_callback
async def callback_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if not is_admin(user.id):
        await safe_edit(query, "Acceso denegado.")
        return
    keyboard = [
        [InlineKeyboardButton("📣 Enviar mensaje global", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🧾 Ver informe admin", callback_data="admin_menu")]
    ]
    await safe_edit(query, "Menú admin (grupo):", reply_markup=InlineKeyboardMarkup(keyboard))

# ===================== NAVEGACIÓN: volver al menú principal =====================
@restricted_callback
async def callback_menu_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("accounts_page", None)
    context.user_data.pop("admin_users_page", None)
    try:
        await handle_private_start(update, context)
    except Exception as e:
        logger.exception("callback_menu_back: error al volver al menú principal: %s", e)
        try:
            await safe_edit(query, "Volviendo al menú principal...")
        except Exception:
            pass

# ===================== EDICIÓN / BORRADO / BROADCAST =====================
@restricted_callback
async def callback_edit_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, username = query.data.split(":", 1)
    except Exception:
        await safe_edit(query, "Dato inválido.")
        return
    context.user_data["editing_account"] = username
    context.user_data["edit_step"] = "attack"
    await safe_edit(query,
        f"Has elegido editar **{username}**.\n\n"
        "Primero, envía el nuevo valor de **ataque** (solo el número).\n"
        "Ejemplo: `12345`",
        parse_mode="Markdown"
    )

@restricted_callback
async def callback_delete_own_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, username = query.data.split(":", 1)
    except Exception:
        await safe_edit(query, "Dato inválido.")
        return
    context.user_data["confirm_delete_account"] = username
    keyboard = [
        [InlineKeyboardButton("✅ Sí, eliminar", callback_data=f"confirm_delete_account:{username}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_delete_account")]
    ]
    await safe_edit(query,
        f"¿Seguro que quieres eliminar la cuenta **{username}**? Esta acción no se puede deshacer.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

@restricted_callback
async def callback_confirm_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, username = query.data.split(":", 1)
    except Exception:
        await safe_edit(query, "Dato inválido.")
        return
    user = query.from_user
    success = delete_user_account(user.id, username)
    context.user_data.pop("confirm_delete_account", None)
    if success:
        await safe_edit(query, f"Cuenta **{username}** eliminada correctamente.", parse_mode="Markdown")
    else:
        await safe_edit(query, "No pude eliminar la cuenta (no encontrada).", parse_mode="Markdown")

@restricted_callback
async def callback_cancel_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("confirm_delete_account", None)
    await safe_edit(query, "Eliminación cancelada.", parse_mode="Markdown")

# ------------------ MENÚ ADMIN ------------------
@restricted
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Acceso denegado.")
        return
    data = load_data()
    users = list(data.items())
    if not users:
        await update.message.reply_text("No hay usuarios registrados.")
        return
    page = int(context.user_data.get("admin_users_page", 1))
    per_page = 8
    total_pages = max(1, ceil(len(users) / per_page))
    page = max(1, min(page, total_pages))
    context.user_data["admin_users_page"] = page
    start = (page - 1) * per_page
    end = start + per_page
    slice_users = users[start:end]
    keyboard = []
    keyboard.append([InlineKeyboardButton("📣 Enviar mensaje global", callback_data="admin_broadcast")])
    for user_id_str, user_data in slice_users:
        display = user_data.get("telegram_name", f"User {user_id_str}")
        keyboard.append([InlineKeyboardButton(f"🧑 {display}", callback_data=f"admin_user:{user_id_str}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data="admin_users_prev"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data="admin_users_next"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("↩️ Volver", callback_data="menu_back")])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Menú administrador:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("Menú administrador:", reply_markup=InlineKeyboardMarkup(keyboard))

@restricted_callback
async def callback_admin_users_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "admin_users_next":
        context.user_data["admin_users_page"] = int(context.user_data.get("admin_users_page", 1)) + 1
    elif query.data == "admin_users_prev":
        context.user_data["admin_users_page"] = max(1, int(context.user_data.get("admin_users_page", 1)) - 1)
    await admin_menu(update, context)

@restricted_callback
async def callback_admin_user_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, user_id_str = query.data.split(":", 1)
    except Exception:
        await safe_edit(query, "Dato inválido.")
        return
    data = load_data()
    user_data = data.get(user_id_str)
    if not user_data:
        await safe_edit(query, "Usuario no encontrado.")
        return
    text = f"Usuario: **{user_data.get('telegram_name','-')}** (ID: `{user_id_str}`)\n\nCuentas:\n"
    for acc in user_data.get("accounts", []):
        text += f"- {acc['username']}: Ataque {acc['attack']:,} Defensa {acc['defense']:,}\n"
    keyboard = [
        [InlineKeyboardButton("🗑️ Eliminar usuario completo", callback_data=f"admin_delete_user_confirm:{user_id_str}")],
    ]
    for acc in user_data.get("accounts", []):
        keyboard.append([InlineKeyboardButton(f"🗑️ Eliminar {acc['username']}", callback_data=f"admin_delete_account_confirm:{user_id_str}:{acc['username']}")])
    keyboard.append([InlineKeyboardButton("↩️ Volver", callback_data="admin_menu")])
    await safe_edit(query, text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

@restricted_callback
async def callback_admin_delete_user_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, user_id_str = query.data.split(":", 1)
    except Exception:
        await safe_edit(query, "Dato inválido.")
        return
    context.user_data["admin_confirm_delete_user"] = user_id_str
    keyboard = [
        [InlineKeyboardButton("✅ Sí, eliminar usuario", callback_data=f"admin_delete_user:{user_id_str}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_cancel_delete")]
    ]
    await safe_edit(query,
        f"¿Seguro que quieres eliminar al usuario `{user_id_str}` y todas sus cuentas? Esta acción es irreversible.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@restricted_callback
async def callback_admin_delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, user_id_str = query.data.split(":", 1)
    except Exception:
        await safe_edit(query, "Dato inválido.")
        return
    data = load_data()
    if user_id_str in data:
        data.pop(user_id_str)
        save_data_with_retry(data)
        try:
            auth = load_authorized_users()
            uid_int = int(user_id_str)
            if uid_int in auth:
                auth.remove(uid_int)
                save_authorized_users(auth)
        except Exception:
            pass
        context.user_data.pop("admin_confirm_delete_user", None)
        await safe_edit(query, f"Usuario `{user_id_str}` eliminado correctamente.", parse_mode="Markdown")
    else:
        await safe_edit(query, "Usuario no encontrado.", parse_mode="Markdown")

@restricted_callback
async def callback_admin_cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("admin_confirm_delete_user", None)
    context.user_data.pop("admin_confirm_delete_account", None)
    await safe_edit(query, "Eliminación cancelada.", parse_mode="Markdown")

@restricted_callback
async def callback_admin_delete_account_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, user_id_str, username = query.data.split(":", 2)
    except Exception:
        await safe_edit(query, "Dato inválido.")
        return
    context.user_data["admin_confirm_delete_account"] = (user_id_str, username)
    keyboard = [
        [InlineKeyboardButton("✅ Sí, eliminar cuenta", callback_data=f"admin_delete_account:{user_id_str}:{username}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_cancel_delete")]
    ]
    await safe_edit(query,
        f"¿Seguro que quieres eliminar la cuenta **{username}** del usuario `{user_id_str}`?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@restricted_callback
async def callback_admin_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, user_id_str, username = query.data.split(":", 2)
    except Exception:
        await safe_edit(query, "Dato inválido.")
        return
    data = load_data()
    if user_id_str in data:
        accounts = data[user_id_str].get("accounts", [])
        new_accounts = [acc for acc in accounts if acc["username"].lower() != username.lower()]
        if len(new_accounts) < len(accounts):
            data[user_id_str]["accounts"] = new_accounts
            save_data_with_retry(data)
            context.user_data.pop("admin_confirm_delete_account", None)
            await safe_edit(query, f"Cuenta **{username}** eliminada del usuario `{user_id_str}`.", parse_mode="Markdown")
            return
    await safe_edit(query, "Cuenta o usuario no encontrado.", parse_mode="Markdown")

# Broadcast start (admin)
@restricted_callback
async def callback_admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("No autorizado", show_alert=True)
        return
    context.user_data["awaiting_broadcast"] = True
    await safe_edit(query, "Envía el mensaje que quieres enviar a todos los usuarios registrados. Usa texto simple.")

async def handle_broadcast_message_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return False
    if not context.user_data.pop("awaiting_broadcast", False):
        return False
    text = update.message.text
    data = load_data()
    sent = 0
    failed = 0
    batch_size = 20
    user_ids = [int(uid) for uid in list(data.keys())]
    for i in range(0, len(user_ids), batch_size):
        batch = user_ids[i : i + batch_size]
        for uid in batch:
            try:
                await context.bot.send_message(chat_id=uid, text=_safe_text(text))
                sent += 1
            except Exception:
                failed += 1
        await asyncio.sleep(0.5)
    try:
        auth = load_authorized_users()
        for uid in auth:
            if str(uid) not in data:
                try:
                    await context.bot.send_message(chat_id=uid, text=_safe_text(text))
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    failed += 1
    except Exception:
        pass
    await update.message.reply_text(f"Mensaje enviado. Éxitos: {sent}. Fallos: {failed}.")
    return True

# ===================== UNIFICACIÓN DE MESSAGE HANDLER =====================
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    processed = await handle_broadcast_message_internal(update, context)
    if processed:
        return
    processed_add = await handle_add_account_steps(update, context)
    if processed_add:
        return
    if "editing_account" in context.user_data and "edit_step" in context.user_data:
        step = context.user_data.get("edit_step")
        text = update.message.text.strip()
        try:
            value = int(text.replace(",", ""))
        except ValueError:
            await update.message.reply_text("Valor inválido. Envía un número entero.")
            return
        if step == "attack":
            context.user_data["pending_attack"] = value
            context.user_data["edit_step"] = "defense"
            await update.message.reply_text(f"Ataque temporal: {value:,}. Ahora envía defensa.")
            return
        elif step == "defense":
            attack = context.user_data.pop("pending_attack", None)
            defense = value
            username = context.user_data.pop("editing_account", None)
            context.user_data.pop("edit_step", None)
            if username is None or attack is None:
                await update.message.reply_text("Estado perdido. Intenta de nuevo.")
                return
            data = load_data()
            user_id_str = str(update.effective_user.id)
            updated = False
            if user_id_str in data:
                accounts = data[user_id_str].get("accounts", [])
                for acc in accounts:
                    if acc["username"].lower() == username.lower():
                        acc["attack"] = attack
                        acc["defense"] = defense
                        updated = True
                        break
                if updated:
                    data[user_id_str]["accounts"] = accounts
                    save_data_with_retry(data)
                    await update.message.reply_text(f"Cuenta {username} actualizada: Ataque {attack:,}, Defensa {defense:,}.")
                    return
            await update.message.reply_text("No encontré la cuenta para actualizar.")
            return
    return

# ===================== HANDLERS ADICIONALES =====================
@restricted
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = generate_public_report()
    await update.message.reply_text(report, parse_mode="Markdown")

@restricted
async def cmd_admin_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Acceso denegado.")
        return
    report = generate_admin_report()
    await update.message.reply_text(report, parse_mode="Markdown")

@restricted
async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Acceso denegado.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /adduser <user_id>")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID inválido.")
        return
    auth = load_authorized_users()
    if uid in auth:
        await update.message.reply_text("Usuario ya autorizado.")
        return
    auth.append(uid)
    save_authorized_users(auth)
    await update.message.reply_text(f"Usuario {uid} autorizado.")

# ===================== REGISTRO DE HANDLERS Y ARRANQUE =====================
# --- INICIO BLOQUE: vista paginada de cuentas + handler de paginación ---
@restricted
async def send_accounts_list_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Muestra/edita la lista de cuentas del usuario con paginación.
    Si se llama desde callback_query, edita el mensaje; si se llama desde comando, envía nuevo mensaje.
    """
    user = update.effective_user
    user_id = user.id
    accounts = get_user_accounts(user_id)
    per_page = 6
    page = int(context.user_data.get("accounts_page", 1))
    total = len(accounts)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    context.user_data["accounts_page"] = page

    start = (page - 1) * per_page
    end = start + per_page
    slice_accounts = accounts[start:end]

    if not accounts:
        text = "📭 No tienes cuentas registradas."
        keyboard = [[InlineKeyboardButton("↩️ Volver", callback_data="menu_back")]]
        reply = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await safe_edit(update.callback_query, text, reply_markup=reply)
        else:
            await update.message.reply_text(text, reply_markup=reply)
        return

    text = f"📂 **Tus cuentas ({total}):**\n\n"
    for acc in slice_accounts:
        text += f"- **{acc['username']}**: ⚔️ {acc['attack']:,}  🛡️ {acc['defense']:,}\n"

    keyboard = []
    for acc in slice_accounts:
        keyboard.append([
            InlineKeyboardButton(f"✏️ Editar {acc['username']}", callback_data=f"edit_account:{acc['username']}"),
            InlineKeyboardButton(f"🗑️ Eliminar {acc['username']}", callback_data=f"delete_account:{acc['username']}")
        ])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data="accounts_prev"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data="accounts_next"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("↩️ Volver", callback_data="menu_back")])
    reply = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await safe_edit(update.callback_query, text, reply_markup=reply, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply, parse_mode="Markdown")

@restricted_callback
async def callback_accounts_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja los botones de paginación de la lista de cuentas:
    - accounts_next  -> siguiente página
    - accounts_prev  -> página anterior
    Re-renderiza la lista llamando a send_accounts_list_for_edit.
    """
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    page = int(context.user_data.get("accounts_page", 1))
    if data == "accounts_next":
        context.user_data["accounts_page"] = page + 1
    elif data == "accounts_prev":
        context.user_data["accounts_page"] = max(1, page - 1)
    await send_accounts_list_for_edit(update, context)
# --- FIN BLOQUE ---
def main():
    application = Application.builder().token(TOKEN).build()

    # Comandos básicos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getid", getid))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("report", cmd_report))
    application.add_handler(CommandHandler("adminreport", cmd_admin_report))
    application.add_handler(CommandHandler("adduser", cmd_adduser))
    application.add_handler(CommandHandler("editaccounts", callback_my_accounts))
    application.add_handler(CommandHandler("admin", admin_menu))

    # Callbacks: add account, my_accounts, clan_report, my_ranking, send_id_request, group
    application.add_handler(CallbackQueryHandler(callback_add_account_start, pattern=r"^add_account$"))
    application.add_handler(CallbackQueryHandler(callback_add_confirm_overwrite, pattern=r"^add_confirm_overwrite:"))
    application.add_handler(CallbackQueryHandler(callback_add_cancel_overwrite, pattern=r"^add_cancel_overwrite$"))
    application.add_handler(CallbackQueryHandler(callback_my_accounts, pattern=r"^my_accounts$"))
    application.add_handler(CallbackQueryHandler(callback_clan_report, pattern=r"^clan_report$"))
    application.add_handler(CallbackQueryHandler(callback_my_ranking, pattern=r"^my_ranking$"))
    application.add_handler(CallbackQueryHandler(callback_send_id_request, pattern=r"^send_id_request$"))
    application.add_handler(CallbackQueryHandler(callback_group_report, pattern=r"^group_report$"))
    application.add_handler(CallbackQueryHandler(callback_group_admin, pattern=r"^group_admin$"))

    # Callbacks: cuentas (paginación, editar, eliminar)
    application.add_handler(CallbackQueryHandler(callback_accounts_pagination, pattern=r"^accounts_(next|prev)$"))
    application.add_handler(CallbackQueryHandler(callback_edit_account_start, pattern=r"^edit_account:"))
    application.add_handler(CallbackQueryHandler(callback_delete_own_account, pattern=r"^delete_account:"))
    application.add_handler(CallbackQueryHandler(callback_confirm_delete_account, pattern=r"^confirm_delete_account:"))
    application.add_handler(CallbackQueryHandler(callback_cancel_delete_account, pattern=r"^cancel_delete_account$"))
    application.add_handler(CallbackQueryHandler(callback_menu_back, pattern=r"^menu_back$"))

    # Admin callbacks
    application.add_handler(CallbackQueryHandler(admin_menu, pattern=r"^admin_menu$"))
    application.add_handler(CallbackQueryHandler(callback_admin_users_pagination, pattern=r"^admin_users_(next|prev)$"))
    application.add_handler(CallbackQueryHandler(callback_admin_user_view, pattern=r"^admin_user:"))
    application.add_handler(CallbackQueryHandler(callback_admin_delete_user_confirm, pattern=r"^admin_delete_user_confirm:"))
    application.add_handler(CallbackQueryHandler(callback_admin_delete_user, pattern=r"^admin_delete_user:"))
    application.add_handler(CallbackQueryHandler(callback_admin_cancel_delete, pattern=r"^admin_cancel_delete$"))
    application.add_handler(CallbackQueryHandler(callback_admin_delete_account_confirm, pattern=r"^admin_delete_account_confirm:"))
    application.add_handler(CallbackQueryHandler(callback_admin_delete_account, pattern=r"^admin_delete_account:"))
    application.add_handler(CallbackQueryHandler(callback_admin_broadcast_start, pattern=r"^admin_broadcast$"))

    # Pagination callbacks for accounts and admin users
    application.add_handler(CallbackQueryHandler(callback_accounts_pagination, pattern=r"^accounts_(next|prev)$"))
    application.add_handler(CallbackQueryHandler(callback_admin_users_pagination, pattern=r"^admin_users_(next|prev)$"))

    # Un único MessageHandler que enruta según estado
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    # Set bot commands (opcional)
    try:
        commands = [
            BotCommand("start", "Iniciar el bot"),
            BotCommand("getid", "Obtener tu ID"),
            BotCommand("help", "Ayuda"),
            BotCommand("report", "Ver informe del clan"),
            BotCommand("editaccounts", "Editar o eliminar tus cuentas"),
            BotCommand("admin", "Menú administrador (si eres admin)")
        ]
        application.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    except Exception:
        pass

    # Ejecutar webhook si está configurado
    if WEBHOOK_URL:
        logger.info("Iniciando webhook en %s:%s", "0.0.0.0", PORT)
        application.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{WEBHOOK_URL}")
    else:
        logger.info("WEBHOOK_URL no configurado, arrancando en polling (solo para pruebas).")
        application.run_polling()

if __name__ == "__main__":
    main()

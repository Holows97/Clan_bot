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
    """Generar informe para administrador"""
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
                await update.callback_query.answer("❌ No autorizado", show_alert=True)
            return
        return await func(update, context)
    return wrapper

def restricted_callback(func):
    """Decorador para restringir callbacks"""
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
    """Verificar si usuario está autorizado"""
    authorized_ids = load_authorized_users()
    return user_id in authorized_ids

def is_admin(user_id):
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
    """Comando de ayuda"""
    help_text = """
🧭 **BOT DEL CLAN - AYUDA** 🧭

**📌 COMANDOS DISPONIBLES:**

**Para todos:**
/start - Iniciar el bot
/getid - Obtener tu ID de Telegram
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
    """Start en grupo (funciona con message o callback_query)"""
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

# ===================== NUEVAS FUNCIONES SOLICITADAS =====================
# Flujo de edición más estructurado: pedir ataque y luego defensa por separado.
# Estados en context.user_data:
# - editing_account: username en edición
# - edit_step: "attack" o "defense"
# - pending_attack: valor temporal

# Mostrar lista de cuentas del usuario con botones para editar/eliminar (paginada si muchas)
@restricted
async def send_accounts_list_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    accounts = get_user_accounts(user.id)
    if not accounts:
        await update.message.reply_text("No tienes cuentas registradas.")
        return

    # Paginación simple: 6 cuentas por página
    page = int(context.user_data.get("accounts_page", 1))
    per_page = 6
    total_pages = max(1, ceil(len(accounts) / per_page))
    page = max(1, min(page, total_pages))
    context.user_data["accounts_page"] = page

    start = (page - 1) * per_page
    end = start + per_page
    slice_accounts = accounts[start:end]

    keyboard = []
    for acc in slice_accounts:
        username = acc["username"]
        keyboard.append([
            InlineKeyboardButton(f"✏️ Editar {username}", callback_data=f"edit_account:{username}"),
            InlineKeyboardButton(f"🗑️ Eliminar {username}", callback_data=f"delete_account:{username}")
        ])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data="accounts_prev"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data="accounts_next"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("↩️ Volver", callback_data="menu_back")])

    await update.message.reply_text(
        f"Selecciona la cuenta que quieres editar o eliminar (Página {page}/{total_pages}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@restricted_callback
async def callback_accounts_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    page = int(context.user_data.get("accounts_page", 1))
    if data == "accounts_next":
        context.user_data["accounts_page"] = page + 1
    elif data == "accounts_prev":
        context.user_data["accounts_page"] = max(1, page - 1)
    # Reusar la función para enviar la lista (simulamos llamada)
    await query.edit_message_text("Actualizando lista...")
    # Llamamos a la función que envía la lista como si fuera un mensaje nuevo
    # No podemos llamar send_accounts_list_for_edit directamente con update.message, así que respondemos con nuevo mensaje
    await send_accounts_list_for_edit(update, context)

# Iniciar edición: guardar estado y pedir ataque
@restricted_callback
async def callback_edit_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, username = query.data.split(":", 1)
    except Exception:
        await query.edit_message_text("Dato inválido.")
        return
    context.user_data["editing_account"] = username
    context.user_data["edit_step"] = "attack"
    await query.edit_message_text(
        f"Has elegido editar **{username}**.\n\n"
        "Primero, envía el nuevo valor de **ataque** (solo el número).\n"
        "Ejemplo: `12345`",
        parse_mode="Markdown"
    )

# Recibir valores paso a paso (ataque luego defensa)
@restricted
async def handle_structured_edit_values(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if "editing_account" not in context.user_data or "edit_step" not in context.user_data:
        return  # no estamos en modo edición estructurada
    step = context.user_data.get("edit_step")
    text = update.message.text.strip()
    # Validar número
    try:
        value = int(text.replace(",", ""))
    except ValueError:
        await update.message.reply_text("Valor inválido. Envía un número entero.")
        return

    if step == "attack":
        context.user_data["pending_attack"] = value
        context.user_data["edit_step"] = "defense"
        await update.message.reply_text(
            f"Ataque registrado temporalmente: {value:,}\n\nAhora envía el nuevo valor de **defensa** (solo el número).",
            parse_mode="Markdown"
        )
        return
    elif step == "defense":
        attack = context.user_data.pop("pending_attack", None)
        defense = value
        username = context.user_data.pop("editing_account", None)
        context.user_data.pop("edit_step", None)
        if username is None or attack is None:
            await update.message.reply_text("Estado de edición perdido. Intenta de nuevo.")
            return
        # Actualizar en GitHub
        data = load_data()
        user_id_str = str(user.id)
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
                await update.message.reply_text(
                    f"Cuenta **{username}** actualizada: Ataque {attack:,}, Defensa {defense:,}.",
                    parse_mode="Markdown"
                )
                return
        await update.message.reply_text("No encontré la cuenta para actualizar. Asegúrate de que existe.")

# Eliminar cuenta propia con confirmación
@restricted_callback
async def callback_delete_own_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, username = query.data.split(":", 1)
    except Exception:
        await query.edit_message_text("Dato inválido.")
        return
    # Pedir confirmación
    context.user_data["confirm_delete_account"] = username
    keyboard = [
        [InlineKeyboardButton("✅ Sí, eliminar", callback_data=f"confirm_delete_account:{username}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_delete_account")]
    ]
    await query.edit_message_text(
        f"¿Seguro que quieres eliminar la cuenta **{username}**? Esta acción no se puede deshacer.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@restricted_callback
async def callback_confirm_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, username = query.data.split(":", 1)
    except Exception:
        await query.edit_message_text("Dato inválido.")
        return
    user = query.from_user
    success = delete_user_account(user.id, username)
    context.user_data.pop("confirm_delete_account", None)
    if success:
        await query.edit_message_text(f"Cuenta **{username}** eliminada correctamente.", parse_mode="Markdown")
    else:
        await query.edit_message_text("No pude eliminar la cuenta (no encontrada).", parse_mode="Markdown")

@restricted_callback
async def callback_cancel_delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("confirm_delete_account", None)
    await query.edit_message_text("Eliminación cancelada.", parse_mode="Markdown")

# ------------------ MENÚ ADMIN: ver usuarios, eliminar y broadcast ------------------

@restricted
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Puede ser llamado por comando o callback
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Acceso denegado.")
        return
    data = load_data()
    users = list(data.items())
    if not users:
        await update.message.reply_text("No hay usuarios registrados.")
        return

    # Paginación de usuarios: 8 por página
    page = int(context.user_data.get("admin_users_page", 1))
    per_page = 8
    total_pages = max(1, ceil(len(users) / per_page))
    page = max(1, min(page, total_pages))
    context.user_data["admin_users_page"] = page

    start = (page - 1) * per_page
    end = start + per_page
    slice_users = users[start:end]

    keyboard = []
    # Botón para mensaje global
    keyboard.append([InlineKeyboardButton("📣 Enviar mensaje global", callback_data="admin_broadcast")])
    # Listar usuarios (mostrar nombre o ID)
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
    # Si llamado por comando, enviar nuevo mensaje; si por callback, editar
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Menú administrador:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("Menú administrador:", reply_markup=InlineKeyboardMarkup(keyboard))

@restricted_callback
async def callback_admin_users_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    page = int(context.user_data.get("admin_users_page", 1))
    if data == "admin_users_next":
        context.user_data["admin_users_page"] = page + 1
    elif data == "admin_users_prev":
        context.user_data["admin_users_page"] = max(1, page - 1)
    await admin_menu(update, context)

@restricted_callback
async def callback_admin_user_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, user_id_str = query.data.split(":", 1)
    except Exception:
        await query.edit_message_text("Dato inválido.")
        return
    data = load_data()
    user_data = data.get(user_id_str)
    if not user_data:
        await query.edit_message_text("Usuario no encontrado.")
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
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# Confirmaciones admin: eliminar usuario completo
@restricted_callback
async def callback_admin_delete_user_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, user_id_str = query.data.split(":", 1)
    except Exception:
        await query.edit_message_text("Dato inválido.")
        return
    context.user_data["admin_confirm_delete_user"] = user_id_str
    keyboard = [
        [InlineKeyboardButton("✅ Sí, eliminar usuario", callback_data=f"admin_delete_user:{user_id_str}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_cancel_delete")]
    ]
    await query.edit_message_text(
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
        await query.edit_message_text("Dato inválido.")
        return
    data = load_data()
    if user_id_str in data:
        data.pop(user_id_str)
        save_data_with_retry(data)
        # también quitar de authorized users si existe
        try:
            auth = load_authorized_users()
            uid_int = int(user_id_str)
            if uid_int in auth:
                auth.remove(uid_int)
                save_authorized_users(auth)
        except Exception:
            pass
        context.user_data.pop("admin_confirm_delete_user", None)
        await query.edit_message_text(f"Usuario `{user_id_str}` eliminado correctamente.", parse_mode="Markdown")
    else:
        await query.edit_message_text("Usuario no encontrado.", parse_mode="Markdown")

@restricted_callback
async def callback_admin_cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("admin_confirm_delete_user", None)
    await query.edit_message_text("Eliminación cancelada.", parse_mode="Markdown")

# Confirmaciones admin: eliminar cuenta específica
@restricted_callback
async def callback_admin_delete_account_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, user_id_str, username = query.data.split(":", 2)
    except Exception:
        await query.edit_message_text("Dato inválido.")
        return
    context.user_data["admin_confirm_delete_account"] = (user_id_str, username)
    keyboard = [
        [InlineKeyboardButton("✅ Sí, eliminar cuenta", callback_data=f"admin_delete_account:{user_id_str}:{username}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_cancel_delete")]
    ]
    await query.edit_message_text(
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
        await query.edit_message_text("Dato inválido.")
        return
    data = load_data()
    if user_id_str in data:
        accounts = data[user_id_str].get("accounts", [])
        new_accounts = [acc for acc in accounts if acc["username"].lower() != username.lower()]
        if len(new_accounts) < len(accounts):
            data[user_id_str]["accounts"] = new_accounts
            save_data_with_retry(data)
            context.user_data.pop("admin_confirm_delete_account", None)
            await query.edit_message_text(f"Cuenta **{username}** eliminada del usuario `{user_id_str}`.", parse_mode="Markdown")
            return
    await query.edit_message_text("Cuenta o usuario no encontrado.", parse_mode="Markdown")

# ------------------ BROADCAST (MENSAJE GLOBAL) ------------------

@restricted_callback
async def callback_admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("No autorizado", show_alert=True)
        return
    context.user_data["awaiting_broadcast"] = True
    await query.edit_message_text("Envía el mensaje que quieres enviar a todos los usuarios registrados. Usa texto simple.")

@restricted
async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    if not context.user_data.pop("awaiting_broadcast", False):
        return
    text = update.message.text
    data = load_data()
    sent = 0
    failed = 0
    # Enviar a todos los usuarios que aparecen en data (keys)
    for user_id_str in list(data.keys()):
        try:
            await context.bot.send_message(chat_id=int(user_id_str), text=text)
            sent += 1
            # pequeña pausa para evitar límites
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
            continue
    # También enviar a usuarios autorizados que no estén en data
    try:
        auth = load_authorized_users()
        for uid in auth:
            if str(uid) not in data:
                try:
                    await context.bot.send_message(chat_id=uid, text=text)
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    failed += 1
    except Exception:
        pass
    await update.message.reply_text(f"Mensaje enviado. Éxitos: {sent}. Fallos: {failed}.")

# ===================== HANDLERS ADICIONALES =====================
# Handler para mostrar informe público
@restricted
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = generate_public_report()
    await update.message.reply_text(report, parse_mode="Markdown")

# Handler admin quick command to show admin report
@restricted
async def cmd_admin_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Acceso denegado.")
        return
    report = generate_admin_report()
    await update.message.reply_text(report, parse_mode="Markdown")

# Comando para añadir usuario autorizado (solo admin)
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
def main():
    application = Application.builder().token(TOKEN).build()

    # Comandos básicos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getid", getid))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("report", cmd_report))
    application.add_handler(CommandHandler("adminreport", cmd_admin_report))
    application.add_handler(CommandHandler("adduser", cmd_adduser))
    application.add_handler(CommandHandler("editaccounts", send_accounts_list_for_edit))
    application.add_handler(CommandHandler("admin", admin_menu))

    # Callbacks para navegación y acciones
    application.add_handler(CallbackQueryHandler(callback_accounts_pagination, pattern=r"^accounts_(next|prev)$"))
    application.add_handler(CallbackQueryHandler(callback_edit_account_start, pattern=r"^edit_account:"))
    application.add_handler(CallbackQueryHandler(callback_delete_own_account, pattern=r"^delete_account:"))
    application.add_handler(CallbackQueryHandler(callback_confirm_delete_account, pattern=r"^confirm_delete_account:"))
    application.add_handler(CallbackQueryHandler(callback_cancel_delete_account, pattern=r"^cancel_delete_account$"))

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

    # Callbacks for pagination and menu back
    application.add_handler(CallbackQueryHandler(admin_menu, pattern=r"^admin_menu$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: c.user_data.pop("accounts_page", None) or u.callback_query.edit_message_text("Volviendo..."), pattern=r"^menu_back$"))

    # Handlers para edición estructurada y broadcast (mensajes de texto)
    # IMPORTANTE: estos MessageHandlers deben ir después de handlers más específicos
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_structured_edit_values))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_message))

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
        # run_webhook requiere host y port; Render suele usar 0.0.0.0 y el puerto de env
        logger.info("Iniciando webhook en %s:%s", "0.0.0.0", PORT)
        application.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{WEBHOOK_URL}")
    else:
        # Fallback a polling (útil para pruebas locales)
        logger.info("WEBHOOK_URL no configurado, arrancando en polling (solo para pruebas).")
        application.run_polling()

if __name__ == "__main__":
    main()

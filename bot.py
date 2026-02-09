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

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"


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


# ================= FUNCIONES DE DATOS (GITHUB) =================
def load_user_data():
    """Carga toda la información de usuarios y administradores"""
    try:
        content, sha = _get_file_from_github(GITHUB_AUTH_PATH)
        if content is None:
            # Crear estructura inicial
            initial_data = {
                "authorized_ids": [ADMIN_USER_ID],
                "admin_ids": [ADMIN_USER_ID],
                "user_info": {
                    str(ADMIN_USER_ID): {
                        "username": ADMIN_USERNAME if ADMIN_USERNAME else None,
                        "first_name": "Administrador Principal",
                        "last_interaction": int(time.time())
                    }
                }
            }
            _put_file_to_github(GITHUB_AUTH_PATH, 
                              json.dumps(initial_data, indent=2), 
                              sha=None, 
                              message="Initial authorized users")
            return initial_data
        
        data = json.loads(content)
        
        # Migrar de estructura antigua a nueva si es necesario
        if "user_info" not in data:
            data["user_info"] = {}
            
        # Asegurar que ADMIN_USER_ID siempre esté en ambas listas
        if ADMIN_USER_ID not in data.get("authorized_ids", []):
            data.setdefault("authorized_ids", []).append(ADMIN_USER_ID)
        if ADMIN_USER_ID not in data.get("admin_ids", []):
            data.setdefault("admin_ids", []).append(ADMIN_USER_ID)
            
        return data
    except Exception as e:
        logger.error("Error cargando usuarios autorizados desde GitHub: %s", e)
        return {
            "authorized_ids": [ADMIN_USER_ID],
            "admin_ids": [ADMIN_USER_ID],
            "user_info": {}
        }

def load_authorized_users():
    """Compatibilidad: carga usuarios autorizados del nuevo sistema"""
    data = load_user_data()
    return data.get("authorized_ids", []), data.get("admin_ids", [])

def save_authorized_users(authorized_ids, admin_ids=None):
    """Compatibilidad: guarda usuarios en el nuevo sistema"""
    data = load_user_data()
    data["authorized_ids"] = list(set(authorized_ids))
    if admin_ids is not None:
        data["admin_ids"] = list(set(admin_ids))
    return save_user_data(data)

def save_user_data(data):
    """Guarda toda la información de usuarios"""
    try:
        _, sha = _get_file_from_github(GITHUB_AUTH_PATH)
        new_content = json.dumps(data, ensure_ascii=False, indent=2)
        _put_file_to_github(GITHUB_AUTH_PATH, new_content, sha=sha, message="Save user data")
        return True
    except Exception as e:
        logger.error("Error guardando usuarios autorizados en GitHub: %s", e)
        return False

def update_user_info(user_id: int, username: str = None, first_name: str = None):
    """Actualiza la información del usuario"""
    try:
        data = load_user_data()
        user_id_str = str(user_id)
        
        if user_id_str not in data.setdefault("user_info", {}):
            data["user_info"][user_id_str] = {}
        
        if username is not None:
            data["user_info"][user_id_str]["username"] = username
        if first_name is not None:
            data["user_info"][user_id_str]["first_name"] = first_name
        
        data["user_info"][user_id_str]["last_interaction"] = int(time.time())
        
        return save_user_data(data)
    except Exception as e:
        logger.error("Error actualizando información de usuario: %s", e)
        return False

def get_user_info(user_id: int):
    """Obtiene información del usuario"""
    data = load_user_data()
    return data.get("user_info", {}).get(str(user_id), {})

def is_user_authorized(user_id):
    data = load_user_data()
    return user_id in data.get("authorized_ids", [])

def is_admin(user_id):
    data = load_user_data()
    return user_id in data.get("admin_ids", [])

def load_all_users():
    """Carga ambos: usuarios autorizados y administradores"""
    return load_authorized_users()


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

#===añade a la bd
def add_authorized_user(user_id: int, make_admin: bool = False, username: str = None, first_name: str = None) -> bool:
    """
    Añade user_id a la lista de autorizados y opcionalmente lo hace admin.
    Devuelve True si se añadió, False si ya existía o hubo error.
    """
    try:
        data = load_user_data()
        uid = int(user_id)
        
        # Añadir a usuarios autorizados si no existe
        if uid not in data.setdefault("authorized_ids", []):
            data["authorized_ids"].append(uid)
        
        # Añadir a administradores si se solicita
        if make_admin and uid not in data.setdefault("admin_ids", []):
            data["admin_ids"].append(uid)
        
        # Actualizar información del usuario
        update_user_info(uid, username, first_name)
        
        # Actualizar datos en el archivo principal
        ok = save_user_data(data)
        if not ok:
            logger.error("add_authorized_user: fallo al guardar usuarios en GitHub")
            return False
        
        logger.info("Usuario %s añadido%s", uid, " como ADMIN" if make_admin else "")
        return True
        
    except Exception as e:
        logger.exception("Error guardando usuario autorizado: %s", e)
        return False
        
        
def update_user_telegram_name(user_id: int, name: str) -> bool:
    """
    Actualiza el nombre de Telegram del usuario en los datos.
    """
    try:
        user_id_str = str(user_id)
        data = load_data()
        
        if user_id_str not in data:
            data[user_id_str] = {
                "telegram_name": name,
                "accounts": []
            }
        else:
            data[user_id_str]["telegram_name"] = name
        
        ok = save_data_with_retry(data)
        if not ok:
            logger.warning("No se pudo actualizar nombre de Telegram para user %s", user_id)
        
        return ok
    except Exception as e:
        logger.exception("Error actualizando nombre de Telegram: %s", e)
        return False


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
        return "📭 *No hay datos registrados aún.*"
    
    all_accounts = []
    for user_data in data.values():
        accounts = user_data.get("accounts", [])
        all_accounts.extend([{
            "username": acc["username"],
            "attack": acc["attack"],
            "defense": acc["defense"]
        } for acc in accounts])
    
    if not all_accounts:
        return "📭 *No hay cuentas registradas en el clan.*"
    
    # Ordenar por ataque descendente
    all_accounts.sort(key=lambda x: x["attack"], reverse=True)
    display_limit = min(30, len(all_accounts))
    accounts_to_show = all_accounts[:display_limit]
    
    # Cálculos de estadísticas
    total_attack = sum(acc["attack"] for acc in all_accounts)
    total_defense = sum(acc["defense"] for acc in all_accounts)
    avg_attack = total_attack // len(all_accounts) if all_accounts else 0
    avg_defense = total_defense // len(all_accounts) if all_accounts else 0
    
    # Construir el informe
    report = "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
    report += "┃      🏰 *INFORME DEL CLAN* 🏰     ┃\n"
    report += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
    
    report += "📊 *ESTADÍSTICAS GENERALES:*\n"
    report += "├─ 📈 *Cuentas totales:* " + f"`{len(all_accounts)}`\n"
    report += "├─ ⚔️ *Ataque total:* " + f"`{total_attack:,}`\n"
    report += "├─ 🛡️ *Defensa total:* " + f"`{total_defense:,}`\n"
    report += "├─ 📊 *Promedio por cuenta:*\n"
    report += "│  ├─ ⚔️ Ataque: " + f"`{avg_attack:,}`\n"
    report += "│  └─ 🛡️ Defensa: " + f"`{avg_defense:,}`\n\n"
    
    report += "🏆 *TOP 10 CUENTAS:*\n"
    report += "┌─────────────────────────────────────────┐\n"
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, account in enumerate(accounts_to_show[:10], 1):
        medal = medals[i - 1] if i <= 10 else f"{i}."
        username_display = account['username'][:15] + "..." if len(account['username']) > 18 else account['username']
        
        report += f"│ {medal} *{username_display:<18}*\n"
        report += f"│   ⚔️ `{account['attack']:>12,}`\n"
        report += f"│   🛡️ `{account['defense']:>12,}`\n"
        
        if i < 10 and i < len(accounts_to_show):
            report += "│   ───────────────────────\n"
    
    report += "└─────────────────────────────────────────┘\n"
    
    if len(all_accounts) > 10:
        report += f"\n📌 *... y {len(all_accounts) - 10} cuenta(s) más*\n"
    
    # Top 5 por defensa
    top_defense = sorted(all_accounts, key=lambda x: x["defense"], reverse=True)[:5]
    report += "\n🛡️ *TOP 5 DEFENSA:*\n"
    for i, acc in enumerate(top_defense, 1):
        report += f"`{i:>2}.` {acc['username'][:15]:<15} 🛡️ `{acc['defense']:,}`\n"
    
    return report

def generate_admin_report():
    data = load_data()
    if not data:
        return "📭 *No hay datos registrados aún.*"
    
    report = "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
    report += "┃   🧾 *INFORME ADMINISTRADOR*   ┃\n"
    report += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
    
    # Estadísticas globales
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
    
    report += "📈 *ESTADÍSTICAS GLOBALES:*\n"
    report += "├─ 👥 *Miembros activos:* " + f"`{total_members}`\n"
    report += "├─ 📂 *Cuentas totales:* " + f"`{total_accounts}`\n"
    report += "├─ ⚔️ *Ataque total:* " + f"`{total_attack:,}`\n"
    report += "├─ 🛡️ *Defensa total:* " + f"`{total_defense:,}`\n"
    report += "└─ 📊 *Promedio por miembro:* " + f"`{total_accounts/total_members:.1f}` cuentas\n\n"
    
    report += "👤 *DETALLE POR MIEMBRO:*\n"
    report += "┌─────────────────────────────────────────────────┐\n"
    
    # Ordenar miembros por ataque total descendente
    members_data = []
    for user_id_str, user_data in data.items():
        accounts = user_data.get("accounts", [])
        if accounts:
            user_attack = sum(acc["attack"] for acc in accounts)
            user_defense = sum(acc["defense"] for acc in accounts)
            members_data.append({
                "name": user_data.get('telegram_name', f"Usuario {user_id_str}"),
                "accounts": len(accounts),
                "attack": user_attack,
                "defense": user_defense
            })
    
    members_data.sort(key=lambda x: x["attack"], reverse=True)
    
    for member in members_data:
        report += f"│ 👤 *{member['name'][:20]:<20}*\n"
        report += f"│    📊 Cuentas: `{member['accounts']:>2}`\n"
        report += f"│    ⚔️ Ataque:  `{member['attack']:>12,}`\n"
        report += f"│    🛡️ Defensa: `{member['defense']:>12,}`\n"
        report += "│    ─────────────────────────────\n"
    
    report += "└─────────────────────────────────────────────────┘\n"
    
    # Estadísticas adicionales
    if total_accounts > 0:
        avg_attack_per_acc = total_attack // total_accounts
        avg_defense_per_acc = total_defense // total_accounts
        report += f"\n📊 *PROMEDIOS POR CUENTA:*\n"
        report += f"├─ ⚔️ Ataque promedio: `{avg_attack_per_acc:,}`\n"
        report += f"└─ 🛡️ Defensa promedio: `{avg_defense_per_acc:,}`\n"
    
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

def add_user_account(user_id: int, account_data: dict) -> bool:
    """
    Añade o actualiza una cuenta para un usuario.
    """
    try:
        user_id_str = str(user_id)
        data = load_data()
        
        # Si el usuario no existe, crear su entrada
        if user_id_str not in data:
            data[user_id_str] = {
                "telegram_name": "",  # Se actualizará después si es necesario
                "accounts": []
            }
        
        # Verificar si la cuenta ya existe para actualizarla
        accounts = data[user_id_str].get("accounts", [])
        updated = False
        
        for i, acc in enumerate(accounts):
            if acc["username"].lower() == account_data["username"].lower():
                accounts[i] = account_data  # Actualizar cuenta existente
                updated = True
                break
        
        if not updated:
            accounts.append(account_data)  # Añadir nueva cuenta
        
        data[user_id_str]["accounts"] = accounts
        
        # Actualizar el nombre de telegram si está vacío
        if not data[user_id_str].get("telegram_name"):
            user_info = get_user_info(user_id)
            if user_info and user_info.get("first_name"):
                data[user_id_str]["telegram_name"] = user_info["first_name"]
        
        # Guardar los datos actualizados
        ok = save_data_with_retry(data)
        if not ok:
            logger.error("add_user_account: fallo al guardar datos en GitHub para user %s", user_id)
            return False
        
        logger.info("Cuenta %s %s para user %s", 
                   account_data["username"], 
                   "actualizada" if updated else "añadida", 
                   user_id)
        return True
        
    except Exception as e:
        logger.exception("Error en add_user_account: %s", e)
        return False

# ================= COMANDOS PÚBLICOS =================

# ====== Notificación al Admin (debe estar definida antes de getid)

async def notify_admin_request(app_bot, user):
    """
    Envía a todos los administradores una notificación con botones para aceptar/denegar.
    """
    text = (
        f"➡️ **SOLICITUD DE ACCESO**\n\n"
        f"👤 Usuario: {user.first_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🔗 Username: @{user.username if user.username else 'No tiene'}\n\n"
        f"Acciones:"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Aceptar (Usuario)", callback_data=f"admin_request:accept:{user.id}"),
            InlineKeyboardButton("👑 Aceptar (Admin)", callback_data=f"admin_request:accept_admin:{user.id}")
        ],
        [
            InlineKeyboardButton("❌ Denegar", callback_data=f"admin_request:deny:{user.id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    sent = False
#========== Notificar a todos los administradores
    data = load_user_data()
    admin_ids = data.get("admin_ids", [])
    
    for admin_id in admin_ids:
        try:
            await app_bot.send_message(
                chat_id=admin_id, 
                text=text, 
                parse_mode="Markdown", 
                reply_markup=reply_markup
            )
            sent = True
        except Exception as e:
            logger.warning("No se pudo notificar al admin %s: %s", admin_id, e)
    
    return sent


# === SOLICITUD DE ID

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

    # Intentar notificar al admin usando la función que envía botones
    sent_to_admin = False
    try:
        sent_to_admin = await notify_admin_request(context.bot, user)
    except Exception as e:
        logger.warning("Error al notificar al admin con notify_admin_request: %s", e)
        sent_to_admin = False

    # Construir botón de contacto si hay admin configurado (comportamiento previo)
    admin_contact_url = None
    if admin_username:
        admin_contact_url = f"https://t.me/{admin_username.lstrip('@')}"
    elif admin_id:
        admin_contact_url = f"tg://user?id={admin_id}"

    if admin_contact_url:
        keyboard = [[InlineKeyboardButton("✉️ Contactar al admin", url=admin_contact_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(user_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        admin_display = str(ADMIN_USER_ID) if ADMIN_USER_ID else "No configurado"
        extra = f"\n\nID del admin: `{admin_display}`"
        await update.message.reply_text(user_text + extra, parse_mode="Markdown")
    # Si no se pudo notificar automáticamente, informar al usuario
    if not sent_to_admin:
        try:
            await update.message.reply_text(
                "⚠️ No pude notificar automáticamente al administrador. "
                "Por favor, envía tu ID manualmente o contacta al admin.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

# ====== Notificar Al Usuario Aceptado/Denegado

@restricted_callback
async def callback_admin_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja callbacks: admin_request:accept:<id> y admin_request:accept_admin:<id>
    """
    query = update.callback_query
    await query.answer()
    data = (query.data or "")
    parts = data.split(":")
    
    if len(parts) < 3:
        await safe_edit(query, "Dato inválido.")
        return

    action = parts[1]
    target_id = parts[2]

    # Validar que quien pulsa es administrador
    caller_id = query.from_user.id
    if not is_admin(caller_id):
        await query.answer("❌ No tienes permisos para realizar esta acción.", show_alert=True)
        return

    try:
        target_int = int(target_id)
    except ValueError:
        await safe_edit(query, "❌ ID inválido.")
        return

    if action == "accept":
        # Autorizar como usuario normal
        try:
            # Obtener información del usuario
            target_user = await context.bot.get_chat(target_int)
            add_authorized_user(target_int, make_admin=False, username=target_user.username, first_name=target_user.first_name)
            
            # Notificar al solicitante
            try:
                await context.bot.send_message(
                    chat_id=target_int,
                    text="✅ *Tu solicitud ha sido aceptada.*\n\n"
                         "Ahora puedes usar el bot como usuario normal.\n\n"
                         "Usa /start para comenzar.",
                    parse_mode="Markdown"
                )
            except Exception:
                logger.warning("No se pudo notificar al usuario %s tras aceptar", target_id)
            
            await safe_edit(query, f"✅ Usuario `{target_id}` autorizado como usuario normal.", parse_mode="Markdown")
            
        except Exception as e:
            logger.exception("Error al autorizar usuario %s: %s", target_id, e)
            await safe_edit(query, "❌ Error al autorizar al usuario.")
        return

    elif action == "accept_admin":
        # Autorizar como administrador
        try:
            # Obtener información del usuario
            target_user = await context.bot.get_chat(target_int)
            add_authorized_user(target_int, make_admin=True, username=target_user.username, first_name=target_user.first_name)
            
            # Notificar al solicitante
            try:
                await context.bot.send_message(
                    chat_id=target_int,
                    text="🎉 *¡Felicidades!*\n\n"
                         "Tu solicitud ha sido aceptada y has sido nombrado *administrador*.\n\n"
                         "Ahora tienes acceso completo a todas las funciones del bot.\n\n"
                         "Usa /start para ver el nuevo menú de administración.",
                    parse_mode="Markdown"
                )
            except Exception:
                logger.warning("No se pudo notificar al usuario %s tras aceptar como admin", target_id)
            
            await safe_edit(query, f"✅ Usuario `{target_id}` autorizado como *administrador*.", parse_mode="Markdown")
            
        except Exception as e:
            logger.exception("Error al autorizar usuario admin %s: %s", target_id, e)
            await safe_edit(query, "❌ Error al autorizar al usuario como administrador.")
        return

    elif action == "deny":
        # Denegar
        try:
            await context.bot.send_message(
                chat_id=target_int,
                text="❌ *Tu solicitud ha sido denegada.*\n\n"
                     "Contacta al administrador para más información.",
                parse_mode="Markdown"
            )
        except Exception:
            logger.warning("No se pudo notificar al usuario %s tras denegar", target_id)
        await safe_edit(query, f"❌ Solicitud de `{target_id}` denegada.", parse_mode="Markdown")
        return

    # Acción desconocida
    await safe_edit(query, "❌ Acción no reconocida.")


# ====== send_id_request: callback para usuarios no autorizados que envía la solicitud al admin

@restricted_callback
async def callback_send_id_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    admin_username = ADMIN_USERNAME
    admin_id = ADMIN_USER_ID if ADMIN_USER_ID != 0 else None
    sent_to_admin = False
    if ADMIN_USER_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
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
            logger.warning("No se pudo notificar al admin por username: %s", e)
    if sent_to_admin:
        await safe_edit(query, "Tu ID ha sido enviado al administrador. Espera la autorización.")
    else:
        await safe_edit(query, "No pude notificar al administrador automáticamente. Envía tu ID manualmente.")

#=========Comando HELP=======

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
    # Actualizar información del usuario
    update_user_info(user.id, user.username, user.first_name)
    
    if not is_user_authorized(user.id):
        # Obtener lista de administradores con sus usernames
        admins_info = []
        data = load_user_data()
        for admin_id in data.get("admin_ids", []):
            info = get_user_info(admin_id)
            if info:
                admins_info.append({
                    "username": info.get("username"),
                    "first_name": info.get("first_name", f"Admin {admin_id}")
                })
        
        # Construir mensaje con lista de administradores
        admin_list = ""
        for admin in admins_info:
            if admin['username']:
                admin_list += f"• @{admin['username']} ({admin['first_name']})\n"
            else:
                admin_list += f"• {admin['first_name']}\n"
        
        keyboard = [[InlineKeyboardButton("📤 Enviar ID al admin", callback_data="send_id_request")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = (
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "┃     🏰 *BOT DEL CLAN* 🏰     ┃\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"Hola *{user.first_name}*! 👋\n\n"
            "🔒 *ACCESO RESTRINGIDO*\n\n"
            "Para usar este bot necesitas autorización.\n\n"
            "👑 *CONTACTAR ADMINISTRADORES:*\n"
            f"{admin_list}\n"
            "Usa /getid para obtener tu ID y envíalo a un administrador.\n\n"
            "📌 *O usa el botón para enviar tu ID automáticamente.*"
        )
        if query:
            await query.answer()
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return
    
    accounts = get_user_accounts(user.id)
    
    # Construir menú de botones
    keyboard = [
        [
            InlineKeyboardButton("➕ Añadir cuenta", callback_data="add_account"),
            InlineKeyboardButton("📂 Mis cuentas", callback_data="my_accounts")
        ],
        [
            InlineKeyboardButton("📊 Informe clan", callback_data="clan_report"),
            InlineKeyboardButton("🏅 ⚔️=Ranking=🛡️", callback_data="my_ranking")
        ]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🧾 Vista Admin", callback_data="admin_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Construir mensaje de bienvenida
    welcome_text = (
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃     🏰 *BOT DEL CLAN* 🏰     ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"¡Hola *{user.first_name}*! 👋\n\n"
    )
    
    if accounts:
        total_attack = sum(acc["attack"] for acc in accounts)
        total_defense = sum(acc["defense"] for acc in accounts)
        avg_attack = total_attack // len(accounts)
        avg_defense = total_defense // len(accounts)
        
        welcome_text += "📊 *TUS ESTADÍSTICAS:*\n"
        welcome_text += "├─ 📈 *Cuentas registradas:* " + f"`{len(accounts)}`\n"
        welcome_text += "├─ ⚔️ *Ataque total:* " + f"`{total_attack:,}`\n"
        welcome_text += "├─ 🛡️ *Defensa total:* " + f"`{total_defense:,}`\n"
        welcome_text += "├─ 📊 *Promedio por cuenta:*\n"
        welcome_text += "│  ├─ ⚔️ Ataque: " + f"`{avg_attack:,}`\n"
        welcome_text += "│  └─ 🛡️ Defensa: " + f"`{avg_defense:,}`\n\n"
        
        # Top cuenta personal
        top_account = max(accounts, key=lambda x: x["attack"])
        welcome_text += f"🏆 *TU MEJOR CUENTA:*\n"
        welcome_text += f"└─ `{top_account['username']}` ⚔️ `{top_account['attack']:,}`\n\n"
    else:
        welcome_text += (
            "📭 *Aún no tienes cuentas registradas.*\n\n"
            "¡Comienza añadiendo tu primera cuenta!\n\n"
        )
    
    welcome_text += "🔍 *SELECCIONA UNA OPCIÓN:*"
    
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
    keyboard = [[InlineKeyboardButton("↩️ Cancelar", callback_data="menu_back")]]
    await safe_edit(query,
        "Registro de nueva cuenta.\n\nEnvía el *nombre de usuario* de la cuenta (ej: Player123).",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

    
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
            keyboard = [[InlineKeyboardButton("↩️ Volver", callback_data="menu_back")]]
            await update.message.reply_text("Nombre guardado. Ahora envía el valor de *ataque* (número).",
                                parse_mode="Markdown",
                                reply_markup=InlineKeyboardMarkup(keyboard))
            return True
    elif step == "attack":
        try:
            attack = int(text.replace(",", ""))
        except ValueError:
            await update.message.reply_text("Valor inválido. Envía un número entero para ataque.")
            return True
        context.user_data.setdefault("add_temp", {})["attack"] = attack
        context.user_data["add_step"] = "defense"
        keyboard = [[InlineKeyboardButton("↩️ Volver", callback_data="menu_back")]]
        await update.message.reply_text("Ataque guardado. Ahora envía el valor de *defensa* (número).", 
                                 parse_mode="Markdown",
                                 reply_markup=InlineKeyboardMarkup(keyboard))
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
            keyboard = [[InlineKeyboardButton("↩️ Volver", callback_data="menu_back")]]
            await update.message.reply_text("Estado perdido. Inténtalo de nuevo")
            return True

        account_data = {
            "username": username,
            "attack": attack,
            "defense": defense
        }

        add_user_account(update.effective_user.id, account_data)
        context.user_data.pop("add_step", None)
        keyboard = [[InlineKeyboardButton("↩️ Volver", callback_data="menu_back")]]
        await update.message.reply_text(f"Cuenta **{username}** registrada: Ataque {attack:,}, Defensa {defense:,}.",
                                parse_mode="Markdown",
                                reply_markup=InlineKeyboardMarkup(keyboard))
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
        await safe_edit(query, 
                       "📭 *No tienes cuentas registradas.*\n\n"
                       "¡Usa el botón '➕ Añadir cuenta' para comenzar!",
                       parse_mode="Markdown")
        return
    
    # Ordenar cuentas por ataque
    accounts.sort(key=lambda x: x["attack"], reverse=True)
    
    text = "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
    text += "┃     📂 *TUS CUENTAS* 📂     ┃\n"
    text += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
    
    text += f"📊 *Total de cuentas:* `{len(accounts)}`\n\n"
    
    total_attack = sum(acc["attack"] for acc in accounts)
    total_defense = sum(acc["defense"] for acc in accounts)
    avg_attack = total_attack // len(accounts)
    avg_defense = total_defense // len(accounts)
    
    text += "📈 *ESTADÍSTICAS:*\n"
    text += f"├─ ⚔️ Ataque total: `{total_attack:,}`\n"
    text += f"├─ 🛡️ Defensa total: `{total_defense:,}`\n"
    text += f"├─ 📊 Promedio por cuenta:\n"
    text += f"│  ├─ ⚔️ Ataque: `{avg_attack:,}`\n"
    text += f"│  └─ 🛡️ Defensa: `{avg_defense:,}`\n\n"
    
    text += "👑 *TUS CUENTAS:*\n"
    text += "┌──────────────────────────────────────┐\n"
    
    for i, acc in enumerate(accounts, 1):
        text += f"│ `{i:>2}.` *{acc['username'][:18]:<18}*\n"
        text += f"│    ⚔️ `{acc['attack']:>12,}`\n"
        text += f"│    🛡️ `{acc['defense']:>12,}`\n"
        if i < len(accounts):
            text += "│    ──────────────────────────\n"
    
    text += "└──────────────────────────────────────┘\n"
    
    # Crear botones
    keyboard = []
    for acc in accounts[:8]:  # Máximo 8 botones para no saturar
        keyboard.append([
            InlineKeyboardButton(f"✏️ {acc['username'][:8]}", 
                               callback_data=f"edit_account:{acc['username']}"),
            InlineKeyboardButton(f"🗑️ {acc['username'][:8]}", 
                               callback_data=f"delete_account:{acc['username']}")
        ])
    
    keyboard.append([InlineKeyboardButton("↩️ Volver al menú", callback_data="menu_back")])
    
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    
# clan_report: mostrar informe público desde callback

@restricted_callback
async def callback_clan_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    report = generate_public_report()
    keyboard = [[InlineKeyboardButton("↩️ Volver", callback_data="menu_back")]]
    await safe_edit(query, report, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")



# my_ranking: calcular y mostrar la posición del usuario entre todas las cuentas
@restricted_callback
async def callback_my_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    
    # Obtener el modo de ordenación (ataque o defensa) del callback_data
    data = query.data
    sort_mode = "attack"  # Por defecto
    
    if data.startswith("my_ranking:"):
        _, mode = data.split(":", 1)
        if mode in ["attack", "defense"]:
            sort_mode = mode
    
    # Guardar el modo actual en user_data para mantenerlo
    context.user_data["ranking_sort"] = sort_mode
    
    # Cargar datos
    data = load_data()
    
    # Obtener todas las cuentas
    all_accounts = []
    for user_id_str, user_data in data.items():
        for acc in user_data.get("accounts", []):
            all_accounts.append({
                "username": acc["username"],
                "attack": acc["attack"],
                "defense": acc["defense"],
                "owner": user_id_str,
                "owner_name": user_data.get("telegram_name", f"Usuario {user_id_str}")
            })
    
    if not all_accounts:
        keyboard = [[InlineKeyboardButton("↩️ Volver al menú", callback_data="menu_back")]]
        await safe_edit(query, 
                       "📭 *No hay cuentas registradas en el clan.*", 
                       reply_markup=InlineKeyboardMarkup(keyboard), 
                       parse_mode="Markdown")
        return
    
    # Obtener cuentas del usuario
    user_accounts = [acc for acc in all_accounts if acc["owner"] == str(user.id)]
    
    if not user_accounts:
        keyboard = [[InlineKeyboardButton("↩️ Volver al menú", callback_data="menu_back")]]
        await safe_edit(query, 
                       "📭 *No tienes cuentas registradas.*\n\n"
                       "¡Usa el botón '➕ Añadir cuenta' para comenzar!", 
                       reply_markup=InlineKeyboardMarkup(keyboard), 
                       parse_mode="Markdown")
        return
    
    # Ordenar según el modo seleccionado
    if sort_mode == "attack":
        all_accounts.sort(key=lambda x: x["attack"], reverse=True)
        sort_field = "attack"
        sort_emoji = "⚔️"
        sort_title = "ATAQUE"
    else:
        all_accounts.sort(key=lambda x: x["defense"], reverse=True)
        sort_field = "defense"
        sort_emoji = "🛡️"
        sort_title = "DEFENSA"
    
    # Construir informe de ranking
    report = "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
    report += f"┃     🏅 *RANKING GLOBAL* 🏅     ┃\n"
    report += f"┃      {sort_emoji} *{sort_title}* {sort_emoji}       ┃\n"
    report += "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
    
    # Estadísticas globales
    total_accounts = len(all_accounts)
    total_value = sum(acc[sort_field] for acc in all_accounts)
    avg_value = total_value // total_accounts if total_accounts else 0
    
    report += "📊 *ESTADÍSTICAS GLOBALES:*\n"
    report += f"├─ 📈 *Cuentas totales:* `{total_accounts}`\n"
    report += f"├─ {sort_emoji} *Total {sort_title.lower()}:* `{total_value:,}`\n"
    report += f"└─ 📊 *Promedio por cuenta:* `{avg_value:,}`\n\n"
    
    # TOP 10 GLOBAL
    report += f"🏆 *TOP 10 GLOBAL ({sort_title}):*\n"
    report += "┌──────────────────────────────────────────┐\n"
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for i, acc in enumerate(all_accounts[:10], 1):
        medal = medals[i - 1] if i <= 10 else f"{i}."
        username_display = acc['username'][:15] + "..." if len(acc['username']) > 18 else acc['username']
        owner_display = "Tú" if acc['owner'] == str(user.id) else acc['owner_name'][:8]
        
        # Valor del campo de ordenación
        value = acc[sort_field]
        
        report += f"│ {medal} *{username_display:<18}*\n"
        report += f"│   👤 {owner_display:<8} {sort_emoji} `{value:>12,}`\n"
        
        if i < 10 and i < len(all_accounts[:10]):
            report += "│   ───────────────────────────\n"
    
    report += "└──────────────────────────────────────────┘\n\n"
    
    # POSICIONES DEL USUARIO
    report += "👤 *TUS POSICIONES:*\n"
    
    user_total_value = sum(acc[sort_field] for acc in user_accounts)
    
    for user_acc in user_accounts:
        # Encontrar posición de esta cuenta en el ranking actual
        position = next((i+1 for i, acc in enumerate(all_accounts) 
                        if acc["username"] == user_acc["username"]), 0)
        
        if position <= 10:
            medal = medals[position-1]
            position_display = f"{medal} `{position:>2}`"
        else:
            position_display = f"`{position:>2}`"
        
        value = user_acc[sort_field]
        other_field = user_acc["defense"] if sort_mode == "attack" else user_acc["attack"]
        other_emoji = "🛡️" if sort_mode == "attack" else "⚔️"
        
        report += f"│ {position_display} *{user_acc['username']}*\n"
        report += f"│   {sort_emoji} `{value:>12,}`  {other_emoji} `{other_field:>12,}`\n"
        
        if user_acc != user_accounts[-1]:
            report += "│   ───────────────────────────\n"
    
    report += "\n"
    
    # CONTRIBUCIONES DEL USUARIO
    total_user_value = sum(acc[sort_field] for acc in user_accounts)
    percentage = (total_user_value / total_value * 100) if total_value > 0 else 0
    
    report += f"📈 *TUS CONTRIBUCIONES ({sort_title}):*\n"
    report += f"├─ {sort_emoji} *Total:* `{total_user_value:,}`\n"
    report += f"├─ 📊 *Porcentaje del clan:* `{percentage:.1f}%`\n"
    
    # Mostrar también el otro campo para contexto
    if sort_mode == "attack":
        total_user_defense = sum(acc["defense"] for acc in user_accounts)
        total_defense = sum(acc["defense"] for acc in all_accounts)
        report += f"└─ 🛡️ *Defensa total:* `{total_user_defense:,}`\n"
    else:
        total_user_attack = sum(acc["attack"] for acc in user_accounts)
        total_attack = sum(acc["attack"] for acc in all_accounts)
        report += f"└─ ⚔️ *Ataque total:* `{total_user_attack:,}`\n"
    
    # Crear botones de navegación
    keyboard = []
    
    # Botones para cambiar modo de ordenación
    if sort_mode == "attack":
        # Si estamos en ataque, ofrecemos botón para ver defensa
        keyboard.append([
            InlineKeyboardButton("⚔️ Ranking Ataque (Actual)", 
                               callback_data="my_ranking:attack"),
            InlineKeyboardButton("🛡️ Ver Ranking Defensa", 
                               callback_data="my_ranking:defense")
        ])
    else:
        # Si estamos en defensa, ofrecemos botón para ver ataque
        keyboard.append([
            InlineKeyboardButton("⚔️ Ver Ranking Ataque", 
                               callback_data="my_ranking:attack"),
            InlineKeyboardButton("🛡️ Ranking Defensa (Actual)", 
                               callback_data="my_ranking:defense")
        ])
    
    # Botón para volver al menú
    keyboard.append([InlineKeyboardButton("↩️ Volver al menú", callback_data="menu_back")])
    
    await safe_edit(query, report, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


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
async def callback_admin_manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista paginada de usuarios para administración"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("❌ No eres administrador", show_alert=True)
        return
    
    # Obtener página del callback_data
    data_parts = query.data.split(":")
    page = int(data_parts[1]) if len(data_parts) > 1 else 1
    
    # Cargar datos
    user_data = load_user_data()
    clan_data = load_data()
    
    # Obtener todos los usuarios autorizados
    authorized_ids = user_data.get("authorized_ids", [])
    admin_ids = user_data.get("admin_ids", [])
    
    # Configurar paginación
    users_per_page = 8
    total_pages = max(1, (len(authorized_ids) + users_per_page - 1) // users_per_page)
    page = max(1, min(page, total_pages))
    
    # Calcular índices
    start_idx = (page - 1) * users_per_page
    end_idx = start_idx + users_per_page
    page_users = authorized_ids[start_idx:end_idx]
    
    # Construir texto
    text = (
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃      👥 *GESTIÓN USUARIOS*      ┃\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"📊 *Usuarios autorizados:* `{len(authorized_ids)}`\n"
        f"📄 *Página {page}/{total_pages}*\n\n"
    )
    
    # Información de cada usuario
    for idx, user_id in enumerate(page_users, start_idx + 1):
        user_info = get_user_info(user_id)
        clan_user_data = clan_data.get(str(user_id), {})
        
        username = user_info.get("username", "Sin username")
        first_name = user_info.get("first_name", f"Usuario {user_id}")
        
        # Contar cuentas del usuario
        account_count = len(clan_user_data.get("accounts", []))
        
        # Calcular estadísticas
        total_attack = sum(acc["attack"] for acc in clan_user_data.get("accounts", []))
        total_defense = sum(acc["defense"] for acc in clan_user_data.get("accounts", []))
        
        # Determinar tipo
        user_type = "👑 ADMIN" if user_id in admin_ids else "👤 USUARIO"
        
        text += f"`{idx:>2}.` {user_type}\n"
        text += f"    👤 *{first_name}*\n"
        if username:
            text += f"    📧 @{username}\n"
        text += f"    🆔 `{user_id}`\n"
        text += f"    📂 Cuentas: `{account_count}`\n"
        if account_count > 0:
            text += f"    ⚔️ Total: `{total_attack:,}`\n"
            text += f"    🛡️ Total: `{total_defense:,}`\n"
        
        text += "\n"
    
    # Crear teclado con botones para cada usuario
    keyboard = []
    
    # Botones por usuario (2 por fila)
    for i in range(0, len(page_users), 2):
        row = []
        for j in range(2):
            if i + j < len(page_users):
                user_id = page_users[i + j]
                user_info = get_user_info(user_id)
                display_name = user_info.get("first_name", str(user_id))[:10]
                
                row.append(InlineKeyboardButton(
                    f"⚙️ {display_name}",
                    callback_data=f"admin_user_detail:{user_id}"
                ))
        if row:
            keyboard.append(row)
    
    # Botones de navegación
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"admin_manage_users:{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"admin_manage_users:{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Botones de acción general
    keyboard.append([
        InlineKeyboardButton("➕ Añadir Usuario", callback_data="admin_add_user_dialog"),
        InlineKeyboardButton("📋 Lista Completa", callback_data="admin_users_compact")
    ])
    
    keyboard.append([InlineKeyboardButton("↩️ Volver al Menú Admin", callback_data="admin_menu")])
    
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

@restricted_callback
async def callback_admin_manage_all_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista paginada de TODAS las cuentas para administración"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("❌ No eres administrador", show_alert=True)
        return
    
    # Obtener página del callback_data
    data_parts = query.data.split(":")
    page = int(data_parts[1]) if len(data_parts) > 1 else 1
    
    # Cargar datos
    clan_data = load_data()
    user_data = load_user_data()
    
    # Obtener TODAS las cuentas de todos los usuarios
    all_accounts = []
    for user_id_str, user_clan_data in clan_data.items():
        user_info = get_user_info(int(user_id_str))
        user_name = user_info.get("first_name", f"Usuario {user_id_str}")
        
        for account in user_clan_data.get("accounts", []):
            all_accounts.append({
                "username": account["username"],
                "attack": account["attack"],
                "defense": account["defense"],
                "owner_id": int(user_id_str),
                "owner_name": user_name
            })
    
    # Ordenar por ataque descendente
    all_accounts.sort(key=lambda x: x["attack"], reverse=True)
    
    # Configurar paginación
    accounts_per_page = 8
    total_pages = max(1, (len(all_accounts) + accounts_per_page - 1) // accounts_per_page)
    page = max(1, min(page, total_pages))
    
    # Calcular índices
    start_idx = (page - 1) * accounts_per_page
    end_idx = start_idx + accounts_per_page
    page_accounts = all_accounts[start_idx:end_idx]
    
    # Construir texto
    text = (
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃   📊 *TODAS LAS CUENTAS*   ┃\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"📊 *Total de cuentas:* `{len(all_accounts)}`\n"
        f"📄 *Página {page}/{total_pages}*\n\n"
    )
    
    # Mostrar cuentas de la página actual
    for idx, acc in enumerate(page_accounts, start_idx + 1):
        text += f"`{idx:>2}.` *{acc['username']}*\n"
        text += f"    👤 Dueño: {acc['owner_name']}\n"
        text += f"    ⚔️ Ataque: `{acc['attack']:,}`\n"
        text += f"    🛡️ Defensa: `{acc['defense']:,}`\n"
        text += f"    🆔 Owner ID: `{acc['owner_id']}`\n\n"
    
    # Si no hay cuentas
    if not all_accounts:
        text += "📭 *No hay cuentas registradas en el clan.*\n\n"
    
    # Crear teclado
    keyboard = []
    
    # Botones por cuenta (1 por fila)
    for acc in page_accounts:
        keyboard.append([
            InlineKeyboardButton(
                f"✏️ Editar {acc['username'][:10]}",
                callback_data=f"admin_edit_account:{acc['owner_id']}:{acc['username']}"
            ),
            InlineKeyboardButton(
                f"🗑️ Eliminar {acc['username'][:10]}",
                callback_data=f"admin_delete_account_confirm:{acc['owner_id']}:{acc['username']}"
            )
        ])
    
    # Botones de navegación
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"admin_manage_all_accounts:{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"admin_manage_all_accounts:{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Botones de acción
    keyboard.append([
        InlineKeyboardButton("🔍 Buscar Cuenta", callback_data="admin_search_account"),
        InlineKeyboardButton("📈 Estadísticas", callback_data="admin_accounts_stats")
    ])
    
    keyboard.append([InlineKeyboardButton("↩️ Volver al Menú Admin", callback_data="admin_menu")])
    
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

@restricted_callback
async def callback_admin_manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista de administradores"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("❌ No eres administrador", show_alert=True)
        return
    
    # Cargar datos
    user_data = load_user_data()
    admin_ids = user_data.get("admin_ids", [])
    
    # Construir texto
    text = (
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃      👑 *ADMINISTRADORES*      ┃\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"📊 *Total administradores:* `{len(admin_ids)}`\n\n"
    )
    
    # Listar administradores
    for idx, admin_id in enumerate(admin_ids, 1):
        admin_info = get_user_info(admin_id)
        username = admin_info.get("username", "Sin username")
        first_name = admin_info.get("first_name", f"Admin {admin_id}")
        
        # Marcar admin principal
        is_main = " 🏆" if admin_id == ADMIN_USER_ID else ""
        
        text += f"`{idx:>2}.` {first_name}{is_main}\n"
        text += f"    📧 @{username}\n"
        text += f"    🆔 `{admin_id}`\n"
        
        if idx < len(admin_ids):
            text += "    ─────────────────────\n"
    
    text += "\n🏆 = Administrador Principal (no se puede eliminar)\n"
    
    # Crear teclado
    keyboard = []
    
    # Botones para cada admin (excepto el principal)
    for admin_id in admin_ids:
        if admin_id == ADMIN_USER_ID:
            continue
            
        admin_info = get_user_info(admin_id)
        display_name = admin_info.get("first_name", str(admin_id))[:15]
        
        keyboard.append([
            InlineKeyboardButton(f"👤 Quitar Admin {display_name}", 
                               callback_data=f"admin_remove_admin_confirm:{admin_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("➕ Añadir Nuevo Admin", callback_data="admin_add_admin_dialog")])
    keyboard.append([InlineKeyboardButton("↩️ Volver al Menú Admin", callback_data="admin_menu")])
    
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")



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


# ===================== ADMIN MENÚ MEJORADO =====================
@restricted
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menú principal de administración - maneja tanto comandos como callbacks"""
    query = update.callback_query
    user = update.effective_user
    
    if not is_admin(user.id):
        if query:
            await query.answer("❌ No eres administrador", show_alert=True)
            return
        else:
            await update.message.reply_text("❌ Acceso denegado. Solo administradores.")
            return
    
    text = (
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃      👑 *MENÚ ADMIN* 👑      ┃\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        "👤 *Administrador:* " + (f"@{user.username}" if user.username else user.first_name) + "\n\n"
        "🔧 *Selecciona una opción:*"
    )
    
    keyboard = [
        [InlineKeyboardButton("🧾 Informe Administrador", callback_data="admin_report_full")],
        [InlineKeyboardButton("👥 Gestionar Usuarios", callback_data="admin_manage_users:1")],
        [InlineKeyboardButton("📊 Gestionar Todas las Cuentas", callback_data="admin_manage_all_accounts:1")],
        [InlineKeyboardButton("👑 Administradores", callback_data="admin_manage_admins")],
        [InlineKeyboardButton("📣 Broadcast Global", callback_data="admin_broadcast")],
        [InlineKeyboardButton("↩️ Volver al Menú Principal", callback_data="menu_back")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

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
    
    # Cargar datos
    data = load_data()
    user_data = load_user_data()
    
    if user_id_str in data:
        # Eliminar del clan
        data.pop(user_id_str)
        save_data_with_retry(data)
        
        # Eliminar de usuarios autorizados
        uid_int = int(user_id_str)
        if uid_int in user_data.get("authorized_ids", []):
            user_data["authorized_ids"].remove(uid_int)
            if uid_int in user_data.get("admin_ids", []):
                user_data["admin_ids"].remove(uid_int)
            save_user_data(user_data)
        
        context.user_data.pop("admin_confirm_delete_user", None)
        await safe_edit(query, f"✅ Usuario `{user_id_str}` eliminado completamente.", parse_mode="Markdown")
    else:
        await safe_edit(query, "❌ Usuario no encontrado.", parse_mode="Markdown")

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
async def callback_admin_report_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el informe completo de administrador"""
    query = update.callback_query
    await query.answer()
    
    report = generate_admin_report()  # Usa tu función existente
    keyboard = [[InlineKeyboardButton("↩️ Volver al Menú Admin", callback_data="admin_menu")]]
    await safe_edit(query, report, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

@restricted_callback
async def callback_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el proceso de broadcast global"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["awaiting_broadcast"] = True
    keyboard = [[InlineKeyboardButton("❌ Cancelar", callback_data="admin_menu")]]
    await safe_edit(query, 
                   "📣 *ENVIAR BROADCAST GLOBAL*\n\n"
                   "Envía el mensaje que quieres enviar a todos los usuarios.\n"
                   "Puedes usar formato Markdown.",
                   reply_markup=InlineKeyboardMarkup(keyboard),
                   parse_mode="Markdown")

async def handle_broadcast_message_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return False
    if not context.user_data.pop("awaiting_broadcast", False):
        return False
    
    text = update.message.text
    clan_data = load_data()
    user_data = load_user_data()
    
    sent = 0
    failed = 0
    batch_size = 20
    
    # Obtener TODOS los usuarios autorizados
    all_users = user_data.get("authorized_ids", [])
    
    for i in range(0, len(all_users), batch_size):
        batch = all_users[i : i + batch_size]
        for uid in batch:
            try:
                await context.bot.send_message(chat_id=uid, text=_safe_text(text))
                sent += 1
            except Exception:
                failed += 1
        await asyncio.sleep(0.5)
    
    await update.message.reply_text(
        f"📣 *Broadcast completado*\n\n"
        f"✅ Enviados: `{sent}`\n"
        f"❌ Fallos: `{failed}`\n"
        f"👥 Total usuarios: `{len(all_users)}`",
        parse_mode="Markdown"
    )
    return True

@restricted_callback
async def callback_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para botones que no deben hacer nada"""
    query = update.callback_query
    await query.answer()  # Solo responde sin cambiar nada

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
        await update.message.reply_text("❌ Acceso denegado.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "👤 *Añadir Usuario*\n\n"
            "Uso: `/adduser <user_id>`\n\n"
            "Ejemplo: `/adduser 123456789`",
            parse_mode="Markdown"
        )
        return
    
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID inválido. Debe ser un número.")
        return
    
    # Verificar si ya existe
    user_data = load_user_data()
    if uid in user_data.get("authorized_ids", []):
        await update.message.reply_text(f"ℹ️ El usuario `{uid}` ya está autorizado.", parse_mode="Markdown")
        return
    
    # Intentar obtener información del usuario
    try:
        target_user = await context.bot.get_chat(uid)
        username = target_user.username
        first_name = target_user.first_name
    except Exception:
        username = None
        first_name = f"Usuario {uid}"
    
    # Añadir usuario
    if add_authorized_user(uid, make_admin=False, username=username, first_name=first_name):
        await update.message.reply_text(
            f"✅ *Usuario añadido correctamente*\n\n"
            f"🆔 ID: `{uid}`\n"
            f"👤 Nombre: {first_name}\n"
            f"📧 Username: @{username if username else 'No tiene'}\n\n"
            f"El usuario ya puede usar el bot con /start",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Error al añadir usuario. Revisa los logs.")

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

    # Callbacks básicos
    application.add_handler(CallbackQueryHandler(callback_add_account_start, pattern=r"^add_account$"))
    application.add_handler(CallbackQueryHandler(callback_add_confirm_overwrite, pattern=r"^add_confirm_overwrite:"))
    application.add_handler(CallbackQueryHandler(callback_add_cancel_overwrite, pattern=r"^add_cancel_overwrite$"))
    application.add_handler(CallbackQueryHandler(callback_my_accounts, pattern=r"^my_accounts$"))
    application.add_handler(CallbackQueryHandler(callback_clan_report, pattern=r"^clan_report$"))
    application.add_handler(CallbackQueryHandler(callback_my_ranking, pattern=r"^my_ranking(:attack|:defense)?$"))
    application.add_handler(CallbackQueryHandler(callback_send_id_request, pattern=r"^send_id_request$"))
    application.add_handler(CallbackQueryHandler(callback_group_report, pattern=r"^group_report$"))
    application.add_handler(CallbackQueryHandler(callback_group_admin, pattern=r"^group_admin$"))
    application.add_handler(CallbackQueryHandler(callback_admin_request, pattern=r"^admin_request:(accept|accept_admin|deny):\d+$"))

    # Callbacks de cuentas
    application.add_handler(CallbackQueryHandler(callback_accounts_pagination, pattern=r"^accounts_(next|prev)$"))
    application.add_handler(CallbackQueryHandler(callback_edit_account_start, pattern=r"^edit_account:"))
    application.add_handler(CallbackQueryHandler(callback_delete_own_account, pattern=r"^delete_account:"))
    application.add_handler(CallbackQueryHandler(callback_confirm_delete_account, pattern=r"^confirm_delete_account:"))
    application.add_handler(CallbackQueryHandler(callback_cancel_delete_account, pattern=r"^cancel_delete_account$"))
    application.add_handler(CallbackQueryHandler(callback_menu_back, pattern=r"^menu_back$"))

    # Callbacks del menú admin (NUEVOS)
    application.add_handler(CallbackQueryHandler(admin_menu, pattern=r"^admin_menu$"))
    application.add_handler(CallbackQueryHandler(callback_admin_report_full, pattern=r"^admin_report_full$"))
    application.add_handler(CallbackQueryHandler(callback_admin_manage_users, pattern=r"^admin_manage_users:\d+$"))
    application.add_handler(CallbackQueryHandler(callback_admin_manage_all_accounts, pattern=r"^admin_manage_all_accounts:\d+$"))
    application.add_handler(CallbackQueryHandler(callback_admin_manage_admins, pattern=r"^admin_manage_admins$"))
    application.add_handler(CallbackQueryHandler(callback_admin_broadcast, pattern=r"^admin_broadcast$"))
    application.add_handler(CallbackQueryHandler(callback_noop, pattern=r"^noop$"))

    # Callbacks de administración (eliminar - MANTENER para compatibilidad)
    application.add_handler(CallbackQueryHandler(callback_admin_delete_user_confirm, pattern=r"^admin_delete_user_confirm:"))
    application.add_handler(CallbackQueryHandler(callback_admin_delete_user, pattern=r"^admin_delete_user:"))
    application.add_handler(CallbackQueryHandler(callback_admin_cancel_delete, pattern=r"^admin_cancel_delete$"))
    application.add_handler(CallbackQueryHandler(callback_admin_delete_account_confirm, pattern=r"^admin_delete_account_confirm:"))
    application.add_handler(CallbackQueryHandler(callback_admin_delete_account, pattern=r"^admin_delete_account:"))

    # Handlers antiguos (ELIMINAR o comentar)
    # application.add_handler(CallbackQueryHandler(callback_admin_users_pagination, pattern=r"^admin_users_(next|prev)$"))
    # application.add_handler(CallbackQueryHandler(callback_admin_user_view, pattern=r"^admin_user:"))

    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    # Set bot commands
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
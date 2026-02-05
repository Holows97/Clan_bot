import os
import json
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Configuración de logs para Render
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Variables de entorno (Render las provee)
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
DATA_FILE = "clan_data.json"

# ===== Funciones auxiliares =====
def load_data():
    return json.load(open(DATA_FILE)) if os.path.exists(DATA_FILE) else {}

def save_data(data):
    json.dump(data, open(DATA_FILE, "w"), indent=2)

# ===== Comandos =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bienvenido al Bot del Clan 🏰\nUsa /miid para obtener tu ID y enviárselo al admin.")

async def miid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"🆔 Tu ID de Telegram es: {uid}\nEnvíalo al admin para que te registre.")

async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("⛔ Solo el admin puede añadir usuarios")
    if not context.args:
        return await update.message.reply_text("Uso: /adduser <id>")
    uid = context.args[0]
    data = load_data()
    if uid not in data:
        data[uid] = {"accounts": []}
        save_data(data)
        await update.message.reply_text(f"✅ Usuario {uid} añadido")
    else:
        await update.message.reply_text("⚠️ Usuario ya existe")

async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    data = load_data()
    if uid not in data:
        return await update.message.reply_text("⛔ No estás autorizado, pide al admin que te registre")
    if len(context.args) != 3:
        return await update.message.reply_text("Uso: /registrar <usuario> <ataque> <defensa>")
    nombre, atk, dfs = context.args[0], int(context.args[1]), int(context.args[2])
    data[uid]["accounts"].append({"username": nombre, "attack": atk, "defense": dfs})
    save_data(data)
    await update.message.reply_text(f"✅ Cuenta {nombre} registrada")

async def informe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total_atk = sum(acc["attack"] for u in data.values() for acc in u["accounts"])
    total_def = sum(acc["defense"] for u in data.values() for acc in u["accounts"])
    msg = f"🏆 INFORME DEL CLAN 🏆\n⚔️ Ataque total: {total_atk}\n🛡️ Defensa total: {total_def}"
    await update.message.reply_text(msg)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("⛔ Solo el admin puede ver esto")
    data = load_data()
    msg = "👑 PANEL ADMIN\n"
    for uid, info in data.items():
        msg += f"\nUsuario {uid}:\n"
        for acc in info["accounts"]:
            msg += f"• {acc['username']} ⚔️ {acc['attack']} 🛡️ {acc['defense']}\n"
    await update.message.reply_text(msg)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("⛔ Solo el admin puede enviar mensajes masivos")
    if not context.args:
        return await update.message.reply_text("Uso: /broadcast <mensaje>")
    mensaje = " ".join(context.args)
    data = load_data()
    for uid in data.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=mensaje)
        except Exception as e:
            logging.error(f"Error enviando mensaje a {uid}: {e}")
    await update.message.reply_text("✅ Mensaje enviado a todos los usuarios registrados")

# ===== Main =====
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("miid", miid))
    app.add_handler(CommandHandler("adduser", adduser))
    app.add_handler(CommandHandler("registrar", registrar))
    app.add_handler(CommandHandler("informe", informe))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Render usa webhook
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )

    # Para pruebas locales en Termux, comenta lo anterior y usa:
    # app.run_polling()

if __name__ == "__main__":
    main()

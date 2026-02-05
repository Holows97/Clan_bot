import os, json, logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
DATA_FILE = "clan_data.json"

logging.basicConfig(level=logging.INFO)

def load_data():
    return json.load(open(DATA_FILE)) if os.path.exists(DATA_FILE) else {}

def save_data(data):
    json.dump(data, open(DATA_FILE, "w"), indent=2)

# ===== Comandos =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bienvenido al Bot del Clan 🏰")

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

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("adduser", adduser))
    app.add_handler(CommandHandler("registrar", registrar))
    app.add_handler(CommandHandler("informe", informe))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.run_polling()

if __name__ == "__main__":
    main()

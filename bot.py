#!/usr/bin/env python3
"""
BOT DEL CLAN - VERSIÓN SUPER SIMPLE
100% compatible con v20.7
"""

import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')

print("=" * 60)
print("🤖 BOT INICIANDO - VERSIÓN 20.7")
print(f"TOKEN: {'✅' if TOKEN else '❌'}")
print(f"ADMIN: {ADMIN_ID}")
print("=" * 60)

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Archivo de datos
DATA_FILE = 'data.json'

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

# ========== COMANDOS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    user = update.effective_user
    
    # Menú simple
    keyboard = [
        [InlineKeyboardButton("📊 Ranking", callback_data='ranking')],
        [InlineKeyboardButton("📝 Registrar", callback_data='register')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Hola {user.first_name}! 👋\n\n"
        "Usa los botones para interactuar:",
        reply_markup=reply_markup
    )

async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /getid"""
    user = update.effective_user
    await update.message.reply_text(f"Tu ID: `{user.id}`", parse_mode='Markdown')

async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar ranking"""
    data = load_data()
    
    if not data:
        msg = "📭 No hay datos aún."
    else:
        # Simple ranking
        msg = "🏆 **RANKING** 🏆\n\n"
        # Aquí iría la lógica del ranking
    
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar botones"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'ranking':
        await ranking(update, context)
    elif query.data == 'register':
        await query.edit_message_text("Para registrar, envía:\n`/registrar usuario ataque defensa`", parse_mode='Markdown')

async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registro simple por comando"""
    if len(context.args) != 3:
        await update.message.reply_text("Uso: /registrar <usuario> <ataque> <defensa>")
        return
    
    try:
        usuario = context.args[0]
        ataque = int(context.args[1])
        defensa = int(context.args[2])
        user_id = update.effective_user.id
        
        # Guardar
        data = load_data()
        if str(user_id) not in data:
            data[str(user_id)] = {'accounts': []}
        
        data[str(user_id)]['accounts'].append({
            'usuario': usuario,
            'ataque': ataque,
            'defensa': defensa
        })
        
        save_data(data)
        
        await update.message.reply_text(
            f"✅ Registrado!\n"
            f"👤 {usuario}\n"
            f"⚔️ {ataque:,}\n"
            f"🛡️ {defensa:,}"
        )
    except:
        await update.message.reply_text("❌ Error. Usa: /registrar usuario ataque defensa")

# ========== MAIN ==========
def main():
    """Función principal"""
    print("🚀 INICIANDO BOT...")
    
    # Verificar token
    if not TOKEN:
        print("❌ ERROR: BOT_TOKEN no configurado")
        return
    
    # Crear aplicación (v20.7)
    app = Application.builder().token(TOKEN).build()
    
    # Registrar handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getid", getid))
    app.add_handler(CommandHandler("registrar", registrar))
    app.add_handler(CommandHandler("ranking", ranking))
    
    # Botones
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Bot configurado. Iniciando polling...")
    
    # Iniciar
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()

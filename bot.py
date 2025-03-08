import logging
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, ChatMemberHandler
)
from datetime import timezone

# Ersetzen Sie 'YOUR_NEW_BOT_TOKEN' durch den neuen Token Ihres Bots nach dem Wechsel

BOT_TOKEN = '7671853978:AAEb-a3bHU2hDQdqqXwqnj79i_SKq5IEMsg'

# Datei zum Speichern der registrierten Chats
DATA_FILE = 'registered_chats.json'

# Laden der Liste der registrierten Chats
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        registered_chats = set(tuple(chat) for chat in json.load(f))
else:
    registered_chats = set()

# Wörterbuch zur Speicherung der Benutzerdaten
user_data = {}

# Konfiguration des Loggings
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO  # Setzen Sie auf logging.DEBUG für detaillierte Logs
)

# Wörterbuch zur Speicherung der geplanten Aufgaben
scheduled_jobs = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return

    user_id = update.effective_user.id
    logging.info(f"Empfangene /start Anfrage von Benutzer mit ID: {user_id}")

    keyboard = [
        [
            InlineKeyboardButton("📂 Chats ansehen", callback_data='view_chats'),
            InlineKeyboardButton("📤 Nachricht senden", callback_data='send_message'),
        ],
        [
            InlineKeyboardButton("🛑 Verteilung stoppen", callback_data='stop_broadcast'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📋 Wählen Sie eine Aktion:",
        reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return

    user_id = update.effective_user.id
    logging.info(f"Benutzer {user_id} hat Hilfe angefordert.")

    await update.message.reply_text(
        "ℹ️ Dieser Bot ermöglicht das Senden von Nachrichten 📤 in alle Chats, in denen er hinzugefügt wurde. 📂\n\n"
        "🔧 Verfügbare Befehle:\n"
        "/start - Starten Sie die Arbeit mit dem Bot 🚀\n"
        "/help - Zeigen Sie diese Nachricht an ❓\n"
        "/stop - Stoppen Sie die aktuelle Verteilung 🛑"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    logging.info(f"Benutzer {user_id} hat die Schaltfläche {query.data} gedrückt.")

    if query.data == 'view_chats':
        if registered_chats:
            chat_list = '\n'.join([f"{chat_title} ({chat_id})" for chat_id, chat_title in registered_chats])
            await query.message.reply_text(f"📂 Der Bot ist in folgenden Chats hinzugefügt:\n{chat_list}")
        else:
            await query.message.reply_text("🚫 Der Bot ist in keinem Chat hinzugefügt.")
    elif query.data == 'send_message':
        user_data[user_id] = {'state': 'awaiting_interval'}
        await query.message.reply_text("⏰ Bitte geben Sie das Intervall in Minuten für das Senden der Nachricht ein.")
    elif query.data == 'stop_broadcast':
        # Stoppen der aktuellen Verteilung
        if user_id in scheduled_jobs:
            job = scheduled_jobs[user_id]
            job.schedule_removal()
            del scheduled_jobs[user_id]
            await query.message.reply_text("🛑 Die Verteilung wurde gestoppt.")
        else:
            await query.message.reply_text("❌ Keine aktive Verteilung.")


async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logging.info(f"Nachricht von Benutzer {user_id} empfangen.")

    if user_id in user_data:
        state = user_data[user_id].get('state')
        if state == 'awaiting_interval':
            # Empfang des Intervalls
            try:
                interval = int(update.message.text)
                if interval <= 0:
                    raise ValueError
                user_data[user_id]['interval'] = interval
                user_data[user_id]['state'] = 'awaiting_broadcast_message'
                await update.message.reply_text(
                    f"⏰ Das Intervall wurde auf {interval} Minuten eingestellt.\n✉️ Jetzt senden Sie bitte die Nachricht für die Verteilung."
                )
            except ValueError:
                await update.message.reply_text("⚠️ Bitte geben Sie eine positive ganze Zahl ein.")
        elif state == 'awaiting_broadcast_message':
            # Empfang der Nachricht zur Verteilung
            message_to_forward = update.message
            interval = user_data[user_id]['interval']

            # Überprüfen, ob registrierte Chats vorhanden sind
            if not registered_chats:
                await update.message.reply_text("🚫 Der Bot ist in keinem Chat hinzugefügt.")
                user_data[user_id]['state'] = None
                return

            # Erstellen einer Aufgabe für die periodische Verteilung
            job_queue = context.job_queue

            if job_queue is None:
                logging.error("JobQueue ist nicht initialisiert.")
                await update.message.reply_text("⚠️ Ein Fehler ist aufgetreten: JobQueue ist nicht initialisiert.")
                return

            # Entfernen der vorherigen Aufgabe, falls vorhanden
            if user_id in scheduled_jobs:
                scheduled_jobs[user_id].schedule_removal()

            job = job_queue.run_repeating(
                send_scheduled_message,
                interval=interval * 60,  # Intervall in Sekunden
                first=0,
                data={'message': message_to_forward, 'chats': registered_chats, 'user_id': user_id}
            )
            scheduled_jobs[user_id] = job

            await update.message.reply_text(
                f"📤 Die Verteilung wurde gestartet. Die Nachricht wird alle {interval} Minuten gesendet."
            )

            user_data[user_id]['state'] = None

            # Zurück zu den Schaltflächen
            await start(update, context)
        else:
            pass
    else:
        pass


async def send_scheduled_message(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    message_to_forward = job_data['message']
    chats = job_data['chats']
    user_id = job_data['user_id']

    from_chat_id = message_to_forward.chat_id
    message_id = message_to_forward.message_id

    for chat_id, chat_title in chats:
        try:
            await context.bot.forward_message(
                chat_id=chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id
            )
            logging.info(f"✅ Nachricht an Chat {chat_title} ({chat_id}) gesendet.")
        except Exception as e:
            logging.error(f"❌ Nachricht an Chat {chat_title} ({chat_id}) konnte nicht gesendet werden: {e}")


async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member

    chat = result.chat
    chat_id = chat.id
    chat_title = chat.title or chat.full_name or chat.username or str(chat.id)
    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status

    logging.info(f"📁 Update my_chat_member: Chat '{chat_title}' ({chat_id}), alter Status: {old_status}, neuer Status: {new_status}")

    if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
        registered_chats.add((chat_id, chat_title))
        save_registered_chats()
        logging.info(f"✅ Der Bot wurde dem Chat {chat_title} ({chat_id}) hinzugefügt.")
    elif new_status in ['left', 'kicked']:
        registered_chats.discard((chat_id, chat_title))
        save_registered_chats()
        logging.info(f"❌ Der Bot wurde aus dem Chat {chat_title} ({chat_id}) entfernt.")


def save_registered_chats():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(registered_chats), f, ensure_ascii=False)


def main():
    # Erstellen der Anwendung
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Befehls-Handler
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))

    # Schaltflächen-Handler
    app.add_handler(CallbackQueryHandler(button_handler))

    # Handler für das Hinzufügen/Entfernen des Bots aus Chats
    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    # Handler für Nachrichten von Benutzern
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.PRIVATE & (~filters.COMMAND), receive_message))

    # Starten des Bots
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()


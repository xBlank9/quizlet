import telebot
import os

TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN environment variable before running.")

bot = telebot.TeleBot(TOKEN, parse_mode=None)

@bot.message_handler(func=lambda m: True)
def show_group_id(m):
    chat = m.chat
    if chat.type in ['group', 'supergroup']:
        text = f"Group: {chat.title}\nID: {chat.id}"
        print(text)
        try:
            bot.send_message(m.from_user.id, text)
        except Exception as e:
            print("Cannot send private message:", e)

if __name__ == '__main__':
    print("Bot running... it will print and send you the group ID when it sees any message.")
    bot.infinity_polling(timeout=20, long_polling_timeout=5)

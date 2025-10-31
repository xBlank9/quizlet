import os
import telebot

TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['leave'])
def leave_group(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(message.chat.id, "❗استخدم الأمر كده:\n/leave <group_id>")
            return

        group_id = int(parts[1])
        bot.leave_chat(group_id)
        bot.send_message(message.chat.id, f"✅ تم الخروج من الجروب {group_id}.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ حصل خطأ:\n{e}")

bot.polling()

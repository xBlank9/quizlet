import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, filters, ContextTypes
from telegram.error import Forbidden

# إعداد الـ Logging لطباعة المعلومات في لوحة تحكم Zeabur
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- الدالة الأساسية ---
async def send_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    تعمل هذه الدالة عند استقبال أمر /start في جروب.
    """
    # التأكد من أن الأمر جاء من جروب
    if update.message.chat.type in [filters.ChatType.GROUP, filters.ChatType.SUPERGROUP]:
        
        chat_id = update.message.chat.id
        chat_title = update.message.chat.title
        
        user_id = update.message.from_user.id
        user_name = update.message.from_user.first_name

        # --- الخطوة 1: طباعة الـ ID في اللوجز (Zeabur Logs) ---
        # هذا هو الضمان 100% أنك ستحصل على الـ ID
        logger.info(f"--- /start COMMAND DETECTED ---")
        logger.info(f"Group Title: {chat_title}")
        logger.info(f"Group ID: {chat_id}")
        logger.info(f"Triggered by User: {user_name} (ID: {user_id})")
        
        print("\n" + "*"*30)
        print(f"BINGO: Group ID is: {chat_id}")
        print("*"*30 + "\n")

        # --- الخطوة 2: محاولة إرسال الـ ID لك على الخاص ---
        message_to_user = (
            f"مرحباً {user_name}!\n"
            f"ايدي الجروب '{chat_title}' هو:\n`{chat_id}`"
        )
        
        try:
            # محاولة إرسال الرسالة للخاص
            await context.bot.send_message(chat_id=user_id, text=message_to_user, parse_mode='Markdown')
            logger.info(f"Successfully sent ID to user {user_id} in DM.")
            
        except Forbidden:
            logger.warning(f"Failed to send DM to user {user_id}.")
            logger.warning("REASON: User has not started a chat with the bot first.")
            logger.warning("Don't worry, the Group ID is printed above in the logs.")
        except Exception as e:
            logger.error(f"An unknown error occurred while sending DM: {e}")

        # البوت سيظل يعمل ولن يغادر
        logger.info("Task complete. Bot remains in group and continues running.")


def main() -> None:
    """الدالة الرئيسية لتشغيل البوت"""
    
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN:
        logger.error("Error: TELEGRAM_TOKEN environment variable not set!")
        return

    application = Application.builder().token(TOKEN).build()

    # إضافة "مستمع" لأمر /start فقط في الجروبات
    handler = CommandHandler("start", send_group_id, filters=filters.ChatType.GROUPS)
    application.add_handler(handler)

    logger.info("Bot is running. Waiting for /start command in the group...")
    print("Bot started. Go to your group and type /start")

    # تشغيل البوت بشكل مستمر
    application.run_polling()


if __name__ == "__main__":
    main()

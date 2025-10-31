import logging
import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# إعداد الـ Logging لطباعة المعلومات في لوحة تحكم Zeabur
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- الدالة الأساسية ---
# هذه الدالة سيتم استدعاؤها عند إرسال *أي* رسالة في الجروب
async def get_id_and_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    تعمل هذه الدالة عند استقبال أي رسالة في جروب.
    """
    # التأكد من أن الرسالة من جروب (group) أو سوبر جروب (supergroup)
    if update.message.chat.type in [filters.ChatType.GROUP, filters.ChatType.SUPERGROUP]:
        
        chat_id = update.message.chat.id
        chat_title = update.message.chat.title

        # 1. طباعة الـ ID والعنوان في الـ Logs (ستراها في Zeabur)
        logger.info(f"--- DETECTED GROUP ---")
        logger.info(f"Title: {chat_title}")
        logger.info(f"ID: {chat_id}")
        logger.info(f"----------------------")
        
        # رسالة طباعة واضحة جداً للـ Log
        print(f"\n*** BINGO: Group ID is: {chat_id} (Title: {chat_title}) ***\n")

        try:
            # 2. محاولة مغادرة الجروب
            await context.bot.leave_chat(chat_id=chat_id)
            logger.info(f"Successfully left group: {chat_title} ({chat_id})")
            
        except Exception as e:
            logger.error(f"Failed to leave chat {chat_id}: {e}")
            
        finally:
            # 3. إيقاف البوت عن العمل
            # هذا مهم لإيقاف العملية بعد تنفيذ المهمة
            logger.info("Task complete. Shutting down application.")
            context.application.stop()

def main() -> None:
    """الدالة الرئيسية لتشغيل البوت"""
    
    # قراءة التوكن من متغيرات البيئة (Environment Variables) في Zeabur
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN:
        logger.error("Error: TELEGRAM_TOKEN environment variable not set!")
        return

    # بناء التطبيق
    application = Application.builder().token(TOKEN).build()

    # إضافة "مستمع" للرسائل
    # هذا المستمع سيفعل الدالة get_id_and_leave
    # عند استقبال أي رسالة نصية (filters.TEXT) في جروب (filters.ChatType.GROUPS)
    handler = MessageHandler(filters.TEXT & filters.ChatType.GROUPS, get_id_and_leave)
    application.add_handler(handler)

    logger.info("Bot is running. Waiting for a message in the group...")
    print("Bot started in polling mode. Go to your group and type any message.")

    # تشغيل البوت (سيظل يعمل حتى يتم استدعاء application.stop())
    application.run_polling()
    
    logger.info("Bot has stopped.")
    print("Process finished.")


if __name__ == "__main__":
    main()

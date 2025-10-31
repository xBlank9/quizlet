import os
import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)
from telegram.error import Forbidden, BadRequest

# --- إعدادات أساسية ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- دالة للتحقق من أنك الأدمن ---
def is_admin(update: Update) -> bool:
    """يتحقق إذا كان المستخدم هو الأدمن المحدد في الإعدادات"""
    admin_id = os.environ.get("ADMIN_ID")
    if not admin_id:
        logger.warning("متغير ADMIN_ID غير موجود!")
        return False
    return str(update.effective_user.id) == admin_id

# --- الدالة الأولى: لكشف ID الجروب ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    هذه الدالة تعمل في كل مكان.
    إذا تم استدعاؤها من جروب، سترسل ID الجروب لك في الخاص.
    """
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    # إذا كان الأمر في جروب أو سوبر جروب
    if chat_type in ["group", "supergroup"]:
        admin_id = os.environ.get("ADMIN_ID")
        chat = update.effective_chat
        
        if not admin_id:
            logger.error("ADMIN_ID غير معين، لا يمكن إرسال التقرير.")
            return

        # تجهيز الرسالة لإرسالها لك في الخاص
        text = (
            f"ℹ️ **معلومات مجموعة**\n\n"
            f"تم إرسال /start في المجموعة:\n"
            f"**اسم المجموعة:** {chat.title}\n"
            f"**ID:** `{chat.id}`\n\n"
            f"يمكنك الآن استخدام هذا الـ ID لإخراجي بالأمر:\n"
            f"`/leavegroup {chat.id}`"
        )
        try:
            # إرسال معلومات الجروب إلى محادثتك الخاصة
            await context.bot.send_message(chat_id=admin_id, text=text, parse_mode=ParseMode.MARKDOWN)
            # الرد في الجروب (اختياري)
            await update.message.reply_text("تم إرسال معلومات هذا الجروب إلى الأدمن.")
        except Forbidden:
            logger.error(f"فشل إرسال المعلومات. هل قمت بحظر البوت الخاص بك؟")
        except Exception as e:
            logger.error(f"فشل إرسال معلومات الجروب للأدمن: {e}")
    
    # إذا كان الأمر في محادثة خاصة
    elif chat_type == "private":
        if is_admin(update):
            await update.message.reply_text("أنا في وضع الصيانة وجاهز لاستقبال أوامر الأدمن. استخدم `/leavegroup <ID>` لطردي من مجموعة.")
        else:
            await update.message.reply_text("البوت في وضع الصيانة حاليًا.")

# --- الدالة الثانية: لإجبار البوت على المغادرة ---
async def leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر للأدمن فقط لإجبار البوت على مغادرة جروب معين"""
    
    # التأكد أنك الأدمن وأنك ترسل الأمر في الخاص
    if not is_admin(update):
        return # يتجاهل الأمر إذا لم يكن من الأدمن
    
    if update.effective_chat.type != "private":
        await update.message.reply_text("لأسباب أمنية، هذا الأمر يعمل في المحادثات الخاصة فقط.")
        return

    # التأكد من وجود ID مع الأمر
    if not context.args:
        await update.message.reply_text("الرجاء تحديد ID المجموعة. مثال:\n`/leavegroup -100123456789`")
        return
        
    try:
        chat_id_to_leave = int(context.args[0])
        await context.bot.leave_chat(chat_id=chat_id_to_leave)
        await update.message.reply_text(f"✅ لقد غادرت المجموعة ذات الـ ID: `{chat_id_to_leave}` بنجاح.")
    except (ValueError, IndexError):
         await update.message.reply_text("الـ ID غير صالح. يجب أن يكون رقمًا صحيحًا (غالبًا يبدأ بسالب).")
    except BadRequest as e:
        if "Chat not found" in str(e):
            await update.message.reply_text("لم أتمكن من العثور على مجموعة بهذا الـ ID.")
        else:
            await update.message.reply_text(f"حدث خطأ: {e}")
    except Exception as e:
        await update.message.reply_text(f"لم أتمكن من مغادرة المجموعة. الخطأ: {e}")

# --- دالة التشغيل الرئيسية ---
def main() -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("TELEGRAM_TOKEN not set.")
    
    application = Application.builder().token(token).build()
    
    # تفعيل الأوامر
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("leavegroup", leave_group))
    
    application.run_polling()

if __name__ == "__main__":
    main()

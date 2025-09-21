import os
import logging
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import Forbidden

# --- Configuration ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- State definitions ---
GETTING_QUIZ_FILE = range(1)

# --- File paths and in-memory storage ---
QUIZZES_FILE = "quizzes.json"
quizzes = {}

# --- Helper Functions ---

def load_quizzes():
    """Loads quizzes from the JSON file into memory on startup."""
    global quizzes
    try:
        with open(QUIZZES_FILE, 'r', encoding='utf-8') as f:
            quizzes = json.load(f)
        logger.info(f"Successfully loaded {len(quizzes)} quizzes.")
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning(f"{QUIZZES_FILE} not found or invalid. Starting fresh.")
        quizzes = {}

def save_quizzes():
    """Saves the current quizzes from memory to the JSON file."""
    with open(QUIZZES_FILE, 'w', encoding='utf-8') as f:
        json.dump(quizzes, f, ensure_ascii=False, indent=4)
    logger.info(f"Quizzes saved to {QUIZZES_FILE}.")

def is_admin(update: Update) -> bool:
    """Checks if the user sending the command is the admin."""
    admin_id = os.environ.get("ADMIN_ID")
    return str(update.effective_user.id) == admin_id

def parse_quiz_file_line_by_line(file_content: str) -> list:
    """
    A robust, line-by-line parser that doesn't depend on blank lines between questions.
    """
    questions = []
    current_question = None
    
    # Normalize newlines and split into lines
    lines = file_content.replace('\r\n', '\n').strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith('+'):
            if current_question:
                current_question['correct'] = line[1:].strip()
        elif line.startswith('-'):
            if current_question:
                current_question['incorrect'].append(line[1:].strip())
        else: # This line must be a new question
            # Save the previous question if it's complete
            if current_question and current_question.get('correct'):
                questions.append(current_question)
            
            # Start a new question
            current_question = {
                "question": line,
                "correct": None,
                "incorrect": []
            }
    
    # Append the last question in the file
    if current_question and current_question.get('correct'):
        questions.append(current_question)
        
    return questions

# --- User Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows a list of available quizzes or admin info."""
    user = update.effective_user
    if is_admin(update):
        await update.message.reply_html(
            f"أهلاً بك أيها المدير 👑\n\n"
            f"استخدم /createquiz [اسم] لإضافة اختبار.\n"
            f"استخدم /deletequiz [اسم] لحذف اختبار.\n\n"
            f"للمستخدمين، ستظهر قائمة الاختبارات المتاحة:"
        )

    if not quizzes:
        await update.message.reply_text("أهلاً بك! لا توجد اختبارات متاحة حاليًا. 😕")
        return

    keyboard = [[InlineKeyboardButton(name, callback_data=f"startquiz_{name}")] for name in quizzes]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("الرجاء اختيار الاختبار الذي تريد البدء به:", reply_markup=reply_markup)

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts a quiz based on button selection."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    quiz_name = query.data.split('_', 1)[1]
    
    if quiz_name not in quizzes:
        await query.edit_message_text("عذرًا، هذا الاختبار لم يعد متاحًا.")
        return

    # Store user and quiz info for the session
    context.user_data.update({
        'quiz_name': quiz_name,
        'question_index': 0,
        'score': 0,
        'quiz_questions': quizzes[quiz_name],
        'user_info': {'id': user.id, 'name': user.full_name, 'username': user.username}
    })

    await query.edit_message_text(f"حسنًا! لنبدأ اختبار: **{quiz_name}**")
    await send_question(query.message.chat_id, context)

async def send_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Sends the current question."""
    q_index = context.user_data['question_index']
    questions = context.user_data['quiz_questions']
    
    q_data = questions[q_index]
    options = [q_data['correct']] + q_data['incorrect']
    random.shuffle(options)
    
    context.user_data['correct_answer'] = q_data['correct']
    
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"ans_{opt}")] for opt in options]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(chat_id, text=f"**السؤال {q_index + 1}:**\n\n{q_data['question']}", reply_markup=reply_markup)

async def handle_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the user's answer."""
    query = update.callback_query
    await query.answer()

    selected_answer = query.data.split('_', 1)[1]
    correct_answer = context.user_data.get('correct_answer')
    
    if selected_answer == correct_answer:
        context.user_data['score'] += 1
        result_text = "✅ صحيح!"
    else:
        result_text = f"❌ خطأ. الإجابة الصحيحة هي: {correct_answer}"

    await query.edit_message_text(text=f"{query.message.text}\n\nإجابتك: {selected_answer}\n\n{result_text}")

    context.user_data['question_index'] += 1
    
    if context.user_data['question_index'] < len(context.user_data['quiz_questions']):
        await send_question(query.message.chat_id, context)
    else:
        await end_quiz(query.message.chat_id, context)

async def end_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Ends the quiz, shows the score, and notifies the admin."""
    # User-facing message
    score = context.user_data.get('score', 0)
    total = len(context.user_data.get('quiz_questions', []))
    quiz_name = context.user_data.get('quiz_name', '')
    
    await context.bot.send_message(
        chat_id,
        text=f"🎉 انتهى اختبار '{quiz_name}'!\n\nنتيجتك النهائية هي: {score} من {total}.\n\nلبدء اختبار آخر، أرسل /start."
    )

    # Admin notification
    admin_id = os.environ.get("ADMIN_ID")
    user_info = context.user_data.get('user_info', {})
    if admin_id and user_info:
        user_name = user_info.get('name')
        user_username = f"(@{user_info.get('username')})" if user_info.get('username') else ""
        user_id = user_info.get('id')
        
        notification_text = (
            f"📊 **نتيجة اختبار جديدة**\n\n"
            f"**المستخدم:** {user_name} {user_username}\n"
            f"**ID:** `{user_id}`\n"
            f"**الاختبار:** {quiz_name}\n"
            f"**النتيجة:** {score} من {total}"
        )
        try:
            await context.bot.send_message(chat_id=admin_id, text=notification_text, parse_mode='Markdown')
        except Forbidden:
            logger.warning("Bot is blocked by the admin, can't send notification.")
        except Exception as e:
            logger.error(f"Failed to send notification to admin: {e}")

    context.user_data.clear()

# --- Admin Command Handlers ---

async def create_quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the quiz creation process (Admin only)."""
    if not is_admin(update):
        return ConversationHandler.END

    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم للاختبار. مثال:\n`/createquiz lecture_1`")
        return ConversationHandler.END

    context.user_data['new_quiz_name'] = " ".join(context.args)
    await update.message.reply_text(f"سنقوم بإنشاء اختبار باسم '{context.user_data['new_quiz_name']}'.\nأرسل ملف .txt الآن.")
    return GETTING_QUIZ_FILE

async def receive_quiz_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives, parses, and saves the quiz file (Admin only)."""
    quiz_name = context.user_data.get('new_quiz_name')
    try:
        file = await update.message.document.get_file()
        file_content = (await file.download_as_bytearray()).decode('utf-8')
        parsed_questions = parse_quiz_file_line_by_line(file_content)
        
        if not parsed_questions:
            await update.message.reply_text("لم أجد أسئلة صالحة. تأكد من أن كل سؤال يحتوي على إجابة صحيحة واحدة (+) على الأقل.")
            return ConversationHandler.END

        quizzes[quiz_name] = parsed_questions
        save_quizzes()
        await update.message.reply_text(f"✅ تم حفظ اختبار '{quiz_name}' بنجاح ويحتوي على {len(parsed_questions)} سؤال.")
        
    except Exception as e:
        logger.error(f"Error processing quiz file: {e}")
        await update.message.reply_text("حدث خطأ أثناء معالجة الملف.")
    
    context.user_data.clear()
    return ConversationHandler.END

async def delete_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes a quiz (Admin only)."""
    if not is_admin(update): return
    if not context.args:
        await update.message.reply_text("استخدام الأمر: `/deletequiz [اسم الاختبار الكامل]`")
        return
        
    quiz_name_to_delete = " ".join(context.args)
    if quiz_name_to_delete in quizzes:
        del quizzes[quiz_name_to_delete]
        save_quizzes()
        await update.message.reply_text(f"🗑️ تم حذف اختبار '{quiz_name_to_delete}' بنجاح.")
    else:
        await update.message.reply_text(f"لم أجد اختبارًا بهذا الاسم.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current operation."""
    if is_admin(update):
        await update.message.reply_text("تم إلغاء العملية.")
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    load_quizzes()

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("TELEGRAM_TOKEN not set.")
        
    application = Application.builder().token(token).build()

    create_conv = ConversationHandler(
        entry_points=[CommandHandler("createquiz", create_quiz_start)],
        states={GETTING_QUIZ_FILE: [MessageHandler(filters.Document.TXT, receive_quiz_file)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("deletequiz", delete_quiz))
    application.add_handler(create_conv)
    application.add_handler(CallbackQueryHandler(start_quiz_callback, pattern="^startquiz_"))
    application.add_handler(CallbackQueryHandler(handle_answer_callback, pattern="^ans_"))
    
    application.run_polling()

if __name__ == "__main__":
    main()

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
GETTING_QUIZ_FILE, QUIZ_IN_PROGRESS = range(2)

# --- File paths and in-memory storage ---
QUIZZES_FILE = "quizzes.json"
quizzes = {}

# --- Helper Functions ---

def load_quizzes():
    global quizzes
    try:
        with open(QUIZZES_FILE, 'r', encoding='utf-8') as f: quizzes = json.load(f)
        logger.info(f"Successfully loaded {len(quizzes)} quizzes.")
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning(f"{QUIZZES_FILE} not found or invalid. Starting fresh.")
        quizzes = {}

def save_quizzes():
    with open(QUIZZES_FILE, 'w', encoding='utf-8') as f: json.dump(quizzes, f, ensure_ascii=False, indent=4)
    logger.info(f"Quizzes saved to {QUIZZES_FILE}.")

def is_admin(update: Update) -> bool:
    admin_id = os.environ.get("ADMIN_ID")
    return str(update.effective_user.id) == admin_id

def parse_quiz_file_line_by_line(file_content: str) -> list:
    questions, current_question = [], None
    lines = file_content.replace('\r\n', '\n').strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        if line.startswith('+'):
            if current_question: current_question['correct'] = line[1:].strip()
        elif line.startswith('-'):
            if current_question: current_question['incorrect'].append(line[1:].strip())
        else:
            if current_question and current_question.get('correct'): questions.append(current_question)
            current_question = {"question": line, "correct": None, "incorrect": []}
    if current_question and current_question.get('correct'): questions.append(current_question)
    return questions

# --- User Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_admin(update):
        await update.message.reply_html(
            f"أهلاً بك أيها المدير 👑\n\n"
            f"استخدم /createquiz [اسم] لإضافة اختبار.\n"
            f"استخدم /deletequiz [اسم] لحذف اختبار."
        )

    if not quizzes:
        await update.message.reply_text("أهلاً بك! لا توجد اختبارات متاحة حاليًا. 😕")
        return

    keyboard = [[InlineKeyboardButton(name, callback_data=f"startquiz_{name}")] for name in quizzes]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("الرجاء اختيار الاختبار الذي تريد البدء به:", reply_markup=reply_markup)

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    quiz_name = query.data.split('_', 1)[1]
    if quiz_name not in quizzes:
        await query.edit_message_text("عذرًا، هذا الاختبار لم يعد متاحًا.")
        return ConversationHandler.END

    context.user_data.update({
        'quiz_name': quiz_name, 'question_index': 0, 'score': 0,
        'quiz_questions': quizzes[quiz_name],
        'user_info': {'id': user.id, 'name': user.full_name, 'username': user.username}
    })

    await query.edit_message_text(f"حسنًا! لنبدأ اختبار: **{quiz_name}**\nكل سؤال له مؤقت 45 ثانية.")
    await send_question(query.message.chat_id, context)
    return QUIZ_IN_PROGRESS

async def send_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    q_index = context.user_data['question_index']
    questions = context.user_data['quiz_questions']
    q_data = questions[q_index]
    options = [q_data['correct']] + q_data['incorrect']
    random.shuffle(options)
    context.user_data['correct_answer'] = q_data['correct']
    
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"ans_{opt}")] for opt in options]
    # Add the "Stop Quiz" button
    keyboard.append([InlineKeyboardButton("⏹️ إيقاف الاختبار", callback_data="stop_quiz_prompt")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await context.bot.send_message(
        chat_id, text=f"**السؤال {q_index + 1} (⏳ 45 ثانية):**\n\n{q_data['question']}",
        reply_markup=reply_markup, parse_mode='Markdown'
    )
    
    job = context.job_queue.run_once(
        on_timer_end, 45, # Timer is now 45 seconds
        data={'chat_id': chat_id, 'message_id': message.message_id, 'question_index': q_index},
        name=f"timer_{chat_id}_{message.message_id}"
    )
    context.user_data['timer_job'] = job

async def on_timer_end(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id, message_id, q_index_when_fired = job_data['chat_id'], job_data['message_id'], job_data['question_index']
    if context.user_data.get('question_index') == q_index_when_fired:
        correct_answer = context.user_data.get('correct_answer')
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"⏰ انتهى الوقت!\n\nالإجابة الصحيحة هي: {correct_answer}")
        await process_next_question(chat_id, context)

async def handle_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if 'timer_job' in context.user_data and context.user_data['timer_job']:
        context.user_data['timer_job'].schedule_removal()
        context.user_data['timer_job'] = None

    selected_answer = query.data.split('_', 1)[1]
    correct_answer = context.user_data.get('correct_answer')
    
    if selected_answer == correct_answer:
        context.user_data['score'] += 1
        result_text = "✅ صحيح!"
    else:
        result_text = f"❌ خطأ. الإجابة الصحيحة هي: {correct_answer}"

    await query.edit_message_text(text=f"{query.message.text}\n\nإجابتك: {selected_answer}\n\n{result_text}")
    await process_next_question(query.message.chat_id, context)
    return QUIZ_IN_PROGRESS

async def process_next_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Helper function to advance the quiz."""
    context.user_data['question_index'] += 1
    if context.user_data['question_index'] < len(context.user_data['quiz_questions']):
        await send_question(chat_id, context)
    else:
        await end_quiz(chat_id, context, context.application)

async def end_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE, application: Application) -> int:
    # Remove timer if the last action was to stop
    if 'timer_job' in context.user_data and context.user_data['timer_job']:
        context.user_data['timer_job'].schedule_removal()

    score, total = context.user_data.get('score', 0), len(context.user_data.get('quiz_questions', []))
    quiz_name, user_info = context.user_data.get('quiz_name', ''), context.user_data.get('user_info', {})
    
    await application.bot.send_message(
        chat_id,
        text=f"🎉 انتهى اختبار '{quiz_name}'!\n\nنتيجتك النهائية هي: {score} من {total}.\n\nلبدء اختبار آخر، أرسل /start."
    )

    admin_id = os.environ.get("ADMIN_ID")
    if admin_id and user_info:
        user_name = user_info.get('name')
        user_username = f"(@{user_info.get('username')})" if user_info.get('username') else ""
        notification_text = (f"📊 **نتيجة اختبار جديدة**\n\n"
                             f"**المستخدم:** {user_name} {user_username}\n**ID:** `{user_info.get('id')}`\n"
                             f"**الاختبار:** {quiz_name}\n**النتيجة:** {score} من {total}")
        try:
            await application.bot.send_message(chat_id=admin_id, text=notification_text, parse_mode='Markdown')
        except Forbidden: logger.warning("Bot is blocked by the admin.")
        except Exception as e: logger.error(f"Failed to send notification to admin: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# --- Stop Quiz Handlers ---
async def stop_quiz_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("✅ نعم، قم بالإنهاء", callback_data="stop_quiz_confirm")],
        [InlineKeyboardButton("◀️ لا، متابعة الاختبار", callback_data="stop_quiz_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="هل أنت متأكد أنك تريد إنهاء الاختبار؟", reply_markup=reply_markup)
    return QUIZ_IN_PROGRESS

async def stop_quiz_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تم إنهاء الاختبار بناءً على طلبك.")
    return await end_quiz(query.message.chat_id, context, context.application)

async def stop_quiz_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    # Delete the confirmation message and resend the question
    await query.delete_message()
    await send_question(query.message.chat_id, context)
    return QUIZ_IN_PROGRESS

# --- Admin Handlers --- (No changes here)
async def create_quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update): return ConversationHandler.END
    if not context.args:
        await update.message.reply_text("استخدام الأمر: `/createquiz [اسم الاختبار]`"); return ConversationHandler.END
    context.user_data['new_quiz_name'] = " ".join(context.args)
    await update.message.reply_text(f"سنقوم بإنشاء اختبار باسم '{context.user_data['new_quiz_name']}'.\nأرسل ملف .txt الآن.")
    return GETTING_QUIZ_FILE

async def receive_quiz_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    quiz_name = context.user_data.get('new_quiz_name')
    try:
        file = await update.message.document.get_file()
        file_content = (await file.download_as_bytearray()).decode('utf-8')
        parsed_questions = parse_quiz_file_line_by_line(file_content)
        if not parsed_questions: await update.message.reply_text("لم أجد أسئلة صالحة."); return ConversationHandler.END
        quizzes[quiz_name] = parsed_questions
        save_quizzes()
        await update.message.reply_text(f"✅ تم حفظ اختبار '{quiz_name}' بنجاح ويحتوي على {len(parsed_questions)} سؤال.")
    except Exception as e: logger.error(f"Error processing quiz file: {e}"); await update.message.reply_text("حدث خطأ ما.")
    context.user_data.clear()
    return ConversationHandler.END

async def delete_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not context.args: await update.message.reply_text("استخدام الأمر: `/deletequiz [اسم الاختبار الكامل]`"); return
    quiz_name = " ".join(context.args)
    if quiz_name in quizzes:
        del quizzes[quiz_name]; save_quizzes()
        await update.message.reply_text(f"🗑️ تم حذف اختبار '{quiz_name}' بنجاح.")
    else: await update.message.reply_text(f"لم أجد اختبارًا بهذا الاسم.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'quiz_questions' in context.user_data: # If in a quiz, end it gracefully
        await update.message.reply_text("تم إنهاء الاختبار الحالي.")
        return await end_quiz(update.message.chat_id, context, context.application)
    else: # If in another process like createquiz
        await update.message.reply_text("تم إلغاء العملية.")
        context.user_data.clear()
        return ConversationHandler.END

def main() -> None:
    load_quizzes()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("TELEGRAM_TOKEN not set.")
    
    application = Application.builder().token(token).build()
    
    take_quiz_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_quiz_callback, pattern="^startquiz_")],
        states={
            QUIZ_IN_PROGRESS: [
                CallbackQueryHandler(handle_answer_callback, pattern="^ans_"),
                CallbackQueryHandler(stop_quiz_prompt, pattern="^stop_quiz_prompt$"),
                CallbackQueryHandler(stop_quiz_confirm, pattern="^stop_quiz_confirm$"),
                CallbackQueryHandler(stop_quiz_cancel, pattern="^stop_quiz_cancel$"),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=3600 # 1 hour timeout for the conversation
    )

    create_conv = ConversationHandler(
        entry_points=[CommandHandler("createquiz", create_quiz_start)],
        states={GETTING_QUIZ_FILE: [MessageHandler(filters.Document.TXT, receive_quiz_file)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("deletequiz", delete_quiz))
    application.add_handler(create_conv)
    application.add_handler(take_quiz_conv_handler)
    
    application.run_polling()

if __name__ == "__main__":
    main()

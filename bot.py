import os
import logging
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler
)
from telegram.error import Forbidden

# --- Configuration ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- State definitions ---
QUIZ_IN_PROGRESS = range(1)

# --- In-memory storage ---
quizzes = {}

# --- Helper Functions ---

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

def load_quizzes_from_folder():
    global quizzes
    quizzes_dir = "quizzes"
    if not os.path.isdir(quizzes_dir):
        logger.warning(f"Quizzes directory '{quizzes_dir}' not found. Creating it.")
        os.makedirs(quizzes_dir)
        return

    for filename in os.listdir(quizzes_dir):
        if filename.endswith(".txt"):
            quiz_name = os.path.splitext(filename)[0].replace("_", " ")
            filepath = os.path.join(quizzes_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f: file_content = f.read()
                parsed_questions = parse_quiz_file_line_by_line(file_content)
                if parsed_questions:
                    quizzes[quiz_name] = parsed_questions
                    logger.info(f"Loaded quiz '{quiz_name}' with {len(parsed_questions)} questions.")
            except Exception as e:
                logger.error(f"Failed to load or parse quiz file {filename}: {e}")

# --- User Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not quizzes:
        await update.message.reply_text("أهلاً بك! لا توجد اختبارات متاحة حاليًا. 😕")
        return

    keyboard = [[InlineKeyboardButton(name, callback_data=f"startquiz_{name}")] for name in sorted(quizzes.keys())]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("أهلاً بك! 👋\n\nالرجاء اختيار الاختبار الذي تريد البدء به:", reply_markup=reply_markup)

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    quiz_name = query.data.split('_', 1)[1]
    if quiz_name not in quizzes:
        await query.edit_message_text("عذرًا، هذا الاختبار لم يعد متاحًا."); return ConversationHandler.END

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
    
    # --- NEW: Control Row with smaller buttons ---
    control_row = [
        InlineKeyboardButton("⏹️ إيقاف", callback_data="stop_quiz_prompt"),
        InlineKeyboardButton("🎯 نتيجتي", callback_data="show_score")
    ]
    keyboard.append(control_row)
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await context.bot.send_message(
        chat_id, text=f"**السؤال {q_index + 1} (⏳ 45 ثانية):**\n\n{q_data['question']}",
        reply_markup=reply_markup, parse_mode='Markdown'
    )
    
    job = context.job_queue.run_once(
        on_timer_end, 45,
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
        context.user_data['timer_job'].schedule_removal(); context.user_data['timer_job'] = None

    selected_answer = query.data.split('_', 1)[1]
    correct_answer = context.user_data.get('correct_answer')
    
    if selected_answer == correct_answer: context.user_data['score'] += 1; result_text = "✅ صحيح!"
    else: result_text = f"❌ خطأ. الإجابة الصحيحة هي: {correct_answer}"

    await query.edit_message_text(text=f"{query.message.text}\n\nإجابتك: {selected_answer}\n\n{result_text}")
    await process_next_question(query.message.chat_id, context)
    return QUIZ_IN_PROGRESS

async def process_next_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['question_index'] += 1
    if context.user_data['question_index'] < len(context.user_data['quiz_questions']):
        await send_question(chat_id, context)
    else:
        await end_quiz(chat_id, context, context.application)

async def end_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE, application: Application) -> int:
    if 'timer_job' in context.user_data and context.user_data['timer_job']: context.user_data['timer_job'].schedule_removal()

    score, total = context.user_data.get('score', 0), len(context.user_data.get('quiz_questions', []))
    quiz_name, user_info = context.user_data.get('quiz_name', ''), context.user_data.get('user_info', {})
    
    await application.bot.send_message(chat_id, text=f"🎉 انتهى اختبار '{quiz_name}'!\n\nنتيجتك النهائية هي: {score} من {total}.\n\nلبدء اختبار آخر، أرسل /start.")

    admin_id = os.environ.get("ADMIN_ID")
    if admin_id and user_info:
        user_name = user_info.get('name'); user_username = f"(@{user_info.get('username')})" if user_info.get('username') else ""
        notification_text = (f"📊 **نتيجة اختبار جديدة**\n\n"
                             f"**المستخدم:** {user_name} {user_username}\n**ID:** `{user_info.get('id')}`\n"
                             f"**الاختبار:** {quiz_name}\n**النتيجة:** {score} من {total}")
        try: await application.bot.send_message(chat_id=admin_id, text=notification_text, parse_mode='Markdown')
        except Forbidden: logger.warning("Bot is blocked by the admin.")
        except Exception as e: logger.error(f"Failed to send notification to admin: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# --- In-Quiz Action Handlers ---
async def stop_quiz_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    keyboard = [[InlineKeyboardButton("✅ نعم، قم بالإنهاء", callback_data="stop_quiz_confirm")],
                [InlineKeyboardButton("◀️ لا، متابعة", callback_data="stop_quiz_cancel")]]
    await query.edit_message_text(text="هل أنت متأكد أنك تريد إنهاء الاختبار؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return QUIZ_IN_PROGRESS

async def stop_quiz_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.edit_message_text("تم إنهاء الاختبار بناءً على طلبك.")
    return await end_quiz(query.message.chat_id, context, context.application)

async def stop_quiz_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.delete_message()
    await send_question(query.message.chat_id, context)
    return QUIZ_IN_PROGRESS

async def show_score_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    score = context.user_data.get('score', 0)
    q_index = context.user_data.get('question_index', 0)
    await query.answer(text=f"نتيجتك الحالية: {score} / {q_index}", show_alert=True)
    return QUIZ_IN_PROGRESS

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'quiz_questions' in context.user_data:
        await update.message.reply_text("تم إنهاء الاختبار الحالي.")
        return await end_quiz(update.message.chat_id, context, context.application)
    return ConversationHandler.END

def main() -> None:
    load_quizzes_from_folder()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("TELEGRAM_TOKEN not set.")
    
    application = Application.builder().token(token).build()
    
    take_quiz_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_quiz_callback, pattern="^startquiz_")],
        states={
            QUIZ_IN_PROGRESS: [
                CallbackQueryHandler(handle_answer_callback, pattern="^ans_"),
                CallbackQueryHandler(stop_quiz_prompt, pattern="^stop_quiz_prompt$"),
                CallbackQueryHandler(stop_quiz_confirm, pattern="^stop_quiz_confirm$"),
                CallbackQueryHandler(stop_quiz_cancel, pattern="^stop_quiz_cancel$"),
                CallbackQueryHandler(show_score_callback, pattern="^show_score$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=3600
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(take_quiz_conv)
    application.run_polling()

if __name__ == "__main__":
    main()

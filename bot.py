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
    if not os.path.isdir(quizzes_dir): os.makedirs(quizzes_dir); return

    for filename in os.listdir(quizzes_dir):
        if filename.endswith(".txt"):
            quiz_name = os.path.splitext(filename)[0].replace("_", " ")
            filepath = os.path.join(quizzes_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f: file_content = f.read()
                parsed_questions = parse_quiz_file_line_by_line(file_content)
                if parsed_questions: quizzes[quiz_name] = parsed_questions; logger.info(f"Loaded quiz '{quiz_name}'")
            except Exception as e: logger.error(f"Failed to load quiz file {filename}: {e}")

# --- User-facing Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the main menu of quizzes."""
    await show_main_menu(update)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE = None):
    """Generates and shows the main quiz selection menu."""
    message_object = update.message or update.callback_query.message
    
    if not quizzes:
        await message_object.reply_text("أهلاً بك! لا توجد اختبارات متاحة حاليًا. 😕")
        return

    keyboard = [[InlineKeyboardButton(name, callback_data=f"infopage_{name}")] for name in sorted(quizzes.keys())]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "أهلاً بك! 👋\n\nالرجاء اختيار الاختبار الذي تريد البدء به:"
    
    # If called from a callback, edit the message. Otherwise, send a new one.
    if isinstance(update, Update) and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await message_object.reply_text(text, reply_markup=reply_markup)

async def quiz_info_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a confirmation page with quiz details before starting."""
    query = update.callback_query
    await query.answer()
    
    quiz_name = query.data.split('_', 1)[1]
    if quiz_name not in quizzes:
        await query.edit_message_text("عذرًا، هذا الاختبار لم يعد متاحًا."); return

    num_questions = len(quizzes[quiz_name])
    text = (
        f"أنت على وشك بدء اختبار:\n\n"
        f"**📖 اسم الاختبار:** {quiz_name}\n"
        f"**🔢 عدد الأسئلة:** {num_questions}\n"
        f"**⏱️ الوقت لكل سؤال:** 45 ثانية\n\n"
        f"هل أنت مستعد؟"
    )
    keyboard = [
        [InlineKeyboardButton("🚀 ابدأ الاختبار", callback_data=f"startquiz_{quiz_name}")],
        [InlineKeyboardButton("🔙 عودة للقائمة", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Actually starts the quiz after user confirmation."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    quiz_name = query.data.split('_', 1)[1]
    
    context.user_data.update({
        'quiz_name': quiz_name, 'question_index': 0, 'score': 0,
        'quiz_questions': quizzes[quiz_name],
        'user_info': {'id': user.id, 'name': user.full_name, 'username': user.username}
    })

    await query.edit_message_text(f"تمام! لنبدأ اختبار: **{quiz_name}**")
    await send_question(query.message.chat_id, context)
    return QUIZ_IN_PROGRESS

async def send_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    q_index = context.user_data['question_index']
    questions = context.user_data['quiz_questions']
    total_questions = len(questions)
    q_data = questions[q_index]
    options = [q_data['correct']] + q_data['incorrect']
    random.shuffle(options)
    context.user_data['correct_answer'] = q_data['correct']
    
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"ans_{opt}")] for opt in options]
    keyboard.append([InlineKeyboardButton("⏹️ إيقاف الاختبار", callback_data="stop_quiz_prompt")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    question_header = f"**السؤال {q_index + 1} من {total_questions} (⏳ 45 ثانية):**"
    message_text = f"{question_header}\n\n{q_data['question']}"
    
    message = await context.bot.send_message(chat_id, text=message_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    job = context.job_queue.run_once(
        on_timer_end, 45,
        data={'chat_id': chat_id, 'message_id': message.message_id, 'question_index': q_index},
        name=f"timer_{chat_id}_{message.message_id}"
    )
    context.user_data['timer_job'] = job

# --- Quiz Logic (Timer, Answering, Ending) ---
async def on_timer_end(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id, msg_id, q_index_fired = job_data['chat_id'], job_data['message_id'], job_data['question_index']
    if context.user_data.get('question_index') == q_index_fired:
        correct_answer = context.user_data.get('correct_answer')
        q_text = (await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=f"⏰ انتهى الوقت!")).text
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=f"{q_text}\n\nالإجابة الصحيحة هي: {correct_answer}")
        await process_next_question(chat_id, context)

async def handle_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    if 'timer_job' in context.user_data and context.user_data.get('timer_job'):
        context.user_data['timer_job'].schedule_removal()

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

async def end_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE, application: Application, stopped_by_user: bool = False) -> int:
    if 'timer_job' in context.user_data and context.user_data.get('timer_job'):
        context.user_data['timer_job'].schedule_removal()

    score, total = context.user_data.get('score', 0), len(context.user_data.get('quiz_questions', []))
    quiz_name, user_info = context.user_data.get('quiz_name', ''), context.user_data.get('user_info', {})
    
    await application.bot.send_message(
        chat_id, text=f"🎉 انتهى اختبار '{quiz_name}'!\n\nنتيجتك النهائية هي: {score} من {total}.\n\nلبدء اختبار آخر، أرسل /start."
    )
    admin_id = os.environ.get("ADMIN_ID")
    if admin_id and user_info:
        user_name = user_info.get('name'); user_username = f"(@{user_info.get('username')})" if user_info.get('username') else ""
        status = "⏹️ تم إيقافه بواسطة المستخدم" if stopped_by_user else "✅ اكتمل"
        notification_text = (
            f"📊 **نتيجة اختبار جديدة**\n\n"
            f"**المستخدم:** {user_name} {user_username}\n"
            f"**ID:** `{user_info.get('id')}`\n"
            f"**الاختبار:** {quiz_name}\n"
            f"**النتيجة:** {score} من {total}\n"
            f"**الحالة:** {status}"
        )
        try: await application.bot.send_message(chat_id=admin_id, text=notification_text, parse_mode='Markdown')
        except Exception as e: logger.error(f"Failed to send notification to admin: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# --- In-Quiz Action Handlers (Stop, Cancel) ---
async def stop_quiz_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    keyboard = [[InlineKeyboardButton("✅ نعم، قم بالإنهاء", callback_data="stop_quiz_confirm")],
                [InlineKeyboardButton("◀️ لا، متابعة", callback_data="stop_quiz_cancel")]]
    await query.edit_message_text(text="هل أنت متأكد أنك تريد إنهاء الاختبار؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return QUIZ_IN_PROGRESS

async def stop_quiz_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.edit_message_text("تم إنهاء الاختبار بناءً على طلبك.")
    return await end_quiz(query.message.chat_id, context, context.application, stopped_by_user=True)

async def stop_quiz_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.delete_message()
    await send_question(query.message.chat_id, context)
    return QUIZ_IN_PROGRESS

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'quiz_questions' in context.user_data: # If user is in a quiz
        await update.message.reply_text("✅ تم إلغاء الاختبار الحالي بنجاح.")
        return await end_quiz(update.message.chat_id, context, context.application, stopped_by_user=True)
    else: # If user is not in a quiz
        await update.message.reply_text("لا يوجد شيء لإلغائه حاليًا. أرسل /start لبدء اختبار.")
        return ConversationHandler.END
        
def main() -> None:
    load_quizzes_from_folder()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("TELEGRAM_TOKEN not set.")
    
    application = Application.builder().token(token).build()
    
    # A conversation handler to manage the quiz process
    quiz_conversation_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_quiz_callback, pattern="^confirmstart_")],
        states={
            QUIZ_IN_PROGRESS: [
                CallbackQueryHandler(handle_answer_callback, pattern="^ans_"),
                CallbackQueryHandler(stop_quiz_prompt, pattern="^stop_quiz_prompt$"),
                CallbackQueryHandler(stop_quiz_confirm, pattern="^stop_quiz_confirm$"),
                CallbackQueryHandler(stop_quiz_cancel, pattern="^stop_quiz_cancel$"),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=3600 # 1 hour timeout
    )
    
    # Handlers for the main menu and info pages
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(quiz_info_page_callback, pattern="^infopage_"))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^back_to_menu$"))
    application.add_handler(quiz_conversation_handler) # Add the conversation handler
    
    application.run_polling()

if __name__ == "__main__":
    main()


import os
import logging
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, PollAnswerHandler, ConversationHandler
)
from telegram.error import Forbidden

# --- Configuration ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- State definitions ---
QUIZ_IN_PROGRESS = range(1)

# --- In-memory storage ---
quizzes = {}
user_sessions = {}

# --- Helper Functions ---

def load_quizzes_from_folder():
    """Loads all .txt quizzes from the 'quizzes' directory."""
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

def parse_quiz_file_line_by_line(file_content: str) -> list:
    """A robust, line-by-line parser for a single quiz file."""
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

# --- Main Menu and Quiz Start ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the main menu of quizzes, preventing interruption of an active quiz."""
    if update.effective_chat.id in user_sessions:
        await update.message.reply_text(
            "أنت بالفعل في منتصف اختبار. 🙅‍♂️\n"
            "الرجاء إكماله أولاً، أو استخدم الأمر /cancel لإلغائه وبدء اختبار جديد."
        )
        return
    await show_main_menu(update)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE = None):
    """Generates and shows the main quiz selection menu."""
    message_object = update.message or update.callback_query.message
    if not quizzes:
        await message_object.reply_text("أهلاً بك! لا توجد اختبارات متاحة حاليًا. 😕"); return

    keyboard = [[InlineKeyboardButton(name, callback_data=f"infopage_{name}")] for name in sorted(quizzes.keys())]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "**أهلاً بك!** 👋\n\nالرجاء اختيار الاختبار الذي تريد البدء به:"
    
    if isinstance(update, Update) and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await message_object.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def quiz_info_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a confirmation page with quiz details before starting."""
    query = update.callback_query; await query.answer()
    quiz_name = query.data.split('_', 1)[1]
    if quiz_name not in quizzes: await query.edit_message_text("عذرًا، هذا الاختبار لم يعد متاحًا."); return

    num_questions = len(quizzes[quiz_name])
    text = (f"أنت على وشك بدء اختبار:\n\n**📖 اسم الاختبار:** {quiz_name}\n**🔢 عدد الأسئلة:** {num_questions}\n**⏱️ الوقت لكل سؤال:** 45 ثانية\n\nهل أنت مستعد؟")
    keyboard = [[InlineKeyboardButton("🚀 ابدأ الاختبار", callback_data=f"startquiz_{quiz_name}")], [InlineKeyboardButton("🔙 عودة للقائمة", callback_data="back_to_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the quiz session and sends the first poll."""
    query = update.callback_query; await query.answer()
    user = query.from_user; chat_id = query.message.chat_id
    quiz_name = query.data.split('_', 1)[1]
    
    user_sessions[chat_id] = {
        'quiz_name': quiz_name, 'question_index': 0, 'score': 0, 'quiz_questions': quizzes[quiz_name],
        'user_info': {'id': user.id, 'name': user.full_name, 'username': user.username}
    }
    
    # NEW: Improved cancel reminder message
    text = (
        f"تمام! لنبدأ اختبار: **{quiz_name}**\n\n"
        f"لإلغاء الاختبار في أي وقت، يمكنك استخدام الأمر التالي:\n"
        f"`/cancel`"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    await send_poll_question(chat_id, context)
    return QUIZ_IN_PROGRESS

# --- Poll-based Quiz Logic ---

async def send_poll_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Sends the current question as a quiz poll."""
    session = user_sessions.get(chat_id)
    if not session: return

    q_index = session['question_index']
    questions = session['quiz_questions']
    
    if q_index >= len(questions):
        await end_quiz(chat_id, context, is_completed=True); return

    q_data = questions[q_index]
    question_text = f"({q_index + 1}/{len(questions)}) {q_data['question']}"
    options = [q_data['correct']] + q_data['incorrect']
    random.shuffle(options)
    correct_option_id = options.index(q_data['correct'])
    
    message = await context.bot.send_poll(
        chat_id=chat_id, question=question_text, options=options, type='quiz',
        correct_option_id=correct_option_id, open_period=45, is_anonymous=False
    )
    session['current_poll_id'] = message.poll.id

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles a user's answer to a poll."""
    answer = update.poll_answer
    user_id = answer.user.id
    session = user_sessions.get(user_id)
    
    if not session or session.get('current_poll_id') != answer.poll_id: return QUIZ_IN_PROGRESS

    if answer.option_ids[0] == session.get('correct_option_id'):
        session['score'] += 1

    session['question_index'] += 1
    await send_poll_question(user_id, context)
    return QUIZ_IN_PROGRESS

async def end_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE, is_completed: bool, custom_message: str = None):
    """Ends the quiz, sends results, and notifies the admin."""
    session = user_sessions.get(chat_id)
    if not session: return

    if custom_message:
        await context.bot.send_message(chat_id, text=custom_message)
        await show_main_menu(type('obj', (object,), {'message': context.bot.send_message, 'callback_query': None})(), context)


    score, total, quiz_name, user_info = session['score'], len(session['quiz_questions']), session['quiz_name'], session['user_info']
    
    if is_completed:
        final_text = (f"🎉 انتهى اختبار '**{quiz_name}**'!\n\nنتيجتك النهائية هي: **{score} من {total}**.\n\nلبدء اختبار آخر، أرسل /start.")
        await context.bot.send_message(chat_id, text=final_text, parse_mode=ParseMode.MARKDOWN)

        admin_id = os.environ.get("ADMIN_ID")
        if admin_id and user_info:
            user_name = user_info.get('name'); user_username = f"(@{user_info.get('username')})" if user_info.get('username') else ""
            notification_text = (
                f"📊 **نتيجة اختبار جديدة**\n\n"
                f"**المستخدم:** {user_name} {user_username}\n**ID:** `{user_info.get('id')}`\n"
                f"**الاختبار:** {quiz_name}\n**النتيجة:** {score} من {total}"
            )
            try: await context.bot.send_message(chat_id=admin_id, text=notification_text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e: logger.error(f"Failed to send notification to admin: {e}")

    if chat_id in user_sessions: del user_sessions[chat_id]

# --- Timeout and Cancel Handlers ---

async def handle_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles conversation timeout due to inactivity."""
    chat_id = context.job.chat_id
    await end_quiz(chat_id, context, is_completed=False, custom_message="**⏳ تم إنهاء الاختبار تلقائيًا بسبب عدم التفاعل.**")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allows a user to cancel the quiz."""
    chat_id = update.effective_chat.id
    if chat_id in user_sessions:
        await end_quiz(chat_id, context, is_completed=False, custom_message="✅ **تم إلغاء الاختبار بنجاح.**")
    else:
        await update.message.reply_text("لا يوجد اختبار نشط لإلغائه. أرسل /start لبدء.")
    return ConversationHandler.END

def main() -> None:
    load_quizzes_from_folder()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("TELEGRAM_TOKEN not set.")
    
    application = Application.builder().token(token).build()
    
    quiz_conversation_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_quiz_callback, pattern="^startquiz_")],
        states={
            QUIZ_IN_PROGRESS: [PollAnswerHandler(handle_poll_answer)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=240, # NEW: 4-minute inactivity timeout
    )

    # A handler for when the conversation times out
    application.add_handler(quiz_conversation_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(quiz_info_page_callback, pattern="^infopage_"))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^back_to_menu$"))

    application.run_polling()

if __name__ == "__main__":
    main()

import os
import logging
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, PollAnswerHandler
)
from telegram.error import Forbidden

# --- Configuration ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- In-memory storage ---
quizzes = {}
# Session storage: { chat_id: { quiz_data } }
user_sessions = {}

# --- Helper Functions ---

def load_quizzes_from_folder():
    """Loads all .txt quizzes from the 'quizzes' directory."""
    global quizzes
    quizzes_dir = "quizzes"
    if not os.path.isdir(quizzes_dir):
        os.makedirs(quizzes_dir)
        logger.warning(f"Quizzes directory '{quizzes_dir}' not found. Created it.")
        return

    for filename in os.listdir(quizzes_dir):
        if filename.endswith(".txt"):
            quiz_name = os.path.splitext(filename)[0].replace("_", " ")
            filepath = os.path.join(quizzes_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                
                parsed_questions = parse_quiz_file_line_by_line(file_content)
                if parsed_questions:
                    quizzes[quiz_name] = parsed_questions
                    logger.info(f"Loaded quiz '{quiz_name}' with {len(parsed_questions)} questions.")
            except Exception as e:
                logger.error(f"Failed to load or parse quiz file {filename}: {e}")

def parse_quiz_file_line_by_line(file_content: str) -> list:
    """A robust, line-by-line parser for a single quiz file."""
    questions, current_question = [], None
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
        else:
            if current_question and current_question.get('correct'):
                questions.append(current_question)
            current_question = {"question": line, "correct": None, "incorrect": []}
    if current_question and current_question.get('correct'):
        questions.append(current_question)
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
        await message_object.reply_text("أهلاً بك! لا توجد اختبارات متاحة حاليًا. 😕")
        return

    keyboard = [[InlineKeyboardButton(name, callback_data=f"infopage_{name}")] for name in sorted(quizzes.keys())]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "**أهلاً بك!** 👋\n\nالرجاء اختيار الاختبار الذي تريد البدء به:"
    
    if isinstance(update, Update) and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await message_object.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def quiz_info_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a confirmation page with quiz details before starting."""
    query = update.callback_query
    await query.answer()
    quiz_name = query.data.split('_', 1)[1]
    if quiz_name not in quizzes:
        await query.edit_message_text("عذرًا، هذا الاختبار لم يعد متاحًا.")
        return

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
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the quiz session and sends the first poll."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat_id = query.message.chat_id
    quiz_name = query.data.split('_', 1)[1]
    
    # Initialize session for the user
    user_sessions[chat_id] = {
        'quiz_name': quiz_name,
        'question_index': 0,
        'score': 0,
        'quiz_questions': quizzes[quiz_name],
        'user_info': {'id': user.id, 'name': user.full_name, 'username': user.username}
    }
    
    # NEW: Added reminder on how to cancel the quiz
    await query.edit_message_text(
        f"تمام! لنبدأ اختبار: **{quiz_name}**\n\n"
        f"ℹ️ يمكنك إرسال الأمر /cancel في أي وقت لإلغاء الاختبار.",
        parse_mode=ParseMode.MARKDOWN
    )
    await send_poll_question(chat_id, context)

# --- Poll-based Quiz Logic ---

async def send_poll_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Sends the current question as a quiz poll."""
    session = user_sessions.get(chat_id)
    if not session: return

    q_index = session['question_index']
    questions = session['quiz_questions']
    
    if q_index >= len(questions):
        await end_quiz(chat_id, context)
        return

    q_data = questions[q_index]
    question_text = f"({q_index + 1}/{len(questions)}) {q_data['question']}"
    options = [q_data['correct']] + q_data['incorrect']
    random.shuffle(options)
    correct_option_id = options.index(q_data['correct'])
    
    await context.bot.send_poll(
        chat_id=chat_id,
        question=question_text,
        options=options,
        type='quiz',
        correct_option_id=correct_option_id,
        open_period=45,
        is_anonymous=False
    )

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles a user's answer to a poll."""
    answer = update.poll_answer
    user_id = answer.user.id
    session = user_sessions.get(user_id)
    
    if not session: return

    # Since polls don't close immediately, we can't reliably go to the next question here.
    # We will just record the score. The quiz progresses as polls close.
    # For a smoother experience, we'd need to handle poll closing events, which is more complex.
    # This simplified logic records the score and the user waits for the next poll.
    # A better approach would be to track poll IDs. For now, this is simpler.

    chosen_option = answer.option_ids[0]
    if chosen_option == session['correct_option_id']:
        session['score'] += 1

    session['question_index'] += 1
    await send_poll_question(user_id, context)

async def end_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Ends the quiz and sends results."""
    session = user_sessions.get(chat_id)
    if not session: return

    score, total, quiz_name, user_info = session['score'], len(session['quiz_questions']), session['quiz_name'], session['user_info']
    
    final_text = (
        f"🎉 انتهى اختبار '**{quiz_name}**'!\n\n"
        f"نتيجتك النهائية هي: **{score} من {total}**.\n\n"
        f"لبدء اختبار آخر، أرسل /start."
    )
    await context.bot.send_message(chat_id, text=final_text, parse_mode=ParseMode.MARKDOWN)

    admin_id = os.environ.get("ADMIN_ID")
    if admin_id and user_info:
        user_name = user_info.get('name'); user_username = f"(@{user_info.get('username')})" if user_info.get('username') else ""
        notification_text = (
            f"📊 **نتيجة اختبار جديدة**\n\n"
            f"**المستخدم:** {user_name} {user_username}\n"
            f"**ID:** `{user_info.get('id')}`\n"
            f"**الاختبار:** {quiz_name}\n"
            f"**النتيجة:** {score} من {total}"
        )
        try:
            await context.bot.send_message(chat_id=admin_id, text=notification_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Failed to send notification to admin: {e}")

    if chat_id in user_sessions:
        del user_sessions[chat_id]

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allows a user to cancel the quiz and returns to main menu."""
    chat_id = update.effective_chat.id
    if chat_id in user_sessions:
        del user_sessions[chat_id]
        await update.message.reply_text("✅ **تم إلغاء الاختبار بنجاح.**", parse_mode=ParseMode.MARKDOWN)
        await show_main_menu(update)
    else:
        await update.message.reply_text("لا يوجد اختبار نشط لإلغائه. أرسل /start لبدء.")

def main() -> None:
    load_quizzes_from_folder()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("TELEGRAM_TOKEN not set.")
    
    application = Application.builder().token(token).build()
    
    # Handlers for menu navigation and starting the quiz
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(quiz_info_page_callback, pattern="^infopage_"))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^back_to_menu$"))
    application.add_handler(CallbackQueryHandler(start_quiz_callback, pattern="^startquiz_"))
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    application.add_handler(CommandHandler("cancel", cancel))

    application.run_polling()

if __name__ == "__main__":
    main()

import os
import logging
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, PollAnswerHandler, PollHandler, MessageHandler, filters
)

# --- Configuration ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- In-memory storage ---
quizzes = {}
user_sessions = {}
poll_tracker = {}

# --- Helper Functions ---

def load_quizzes_from_folder():
    """Loads all .txt quizzes from subdirectories inside the 'quizzes' folder."""
    global quizzes
    quizzes_dir = "quizzes"
    if not os.path.isdir(quizzes_dir): os.makedirs(quizzes_dir); return

    for category in os.listdir(quizzes_dir):
        category_path = os.path.join(quizzes_dir, category)
        if os.path.isdir(category_path):
            quizzes[category] = {}
            for filename in os.listdir(category_path):
                if filename.endswith(".txt"):
                    quiz_name = os.path.splitext(filename)[0].replace("_", " ")
                    filepath = os.path.join(category_path, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f: file_content = f.read()
                        parsed_questions = parse_quiz_file_line_by_line(file_content)
                        if parsed_questions:
                            quizzes[category][quiz_name] = parsed_questions
                            logger.info(f"Loaded quiz '{quiz_name}' from category '{category}'")
                    except Exception as e:
                        logger.error(f"Failed to load quiz file {filename}: {e}")

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

def is_admin(update: Update) -> bool:
    """Checks if the user sending the command is the admin."""
    admin_id = os.environ.get("ADMIN_ID")
    return str(update.effective_user.id) == admin_id

# --- Menu and Quiz Logic (Same as before) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id in user_sessions:
        await update.message.reply_text("أنت بالفعل في منتصف اختبار. 🙅‍♂️\nالرجاء إكماله أولاً، أو استخدم الأمر /cancel لإلغائه.")
        return
    await show_main_menu(update, context, is_edit=False)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_edit: bool = True):
    chat_id = update.effective_chat.id
    if not quizzes:
        await context.bot.send_message(chat_id, "أهلاً بك! لا توجد اختبارات متاحة حاليًا. 😕"); return
    keyboard = [[InlineKeyboardButton(cat, callback_data=f"category_{cat}")] for cat in sorted(quizzes.keys())]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "**أهلاً بك!** 👋\n\nالرجاء اختيار قسم الاختبارات:"
    if is_edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await context.bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await context.bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def category_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    category = query.data.split('_', 1)[1]
    if category not in quizzes: await query.edit_message_text("عذرًا، هذا القسم لم يعد متاحًا."); return
    keyboard = [[InlineKeyboardButton(name, callback_data=f"infopage_{category}|{name}")] for name in sorted(quizzes[category].keys())]
    keyboard.append([InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data="back_to_main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"**القسم: {category}**\n\nالرجاء اختيار الاختبار الذي تريد البدء به:"
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def quiz_info_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    category, quiz_name = query.data.split('_', 1)[1].split('|', 1)
    if category not in quizzes or quiz_name not in quizzes[category]:
        await query.edit_message_text("عذرًا، هذا الاختبار لم يعد متاحًا."); return
    num_questions = len(quizzes[category][quiz_name])
    text = (f"**📖 اسم الاختبار:** {quiz_name}\n**🔢 عدد الأسئلة:** {num_questions}\n**⏱️ الوقت لكل سؤال:** 45 ثانية\n\nهل أنت مستعد؟")
    keyboard = [[InlineKeyboardButton("🚀 ابدأ الاختبار", callback_data=f"startquiz_{category}|{quiz_name}")], [InlineKeyboardButton("🔙 عودة لقائمة الاختبارات", callback_data=f"category_{category}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user = query.from_user; chat_id = query.message.chat_id
    category, quiz_name = query.data.split('_', 1)[1].split('|', 1)
    user_sessions[chat_id] = {'quiz_name': quiz_name, 'question_index': 0, 'score': 0, 'quiz_questions': quizzes[category][quiz_name], 'user_info': {'id': user.id, 'name': user.full_name, 'username': user.username}}
    text = f"تمام! لنبدأ اختبار: **{quiz_name}**\n\nلإلغاء الاختبار في أي وقت، أرسل:\n/cancel"
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    await send_poll_question(chat_id, context)

async def send_poll_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    session = user_sessions.get(chat_id)
    if not session: return
    q_index = session['question_index']
    questions = session['quiz_questions']
    if q_index >= len(questions): await end_quiz(chat_id, context, is_completed=True); return
    session['answered_this_poll'] = False
    q_data = questions[q_index]
    question_text = f"({q_index + 1}/{len(questions)}) {q_data['question']}"
    options = [q_data['correct']] + q_data['incorrect']
    random.shuffle(options)
    correct_option_id = options.index(q_data['correct'])
    message = await context.bot.send_poll(chat_id=chat_id, question=question_text, options=options, type='quiz', correct_option_id=correct_option_id, open_period=45, is_anonymous=False)
    poll_tracker[message.poll.id] = chat_id
    session['correct_option_id'] = correct_option_id
    session['current_message_id'] = message.message_id
    job = context.job_queue.run_once(on_timeout, 45, data={'chat_id': chat_id, 'question_index': q_index}, name=f"timer_{chat_id}")
    session['timeout_job'] = job

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer; user_id = answer.user.id
    session = user_sessions.get(user_id)
    if not session or session.get('answered_this_poll'): return
    session['answered_this_poll'] = True
    if 'timeout_job' in session and session['timeout_job']: session['timeout_job'].schedule_removal()
    try: await context.bot.stop_poll(user_id, session['current_message_id'])
    except Exception as e: logger.warning(f"Could not stop poll (fast path): {e}")
    if answer.option_ids[0] == session.get('correct_option_id'): session['score'] += 1
    session['question_index'] += 1
    await send_poll_question(user_id, context)

async def on_timeout(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data; chat_id = job_data['chat_id']; q_index_when_fired = job_data['question_index']
    session = user_sessions.get(chat_id)
    if session and session.get('question_index') == q_index_when_fired and not session.get('answered_this_poll'):
        try: await context.bot.stop_poll(chat_id, session['current_message_id'])
        except Exception as e: logger.warning(f"Could not stop poll on timeout: {e}")
        session['question_index'] += 1
        await send_poll_question(chat_id, context)

async def end_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE, is_completed: bool):
    session = user_sessions.get(chat_id)
    if not session: return
    if 'timeout_job' in session and session['timeout_job']: session['timeout_job'].schedule_removal()
    if is_completed:
        score, total, quiz_name, user_info = session['score'], len(session['quiz_questions']), session['quiz_name'], session['user_info']
        final_text = (f"🎉 انتهى اختبار '**{quiz_name}**'!\n\nنتيجتك النهائية هي: **{score} من {total}**.\n\nلبدء اختبار آخر، أرسل /start.")
        await context.bot.send_message(chat_id, text=final_text, parse_mode=ParseMode.MARKDOWN)
        admin_id = os.environ.get("ADMIN_ID")
        if admin_id and user_info:
            user_name = user_info.get('name'); user_username = f"(@{user_info.get('username')})" if user_info.get('username') else ""
            notification_text = (f"📊 **نتيجة اختبار جديدة**\n\n**المستخدم:** {user_name} {user_username}\n**ID:** `{user_info.get('id')}`\n**الاختبار:** {quiz_name}\n**النتيجة:** {score} من {total}")
            try: await context.bot.send_message(chat_id=admin_id, text=notification_text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e: logger.error(f"Failed to send notification to admin: {e}")
    if chat_id in user_sessions: del user_sessions[chat_id]

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = user_sessions.get(chat_id)
    if session:
        await end_quiz(chat_id, context, is_completed=False) # Will clear session
        user_info = session.get('user_info', {}); quiz_name = session.get('quiz_name', 'غير معروف')
        await update.message.reply_text("✅ **تم إلغاء الاختبار بنجاح.**", parse_mode=ParseMode.MARKDOWN)
        admin_id = os.environ.get("ADMIN_ID")
        if admin_id and user_info:
            user_name = user_info.get('name'); user_username = f"(@{user_info.get('username')})" if user_info.get('username') else ""
            notification_text = (f"⚠️ **تم إلغاء اختبار**\n\n**المستخدم:** {user_name} {user_username}\n**ID:** `{user_info.get('id')}`\n**الاختبار:** {quiz_name}")
            try: await context.bot.send_message(chat_id=admin_id, text=notification_text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e: logger.error(f"Failed to send cancellation notification to admin: {e}")
        await show_main_menu(update, context, is_edit=False)
    else:
        await update.message.reply_text("لا يوجد اختبار نشط لإلغائه. أرسل /start لبدء.")


# --- NEW HANDLERS FOR ADMIN AND GROUP DETECTION ---

async def leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows the admin to make the bot leave a group."""
    if not is_admin(update): return
    if not context.args:
        await update.message.reply_text("الرجاء تحديد ID المجموعة. مثال:\n`/leavegroup -100123456789`")
        return
    try:
        chat_id_to_leave = int(context.args[0])
        await context.bot.leave_chat(chat_id=chat_id_to_leave)
        await update.message.reply_text(f"✅ لقد غادرت المجموعة ذات الـ ID: `{chat_id_to_leave}` بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"لم أتمكن من مغادرة المجموعة. الخطأ: {e}")

async def report_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Temporary handler to report the ID of any group it's in."""
    if update.effective_chat.type in ["group", "supergroup"]:
        admin_id = os.environ.get("ADMIN_ID")
        chat = update.effective_chat
        
        if chat.id not in context.bot_data.get("reported_groups", set()):
            if not admin_id: logger.error("ADMIN_ID not set"); return
            text = (
                f"ℹ️ **معلومات مجموعة**\n\n"
                f"أنا موجود حاليًا في هذه المجموعة:\n"
                f"**اسم المجموعة:** {chat.title}\n"
                f"**ID:** `{chat.id}`\n\n"
                f"يمكنك الآن استخدام هذا الـ ID لإخراجي بالأمر:\n"
                f"`/leavegroup {chat.id}`"
            )
            try:
                await context.bot.send_message(chat_id=admin_id, text=text, parse_mode=ParseMode.MARKDOWN)
                if "reported_groups" not in context.bot_data:
                    context.bot_data["reported_groups"] = set()
                context.bot_data["reported_groups"].add(chat.id)
            except Exception as e:
                logger.error(f"Failed to send group info to admin: {e}")

def main() -> None:
    load_quizzes_from_folder()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("TELEGRAM_TOKEN not set.")
    
    application = Application.builder().token(token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("leavegroup", leave_group)) # Admin command
    
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^back_to_main_menu$"))
    application.add_handler(CallbackQueryHandler(category_menu_callback, pattern="^category_"))
    application.add_handler(CallbackQueryHandler(quiz_info_page_callback, pattern="^infopage_"))
    application.add_handler(CallbackQueryHandler(start_quiz_callback, pattern="^startquiz_"))
    
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    application.add_handler(PollHandler(handle_poll_update))
    
    # NEW: Handler to listen to text messages in groups
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, report_group_id))

    application.run_polling()

if __name__ == "__main__":
    main()

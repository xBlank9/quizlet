import os
import logging
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# --- Configuration ---
# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- State definitions for ConversationHandler ---
GETTING_QUIZ_FILE = range(1)

# --- In-memory storage and JSON file path ---
QUIZZES_FILE = "quizzes.json"
quizzes = {}

# --- Helper Functions ---

def load_quizzes():
    """Loads quizzes from the JSON file into memory."""
    global quizzes
    try:
        with open(QUIZZES_FILE, 'r', encoding='utf-8') as f:
            quizzes = json.load(f)
        logger.info(f"Successfully loaded {len(quizzes)} quizzes from {QUIZZES_FILE}.")
    except FileNotFoundError:
        logger.warning(f"{QUIZZES_FILE} not found. Starting with an empty quiz list.")
        quizzes = {}
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {QUIZZES_FILE}. Starting fresh.")
        quizzes = {}

def save_quizzes():
    """Saves the current quizzes from memory to the JSON file."""
    with open(QUIZZES_FILE, 'w', encoding='utf-8') as f:
        json.dump(quizzes, f, ensure_ascii=False, indent=4)
    logger.info(f"Successfully saved {len(quizzes)} quizzes to {QUIZZES_FILE}.")

def is_admin(update: Update) -> bool:
    """Checks if the user is the admin."""
    admin_id = os.environ.get("ADMIN_ID")
    if not admin_id:
        logger.warning("ADMIN_ID environment variable is not set.")
        return False
    return str(update.effective_user.id) == admin_id

def parse_quiz_file(file_content: str) -> list:
    """Parses the text content into a structured quiz list."""
    questions = []
    raw_questions = file_content.strip().split('\n\n')
    
    for raw_q in raw_questions:
        lines = [line.strip() for line in raw_q.split('\n') if line.strip()]
        if len(lines) < 2: continue
            
        question_text = lines[0]
        correct_answer = None
        incorrect_answers = []
        
        for line in lines[1:]:
            if line.startswith('+'):
                correct_answer = line[1:].strip()
            elif line.startswith('-'):
                incorrect_answers.append(line[1:].strip())
        
        if question_text and correct_answer and incorrect_answers:
            questions.append({
                "question": question_text,
                "correct": correct_answer,
                "incorrect": incorrect_answers
            })
    return questions

# --- User Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows a list of available quizzes to the user."""
    if not quizzes:
        await update.message.reply_text("أهلاً بك! لا توجد اختبارات متاحة حاليًا. 😕")
        return

    keyboard = []
    for quiz_name in quizzes:
        # Callback data format: "startquiz_QUIZNAME"
        button = InlineKeyboardButton(quiz_name, callback_data=f"startquiz_{quiz_name}")
        keyboard.append([button])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("أهلاً بك! 👋\n\nالرجاء اختيار الاختبار الذي تريد البدء به:", reply_markup=reply_markup)

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts a quiz based on the user's button selection."""
    query = update.callback_query
    await query.answer()

    quiz_name = query.data.split('_', 1)[1]
    
    if quiz_name not in quizzes:
        await query.edit_message_text("عذرًا، هذا الاختبار لم يعد متاحًا.")
        return

    context.user_data['quiz_name'] = quiz_name
    context.user_data['question_index'] = 0
    context.user_data['score'] = 0
    context.user_data['quiz_questions'] = quizzes[quiz_name]

    await query.edit_message_text(f"حسنًا! لنبدأ اختبار: **{quiz_name}**")
    await send_question(query.message.chat_id, context)

async def send_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the current question of the ongoing quiz."""
    q_index = context.user_data['question_index']
    questions = context.user_data['quiz_questions']
    
    if q_index < len(questions):
        q_data = questions[q_index]
        options = [q_data['correct']] + q_data['incorrect']
        random.shuffle(options)
        
        context.user_data['correct_answer'] = q_data['correct']
        
        keyboard = [[InlineKeyboardButton(opt, callback_data=f"ans_{opt}")] for opt in options]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(chat_id, text=f"**السؤال {q_index + 1}:**\n\n{q_data['question']}", reply_markup=reply_markup)
    else:
        await end_quiz(chat_id, context)

async def handle_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the user's answer and sends the next question."""
    query = update.callback_query
    await query.answer()

    selected_answer = query.data.split('_', 1)[1]
    correct_answer = context.user_data.get('correct_answer')
    
    result_text = "✅ صحيح!" if selected_answer == correct_answer else f"❌ خطأ. الإجابة الصحيحة هي: {correct_answer}"
    if selected_answer == correct_answer:
        context.user_data['score'] += 1

    await query.edit_message_text(text=f"{query.message.text}\n\nإجابتك: {selected_answer}\n\n{result_text}")

    context.user_data['question_index'] += 1
    
    if context.user_data['question_index'] < len(context.user_data['quiz_questions']):
        await send_question(query.message.chat_id, context)
    else:
        await end_quiz(query.message.chat_id, context)

async def end_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Ends the quiz and shows the final score."""
    score = context.user_data.get('score', 0)
    total = len(context.user_data.get('quiz_questions', []))
    quiz_name = context.user_data.get('quiz_name', '')
    
    await context.bot.send_message(
        chat_id,
        text=f"🎉 انتهى اختبار '{quiz_name}'!\n\nنتيجتك النهائية هي: {score} من {total}.\n\nلبدء اختبار آخر، أرسل /start."
    )
    context.user_data.clear()

# --- Admin Command Handlers ---

async def create_quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the quiz creation conversation (Admin only)."""
    if not is_admin(update):
        await update.message.reply_text("عذرًا، هذا الأمر مخصص للمسؤول فقط.")
        return ConversationHandler.END

    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم للاختبار. مثال:\n`/createquiz lecture_1`")
        return ConversationHandler.END

    quiz_name = " ".join(context.args)
    context.user_data['new_quiz_name'] = quiz_name
    
    await update.message.reply_text(f"حسنًا، سنقوم بإنشاء اختبار باسم '{quiz_name}'.\nالرجاء إرسال ملف .txt الخاص بالأسئلة الآن.")
    return GETTING_QUIZ_FILE

async def receive_quiz_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the quiz file, parses it, and saves it (Admin only)."""
    document = update.message.document
    quiz_name = context.user_data.get('new_quiz_name')
    
    if not document or not document.file_name.endswith('.txt'):
        await update.message.reply_text("خطأ: الرجاء إرسال ملف .txt فقط.")
        return GETTING_QUIZ_FILE

    try:
        file = await document.get_file()
        file_content_bytes = await file.download_as_bytearray()
        file_content = file_content_bytes.decode('utf-8')
        parsed_questions = parse_quiz_file(file_content)
        
        if not parsed_questions:
            await update.message.reply_text("لم أجد أسئلة صالحة في الملف. تم إلغاء العملية.")
            return ConversationHandler.END

        quizzes[quiz_name] = parsed_questions
        save_quizzes()
        await update.message.reply_text(f"✅ تم حفظ اختبار '{quiz_name}' بنجاح ويحتوي على {len(parsed_questions)} سؤال.")
        
    except Exception as e:
        logger.error(f"Error processing quiz file: {e}")
        await update.message.reply_text("حدث خطأ أثناء معالجة الملف.")
    
    context.user_data.clear()
    return ConversationHandler.END

async def delete_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deletes a quiz (Admin only)."""
    if not is_admin(update):
        await update.message.reply_text("عذرًا، هذا الأمر مخصص للمسؤول فقط.")
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم الاختبار الذي تريد حذفه. مثال:\n`/deletequiz lecture_1`")
        return
        
    quiz_name_to_delete = " ".join(context.args)
    
    if quiz_name_to_delete in quizzes:
        del quizzes[quiz_name_to_delete]
        save_quizzes()
        await update.message.reply_text(f"🗑️ تم حذف اختبار '{quiz_name_to_delete}' بنجاح.")
    else:
        await update.message.reply_text(f"لم أجد اختبارًا بهذا الاسم: '{quiz_name_to_delete}'.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current operation."""
    await update.message.reply_text("تم إلغاء العملية.")
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    load_quizzes() # Load quizzes on startup

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("No TELEGRAM_TOKEN environment variable set.")
        
    application = Application.builder().token(token).build()

    # Admin conversation handler for creating quizzes
    create_conv = ConversationHandler(
        entry_points=[CommandHandler("createquiz", create_quiz_start)],
        states={GETTING_QUIZ_FILE: [MessageHandler(filters.Document.TXT, receive_quiz_file)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("deletequiz", delete_quiz))
    application.add_handler(create_conv)
    
    # Handlers for taking the quiz
    application.add_handler(CallbackQueryHandler(start_quiz_callback, pattern="^startquiz_"))
    application.add_handler(CallbackQueryHandler(handle_answer_callback, pattern="^ans_"))
    
    application.run_polling()

if __name__ == "__main__":
    main()

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, ContextTypes, filters
import random

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- State definitions for ConversationHandler ---
GETTING_QUIZ, QUIZ_IN_PROGRESS = range(2)

# --- In-memory storage for quizzes and scores ---
# Note: This data will be lost if the bot restarts.
quizzes = {}
user_scores = {}

# --- Bot Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    user = update.effective_user
    await update.message.reply_html(
        f"أهلاً بك يا {user.mention_html()}!\n\n"
        f"أنا بوت الكويزات الخاص بك.\n"
        f"استخدم الأمر /createquiz لإنشاء اختبار جديد عن طريق إرسال ملف .txt.\n"
        f"استخدم الأمر /startquiz لبدء اختبار قمت بإنشائه في هذه المحادثة.",
    )

async def create_quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the quiz creation process."""
    await update.message.reply_text("الرجاء إرسال ملف الكويز الآن. يجب أن يكون بصيغة .txt وبالتنسيق المطلوب (+ للإجابة الصحيحة, - للخاطئة).")
    return GETTING_QUIZ

def parse_quiz_file(file_content: str) -> list:
    """Parses the text content into a structured quiz list."""
    questions = []
    # Split by double newline to separate questions
    raw_questions = file_content.strip().split('\n\n')
    
    for raw_q in raw_questions:
        lines = [line.strip() for line in raw_q.split('\n') if line.strip()]
        if len(lines) < 2:
            continue
            
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

async def receive_quiz_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives and processes the .txt file."""
    chat_id = update.effective_chat.id
    document = update.message.document
    
    if not document or not document.file_name.endswith('.txt'):
        await update.message.reply_text("خطأ: الرجاء إرسال ملف بصيغة .txt فقط.")
        return GETTING_QUIZ

    try:
        file = await document.get_file()
        file_content_bytes = await file.download_as_bytearray()
        file_content = file_content_bytes.decode('utf-8')
        
        parsed_questions = parse_quiz_file(file_content)
        
        if not parsed_questions:
            await update.message.reply_text("لم أتمكن من العثور على أسئلة صالحة في الملف. تأكد من التنسيق:\n\nالسؤال؟\n+الإجابة الصحيحة\n-إجابة خاطئة\n-إجابة خاطئة أخرى")
            return ConversationHandler.END

        quizzes[chat_id] = parsed_questions
        await update.message.reply_text(
            f"تم إنشاء الاختبار بنجاح! يحتوي على {len(parsed_questions)} سؤال.\n"
            f"يمكنك الآن بدء الاختبار باستخدام الأمر /startquiz."
        )
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        await update.message.reply_text("حدث خطأ أثناء معالجة الملف. الرجاء المحاولة مرة أخرى.")
        return ConversationHandler.END

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts a quiz if one exists for the chat."""
    chat_id = update.effective_chat.id
    if chat_id not in quizzes:
        await update.message.reply_text("لم يتم إنشاء أي اختبار في هذه المحادثة بعد. استخدم /createquiz أولاً.")
        return ConversationHandler.END

    context.user_data['question_index'] = 0
    context.user_data['score'] = 0
    context.user_data['quiz_questions'] = quizzes[chat_id]
    
    await send_question(update.effective_chat.id, context)
    return QUIZ_IN_PROGRESS

async def send_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the current question to the user."""
    question_index = context.user_data['question_index']
    questions = context.user_data['quiz_questions']
    
    if question_index < len(questions):
        question_data = questions[question_index]
        question_text = question_data['question']
        
        options = [question_data['correct']] + question_data['incorrect']
        random.shuffle(options)
        
        context.user_data['correct_answer'] = question_data['correct']
        
        keyboard = [
            [InlineKeyboardButton(option, callback_data=option)] for option in options
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(chat_id, text=f"**السؤال {question_index + 1}:**\n\n{question_text}", reply_markup=reply_markup)
    else:
        # This case should be handled by the answer handler, but as a fallback.
        await end_quiz(chat_id, context)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's answer from the inline keyboard."""
    query = update.callback_query
    await query.answer()

    selected_answer = query.data
    correct_answer = context.user_data.get('correct_answer')
    
    if selected_answer == correct_answer:
        context.user_data['score'] += 1
        await query.edit_message_text(text=f"{query.message.text}\n\nإجابتك: {selected_answer}\n\n✅ صحيح!")
    else:
        await query.edit_message_text(text=f"{query.message.text}\n\nإجابتك: {selected_answer}\n\n❌ خطأ. الإجابة الصحيحة هي: {correct_answer}")

    context.user_data['question_index'] += 1
    
    # Check if quiz is over
    if context.user_data['question_index'] < len(context.user_data['quiz_questions']):
        await send_question(query.message.chat_id, context)
        return QUIZ_IN_PROGRESS
    else:
        await end_quiz(query.message.chat_id, context)
        return ConversationHandler.END

async def end_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Ends the quiz and shows the final score."""
    score = context.user_data.get('score', 0)
    total_questions = len(context.user_data.get('quiz_questions', []))
    await context.bot.send_message(chat_id, text=f"🎉 انتهى الاختبار!\n\nنتيجتك النهائية هي: {score} من {total_questions}.\n\nلإنشاء اختبار جديد، استخدم /createquiz.")
    
    # Clean up user data
    context.user_data.clear()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("No TELEGRAM_TOKEN environment variable set.")
        
    application = Application.builder().token(token).build()

    # Conversation handler for creating a quiz
    create_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("createquiz", create_quiz_start)],
        states={
            GETTING_QUIZ: [MessageHandler(filters.Document.TXT, receive_quiz_file)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Conversation handler for taking a quiz
    take_quiz_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("startquiz", start_quiz)],
        states={
            QUIZ_IN_PROGRESS: [CallbackQueryHandler(handle_answer)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(create_conv_handler)
    application.add_handler(take_quiz_conv_handler)
    
    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == "__main__":
    main()

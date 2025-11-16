import os
import logging
import json
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    PicklePersistence,  
)
from quiz_logic import calculate_result

# --- Configuration and Data Loading ---

def load_quiz_data():
    DATA_PATH = os.path.join(os.path.dirname(__file__), 'script.json')
    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Basic schema validation
            required_keys = {'questions', 'total_questions', 'interpretations', 'type_names'}
            if not required_keys.issubset(data.keys()):
                missing = required_keys - set(data.keys())
                logging.error("script.json missing keys: %s", missing)
                return None
            if not isinstance(data['questions'], list):
                logging.error("script.json: 'questions' must be a list")
                return None
            return data
    except FileNotFoundError:
        logging.error("script.json not found.")
        return None

QUIZ_DATA = load_quiz_data()
if not QUIZ_DATA:
    exit(1)

questions = QUIZ_DATA['questions']
TOTAL_QUESTIONS = QUIZ_DATA['total_questions']

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Conversation States ---
(QUIZ_IN_PROGRESS) = range(1)

# --- Error Handling Setup ---
ADMIN_CHAT = os.getenv('ADMIN_CHAT_ID')

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs the error and sends a notification to the admin chat."""
    logger.exception("Exception in handler: %s", context.error)
    try:
        if ADMIN_CHAT and isinstance(context.application, Application):
            # Attempt to send a message to the admin
            await context.application.bot.send_message(
                chat_id=int(ADMIN_CHAT),
                text=f"Bot error: {context.error}"
            )
    except Exception:
        logger.exception("Failed to send error message to admin")

# --- Helper Function ---

def get_score_type_for_key(q_num, answer_key):
    """Finds the score_type (M, S, P, C) for a given answer key (A, B, C, D)"""
    question_data = questions[q_num]
    for option in question_data['options']:
        if option['key'] == answer_key:
            return option['score_type']
    return None

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Starts the quiz. Clears old data, sends the welcome message,
    and asks the first question.
    """
    # Initialize session data for the user
    context.user_data['question_num'] = 0
    context.user_data['scores'] = {"M": 0, "S": 0, "P": 0, "C": 0}
    
    # Send the updated welcome message
    welcome_message = (
        "Добро пожаловать в диагностическую игру: *Какой ты экономический тип?*\n\n"
        "Ответьте на 16 вопросов. Выбирайте честно, *первый вариант, который пришёл в голову*. "
        "По итогам узнаете свой экономический тип."
    )
    
    # Use reply_text for the initial command response
    if update.message:
        await update.message.reply_text(welcome_message, parse_mode="Markdown")
    # If called from an existing message (e.g., via a command in QUIZ_IN_PROGRESS), send a new one
    elif update.callback_query:
        await update.callback_query.message.reply_text(welcome_message, parse_mode="Markdown")
    
    return await ask_question(update, context)


async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends the current question with full options text and Reply Keyboard buttons."""
    q_num = context.user_data.get('question_num')
    if q_num is None or q_num >= TOTAL_QUESTIONS:
        return await show_result(update, context)

    question_data = questions[q_num]
    
    # --- 1. Construct the Full Message Text ---
    options_text = []
    keyboard_buttons = []
    
    for option in question_data["options"]:
        # Add full option text to the message body
        options_text.append(f"*{option['key']}*. {option['text']}")
        # Add only the key (A, B, C, D) to the Reply Keyboard for visibility
        keyboard_buttons.append(KeyboardButton(option['key'])) 

    # We send the question text and the options in the message body
    message_text = (
        f"Вопрос {q_num + 1} из {TOTAL_QUESTIONS}\n\n"
        f"*{question_data['text']}*\n\n"
        f"{' \n'.join(options_text)}"
    )
    
    # --- 2. Create the Reply Keyboard ---
    keyboard = [keyboard_buttons] 
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=False, resize_keyboard=True)
    
    # Send a new message
    target_message = update.message if update.message else update.callback_query.message
    await target_message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    return QUIZ_IN_PROGRESS


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles a user's answer (text input from the Reply Keyboard).
    Records the score, and asks the next question or shows the result.
    """
    answer_key = update.message.text.upper().strip() 
    
    q_num = context.user_data.get('question_num')
    if q_num is None:
        await update.message.reply_text("Сессия потеряна. Введите /start, чтобы начать заново.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
        
    valid_keys = [option['key'] for option in questions[q_num]['options']]
    
    # --- Input Validation (Sanitize / Validate callback_data) ---
    if answer_key not in valid_keys:
        await update.message.reply_text(
            f"❌ Неверный ответ. Пожалуйста, выберите одну из букв: {', '.join(valid_keys)}."
        )
        return QUIZ_IN_PROGRESS 

    scores = context.user_data['scores']
    
    # Find the profile type and update score
    profile_type = get_score_type_for_key(q_num, answer_key)
    if profile_type:
        scores[profile_type] += 1
    
    # Move to the next question
    context.user_data['question_num'] += 1
    
    # Check if quiz is finished
    if context.user_data['question_num'] < TOTAL_QUESTIONS:
        return await ask_question(update, context)
    else:
        return await show_result(update, context)


async def show_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Calculates and displays the final result, and removes the keyboard."""
    scores = context.user_data['scores']
    
    title, interpretation = calculate_result(scores)
    
    result_text = (
        f"--- *{title}* ---\n\n"
        f"{interpretation}\n\n"
        f"Ваши итоговые баллы: M={scores['M']}, S={scores['S']}, P={scores['P']}, C={scores['C']}\n\n"
        "Чтобы пройти тест снова, введите /start"
    )
    
    # Remove the custom keyboard and send the final result
    if update.message:
        await update.message.reply_text(
            result_text,
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
    else:
         await update.callback_query.message.reply_text(
            result_text,
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        
    context.user_data.clear()
    
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the quiz and clear session data."""
    await update.message.reply_text(
        "Тест отменён. Введите /start, чтобы начать заново.", 
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END


def main() -> None:
    """Run the bot."""
    load_dotenv()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        logger.error("TELEGRAM_TOKEN not found! Please set it in .env file.")
        return

    # Use PicklePersistence to save state
    persistence = PicklePersistence(filepath='bot_data.pickle')
    application = Application.builder().token(token).persistence(persistence).build()

    # Add error handler
    application.add_error_handler(error_handler)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            QUIZ_IN_PROGRESS: [
                # New: Allows user to restart the quiz by typing /start
                CommandHandler("start", start), 
                # MessageHandler handles the text input from the Reply Keyboard
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer) 
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    
    logger.info("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
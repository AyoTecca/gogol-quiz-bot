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


def load_quiz_data():
    DATA_PATH = os.path.join(os.path.dirname(__file__), 'script.json')
    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            required_keys = {'questions', 'total_questions', 'interpretations', 'type_names'}
            if not required_keys.issubset(data.keys()):
                logging.error("script.json missing keys: %s", required_keys - set(data.keys()))
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

(QUIZ_IN_PROGRESS) = range(1)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs the error and sends a notification to the admin chat."""
    logger.exception("Exception in handler: %s", context.error)
    try:
        admin_chat = os.getenv('ADMIN_CHAT_ID')
        if admin_chat and isinstance(context.application, Application):
            await context.application.bot.send_message(
                chat_id=int(admin_chat),
                text=f"Bot error: {context.error}"
            )
    except Exception:
        logger.exception("Failed to send error message to admin")


def get_score_type_for_key(q_num, answer_key):
    """Finds the score_type (M, S, P, C) for a given answer key (A, B, C, D)"""
    question_data = questions[q_num]
    for option in question_data['options']:
        if option['key'] == answer_key:
            return option['score_type']
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['question_num'] = 0
    context.user_data['scores'] = {"M": 0, "S": 0, "P": 0, "C": 0}

    welcome_message = (
        "Добро пожаловать в диагностическую игру: *Какой ты экономический тип?*\n\n"
        "Ответьте на 16 вопросов. Выбирайте честно, *первый вариант, который пришёл в голову*. "
        "По итогам узнаете свой экономический тип."
    )

    if not update.message:
        return ConversationHandler.END

    await update.message.reply_text(welcome_message, parse_mode="Markdown")
    return await ask_question(update, context)


async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends the current question with full options text and Reply Keyboard buttons."""
    q_num = context.user_data.get('question_num')
    if q_num is None or q_num >= TOTAL_QUESTIONS:
        return await show_result(update, context)

    question_data = questions[q_num]

    options_text = []
    keyboard_buttons = []

    for option in question_data["options"]:
        options_text.append(f"*{option['key']}*. {option['text']}")
        keyboard_buttons.append(KeyboardButton(option['key']))

    message_text = (
        f"Вопрос {q_num + 1} из {TOTAL_QUESTIONS}\n\n"
        f"*{question_data['text']}*\n\n"
        f"{' \n'.join(options_text)}\n\n"
        "💡 *Важно:* Для ответа, пожалуйста, используйте только кнопки с буквами."
    )

    keyboard = [keyboard_buttons]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")

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
    
    if answer_key not in valid_keys:
        await update.message.reply_text(
            f"❌ Неверный ответ. Пожалуйста, выберите одну из букв: {', '.join(valid_keys)}."
        )
        return QUIZ_IN_PROGRESS 

    scores = context.user_data['scores']
    
    profile_type = get_score_type_for_key(q_num, answer_key)
    if profile_type:
        scores[profile_type] += 1
    
    context.user_data['question_num'] += 1
    
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
    
    await update.message.reply_text(
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

    persistence = PicklePersistence(filepath='bot_data.pickle')
    application = Application.builder().token(token).persistence(persistence).build()

    application.add_error_handler(error_handler)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            QUIZ_IN_PROGRESS: [
                CommandHandler("start", start), 
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
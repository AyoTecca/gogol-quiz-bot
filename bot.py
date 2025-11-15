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
)
from quiz_logic import calculate_result

def load_quiz_data():
    DATA_PATH = os.path.join(os.path.dirname(__file__), 'script.json')
    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
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

(QUIZ_IN_PROGRESS,) = range(1)

def get_score_type_for_key(q_num, answer_key):
    """Finds the score_type (M, S, P, C) for a given answer key (A, B, C, D)."""
    question_data = questions[q_num]
    for option in question_data['options']:
        if option['key'] == answer_key:
            return option['score_type']
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the quiz and ask the first question."""
    context.user_data['question_num'] = 0
    context.user_data['scores'] = {"M": 0, "S": 0, "P": 0, "C": 0}

    await update.message.reply_text(
        "Добро пожаловать в мини-игру «Какой ты экономический тип»!\n"
        "Вам будет задано 16 вопросов. Начнём."
    )

    return await ask_question(update, context)


async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send the current question with options and Reply Keyboard buttons."""
    q_num = context.user_data['question_num']

    if q_num >= TOTAL_QUESTIONS:
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
        f"{' \n'.join(options_text)}"
    )

    keyboard = [keyboard_buttons]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=False, resize_keyboard=True)

    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")

    return QUIZ_IN_PROGRESS


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle a user's answer (text), update score, and proceed."""
    answer_key = update.message.text.upper().strip()

    valid_keys = [option['key'] for option in questions[context.user_data['question_num']]['options']]

    if answer_key not in valid_keys:
        await update.message.reply_text(
            f"❌ Неверный ответ. Пожалуйста, выберите одну из букв: {', '.join(valid_keys)}."
        )
        return QUIZ_IN_PROGRESS

    q_num = context.user_data['question_num']
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
    """Calculate and display the final result and remove keyboard."""
    scores = context.user_data['scores']

    title, interpretation = calculate_result(scores)

    result_text = (
        f"--- *{title}* ---\n\n"
        f"{interpretation}\n\n"
        f"Ваши итоговые баллы: M={scores['M']}, S={scores['S']}, P={scores['P']}, C={scores['C']}\n\n"
        "Чтобы пройти тест снова, введите /start"
    )

    await update.message.reply_text(result_text, reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")

    context.user_data.clear()

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the quiz and clear session data."""
    await update.message.reply_text("Тест отменён. Введите /start, чтобы начать заново.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


def main() -> None:
    load_dotenv()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        logger.error("TELEGRAM_TOKEN not found! Please set it in .env file.")
        return

    application = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            QUIZ_IN_PROGRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    logger.info("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
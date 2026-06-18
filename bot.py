import os
import time
import httpx
import anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from knowledge import USDKG_KNOWLEDGE

# Клиент Anthropic
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

GAMMA_API_KEY = os.environ.get("GAMMA_API_KEY")
GAMMA_BASE_URL = "https://public-api.gamma.app/v1.0"


def create_gamma_presentation(text_content: str, num_cards: int = 10) -> dict:
    """Отправляет текст в Gamma API и создаёт презентацию."""
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": GAMMA_API_KEY,
    }
    payload = {
        "inputText": text_content,
        "textMode": "preserve",  # сохраняем наш текст как есть, не перегенерируем
        "format": "presentation",
        "numCards": num_cards,
        "exportAs": "pdf",
    }
    resp = httpx.post(f"{GAMMA_BASE_URL}/generations", headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def poll_gamma_result(generation_id: str, max_wait: int = 90) -> dict:
    """Опрашивает статус генерации каждые 5 секунд до готовности."""
    headers = {"X-API-KEY": GAMMA_API_KEY}
    elapsed = 0
    while elapsed < max_wait:
        resp = httpx.get(f"{GAMMA_BASE_URL}/generations/{generation_id}", headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "completed":
            return data
        if data.get("status") == "failed":
            raise Exception("Gamma generation failed")
        time.sleep(5)
        elapsed += 5
    raise TimeoutError("Gamma generation timed out")

# Системный промпт — мозг агента
SYSTEM_PROMPT = """Ты — AI агент-аналитик USDKG. Ниже — ПОЛНАЯ база знаний
проекта: вся стратегия, архитектура, цифры, риски, дорожная карта,
история документов. Это не выжимка — используй её как первичный
источник, отвечай с той же глубиной и конкретными цифрами, какие в ней
содержатся. Не упрощай и не обобщай там, где в базе есть точные данные.

=== БАЗА ЗНАНИЙ USDKG ===
{knowledge}
=== КОНЕЦ БАЗЫ ЗНАНИЙ ===

ПРАВИЛА ОТВЕТА:
1. Если вопрос касается цифр, механик, рисков, дорожной карты — бери
   точные данные из базы знаний выше, не придумывай и не округляй сильнее
   чем там указано.
2. Если просят слайд или раздел презентации — создавай контент в стиле
   Gamma App, структурированный Markdown, и используй реальные цифры и
   формулировки из базы знаний, а не общие фразы.
3. Если просят полную презентацию — генерируй слайды последовательно,
   покрывая реальную структуру (закат доллара → что такое USDKG → Gold
   Dividend → эмиссия → дистрибьюция → use cases → БРИКС+ → финансовая
   модель → риски → дорожная карта), а не урезанную версию.
4. Если просят перевод — переводи точно, сохраняя структуру и цифры.
5. Если вопрос общий (про деньги, доллар, золото) — отвечай развёрнуто,
   как аналитик, используя часть 14 базы знаний и при необходимости
   связывая с USDKG.
6. Отвечай на русском, если не просят иначе.
7. Не сокращай ответ искусственно ради краткости, если вопрос требует
   глубины — пользователь явно ожидает обширную, подробную информацию,
   а не конспект.

ФОРМАТ ДЛЯ СЛАЙДОВ (когда просят конкретный слайд):
---
# [ЗАГОЛОВОК СЛАЙДА]

## [ПОДЗАГОЛОВОК]

[КЛЮЧЕВАЯ ЦИФРА из базы знаний]

- Буллет с конкретными данными
- Буллет с конкретными данными
- Буллет с конкретными данными

[GAMMA HINT: тип слайда — Big number / Comparison / Timeline / Process flow]
---
""".format(knowledge=USDKG_KNOWLEDGE)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🪙 *USDKG Presentation Agent*\n\n"
        "Я создаю контент для презентаций USDKG в твоём стиле — и могу сразу собрать готовую презентацию в Gamma.\n\n"
        "*Что я умею:*\n"
        "• Создать слайд или раздел по теме\n"
        "• /gamma_full — сразу собрать полную презентацию в Gamma (ссылка + PDF)\n"
        "• /gamma_this — превратить последний ответ в презентацию Gamma\n"
        "• Перевести контент на английский/китайский\n\n"
        "*Примеры запросов:*\n"
        "— Сделай слайд про Gold Dividend\n"
        "— Напиши раздел про архитектуру дистрибьюции\n"
        "— Создай слайд сравнения USDKG vs USDT\n\n"
        "Пиши что нужно 👇",
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Команды:*\n"
        "/start — начало работы\n"
        "/help — эта справка\n"
        "/full — полная презентация USDKG\n"
        "/investor — питч для инвестора\n"
        "/exchanger — питч для обменников\n\n"
        "*Или просто напиши запрос на русском*",
        parse_mode="Markdown"
    )


async def full_presentation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Генерирую полную презентацию... (~1 минута)")
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Создай полную структуру презентации USDKG для инвестора. 15 слайдов. Каждый слайд с заголовком, ключевой цифрой и 3-4 буллетами. Формат Markdown готовый для вставки в Gamma App."
        }]
    )
    
    text = response.content[0].text
    # Разбиваем на части если длинный
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await update.message.reply_text(part, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


async def investor_pitch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Генерирую питч для инвестора...")
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user", 
            "content": "Создай короткий питч для инвестора — 8 слайдов. Фокус на финансовой модели, Gold Dividend, плане эмиссии $10B к 2027. Формат Markdown для Gamma."
        }]
    )
    
    await update.message.reply_text(response.content[0].text, parse_mode="Markdown")


async def exchanger_pitch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Генерирую питч для обменников...")
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Создай питч для обменников — почему им выгодно работать с USDKG вместо USDT. 5 слайдов. Фокус на комиссиях, Gold Dividend на резервы, Guardian Service. Формат Markdown для Gamma."
        }]
    )
    
    await update.message.reply_text(response.content[0].text, parse_mode="Markdown")


async def gamma_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерирует полную презентацию USDKG напрямую в Gamma и присылает ссылку."""
    await update.message.reply_text("⏳ Генерирую контент... (~30 сек)")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Создай полную структуру презентации USDKG для инвестора. 15 слайдов. Каждый слайд с заголовком, ключевой цифрой и 3-4 буллетами. Формат Markdown."
        }]
    )
    text_content = response.content[0].text

    await update.message.reply_text("🎨 Создаю презентацию в Gamma...")

    try:
        gen = create_gamma_presentation(text_content, num_cards=15)
        generation_id = gen.get("generationId")
        result = poll_gamma_result(generation_id)
        gamma_url = result.get("gammaUrl")
        export_url = result.get("exportUrl")

        msg = f"✅ Презентация готова!\n\n🔗 Открыть в Gamma:\n{gamma_url}"
        if export_url:
            msg += f"\n\n📄 Скачать PDF:\n{export_url}"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка Gamma API: {e}\n\nВот текст — вставь вручную в gamma.app:")
        await update.message.reply_text(text_content[:4000])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    await update.message.reply_text("⏳ Генерирую...")
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": user_text
        }]
    )
    
    text = response.content[0].text

    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await update.message.reply_text(part, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

    # Предлагаем сразу сделать презентацию в Gamma
    await update.message.reply_text(
        "💡 Хочешь, чтобы я сразу создал это как готовую презентацию в Gamma? "
        "Напиши /gamma_this и я пришлю ссылку.",
    )
    context.user_data["last_content"] = text


async def gamma_this(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Превращает последний сгенерированный текст в готовую презентацию Gamma."""
    text_content = context.user_data.get("last_content")
    if not text_content:
        await update.message.reply_text("Сначала отправь запрос на контент, потом используй эту команду.")
        return

    await update.message.reply_text("🎨 Создаю презентацию в Gamma...")
    try:
        gen = create_gamma_presentation(text_content, num_cards=8)
        generation_id = gen.get("generationId")
        result = poll_gamma_result(generation_id)
        gamma_url = result.get("gammaUrl")
        export_url = result.get("exportUrl")

        msg = f"✅ Готово!\n\n🔗 {gamma_url}"
        if export_url:
            msg += f"\n\n📄 PDF: {export_url}"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка Gamma API: {e}")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан")
    
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("full", full_presentation))
    app.add_handler(CommandHandler("investor", investor_pitch))
    app.add_handler(CommandHandler("exchanger", exchanger_pitch))
    app.add_handler(CommandHandler("gamma_full", gamma_full))
    app.add_handler(CommandHandler("gamma_this", gamma_this))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()

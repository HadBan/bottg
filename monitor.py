import os
import asyncio
import sqlite3
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Переменные из окружения BotHost
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PRICE_DROP_PERCENT = 15  # Оповещать, если цена упала на 15% или больше

# ID категорий Wildberries:
# 5130 — Ноутбуки и компьютеры (включая ноуты)
# 5133 — Планшеты
CATEGORIES = [5130, 5133]

def init_db():
    """Создает базу данных для истории цен категорий."""
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            article INTEGER PRIMARY KEY,
            name TEXT,
            last_price REAL
        )
    """)
    conn.commit()
    conn.close()

async def get_category_products(subject_id):
    """Парсит топ товаров из конкретной категории WB по её subject ID."""
    # Стабильный API эндпоинт каталога с фильтром по категории (subject)
    url = f"https://wb.ru{subject_id}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=12) as response:
                if response.status == 200:
                    data = await response.json()
                    products = data.get("data", {}).get("products", [])
                    print(f"📦 Категория {subject_id}: Успешно загружено {len(products)} товаров.")
                    return products
    except Exception as e:
        print(f"Ошибка при парсинге категории {subject_id}: {e}")
    return []

async def check_prices(application: Application):
    """Фоновый цикл: собирает категории и ищет падение цен."""
    while True:
        print("🔄 Начало глобальной проверки категорий ноутбуков и планшетов...")
        
        all_products = []
        for cat_id in CATEGORIES:
            products = await get_category_products(cat_id)
            all_products.extend(products)
            await asyncio.sleep(2) # Небольшая пауза между категориями, чтобы не спамить
            
        if not all_products:
            print("📭 Не удалось получить товары ни из одной категории.")
        else:
            conn = sqlite3.connect("prices.db")
            cursor = conn.cursor()
            alerts_sent = 0

            for prod in all_products:
                article = prod.get("id")
                name = f"{prod.get('brand', '')} {prod.get('name', '')}".strip()
                # Получаем цену со всеми скидками в рублях
                current_price = prod.get("sizes", [{}]).get("price", {}).get("salePriceU", 0) / 100
                
                if current_price == 0:
                    continue

                cursor.execute("SELECT name, last_price FROM products WHERE article = ?", (article,))
                row = cursor.fetchone()

                if row is None:
                    # Если товар видим впервые — просто сохраняем его стартовую цену
                    cursor.execute("INSERT INTO products (article, name, last_price) VALUES (?, ?, ?)", 
                                   (article, name, current_price))
                else:
                    old_name, last_price = row
                    if current_price < last_price:
                        drop_percent = ((last_price - current_price) / last_price) * 100
                        
                        if drop_percent >= PRICE_DROP_PERCENT:
                            print(f"🔥 НАЙДЕНА СКИДКА: {name} (-{drop_percent:.1f}%)")
                            message = (
                                f"🚨 **ЦЕНА УПАЛА В КАТАЛОГЕ!** 🚨\n\n"
                                f"📦 **Товар:** {name}\n"
                                f"🆔 **Артикул:** `{article}`\n"
                                f"📉 **Старая цена:** {last_price} руб.\n"
                                f"🔥 **Новая цена:** {current_price} руб. (-{drop_percent:.1f}%)\n\n"
                                f"🔗 [Открыть на Wildberries](https://wildberries.ru{article}/detail.aspx)"
                            )
                            try:
                                await application.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
                                alerts_sent += 1
                                await asyncio.sleep(0.5) # Защита от флуда в телеграм
                            except Exception as te:
                                print(f"⚠️ Ошибка отправки алерта: {te}")

                    # Обновляем цену до актуальной для следующего сравнения
                    cursor.execute("UPDATE products SET last_price = ? WHERE article = ?", (current_price, article))

            conn.commit()
            conn.close()
            print(f"✅ База данных обновлена. Отправлено алертов за этот круг: {alerts_sent}")
            
        print("💤 Мониторинг засыпает на 5 минут...")
        await asyncio.sleep(300)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на команду /start."""
    user_name = update.effective_user.first_name
    reply_text = (
        f"Привет, {user_name}! 👋\n\n"
        f"🤖 Я переключился в автоматический режим!\n"
        f"🔍 Теперь я без остановки мониторю разделы **Ноутбуков** и **Планшетов** на WB.\n"
        f"📉 Как только цена на какой-то из них упадет сильнее чем на {PRICE_DROP_PERCENT}%, админ сразу получит уведомление."
    )
    await update.message.reply_text(text=reply_text)

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Ошибка: Переменные окружения TELEGRAM_TOKEN или CHAT_ID отсутствуют!")
        return

    init_db()

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))

    loop = asyncio.get_event_loop()
    loop.create_task(check_prices(application))

    print("🚀 Бот-каталогизатор успешно запущен на хостинге...")
    application.run_polling()

if __name__ == "__main__":
    main()

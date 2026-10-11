import os
import asyncio
import sqlite3
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Загружаем переменные из окружения хостинга
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PRICE_DROP_PERCENT = 15 

# Твои артикулы электроники для теста
TRACKED_ARTICLES = [214328456, 154673412, 180900123]

def init_db():
    """Создает базу данных, если её нет."""
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

async def get_wb_data(articles):
    """Асинхронное получение данных с WB."""
    id_list = ";".join(map(str, articles))
    url = f"https://wb.ru{id_list}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("data", {}).get("products", [])
    except Exception as e:
        print(f"Ошибка при запросе к WB: {e}")
    return []

async def check_prices(application: Application):
    """Циклическая асинхронная проверка цен."""
    while True:
        print("🔄 Проверяю цены на Wildberries...")
        products = await get_wb_data(TRACKED_ARTICLES)
        
        if not products:
            print("📭 Не удалось получить данные о товарах.")
        else:
            conn = sqlite3.connect("prices.db")
            cursor = conn.cursor()

            for prod in products:
                article = prod.get("id")
                name = prod.get("name")
                current_price = prod.get("sizes", [{}])[0].get("price", {}).get("salePriceU", 0) / 100
                
                if current_price == 0:
                    continue

                cursor.execute("SELECT name, last_price FROM products WHERE article = ?", (article,))
                row = cursor.fetchone()

                if row is None:
                    cursor.execute("INSERT INTO products (article, name, last_price) VALUES (?, ?, ?)", 
                                   (article, name, current_price))
                    print(f"➕ Добавлен товар: {name} — {current_price} руб.")
                else:
                    old_name, last_price = row
                    if current_price < last_price:
                        drop_percent = ((last_price - current_price) / last_price) * 100
                        print(f"📉 Снижение на {name}: {last_price} -> {current_price} (-{drop_percent:.1f}%)")
                        
                        if drop_percent >= PRICE_DROP_PERCENT:
                            message = (
                                f"🚨 **ЦЕНА УПАЛА!** 🚨\n\n"
                                f"📦 **Товар:** {name}\n"
                                f"🆔 **Артикул:** `{article}`\n"
                                f"📉 **Старая цена:** {last_price} руб.\n"
                                f"🔥 **Новая цена:** {current_price} руб. (-{drop_percent:.1f}%)\n\n"
                                f"🔗 [Открыть на Wildberries](https://wildberries.ru{article}/detail.aspx)"
                            )
                            try:
                                await application.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
                            except Exception as te:
                                print(f"⚠️ Ошибка отправки уведомления: {te}")

                    cursor.execute("UPDATE products SET last_price = ? WHERE article = ?", (current_price, article))

            conn.commit()
            conn.close()
            
        print("💤 Проверка завершена. Жду 5 минут...")
        await asyncio.sleep(300)  # Асинхронный сон, не блокирующий обработку команд

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user_name = update.effective_user.first_name
    reply_text = (
        f"Привет, {user_name}! 👋\n\n"
        f"🤖 Я — приватный бот-монитор цен Wildberries.\n"
        f"⚙️ Работаю в фоновом режиме: сканирую технику каждые 5 минут и присылаю алерты о жестких скидках администратору."
    )
    await update.message.reply_text(text=reply_text)

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Ошибка: Переменные TELEGRAM_TOKEN или CHAT_ID не найдены!")
        return

    init_db()

    # Создаем приложение телеграм-бота
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Регистрируем команду /start
    application.add_handler(CommandHandler("start", start_command))

    # Запускаем фоновую задачу парсинга WB внутри общего цикла событий
    loop = asyncio.get_event_loop()
    loop.create_task(check_prices(application))

    # Запускаем самого бота (он будет слушать команды)
    print("🚀 Бот успешно запущен и слушает команды...")
    application.run_polling()

if __name__ == "__main__":
    main()

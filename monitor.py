import os
import asyncio
import sqlite3
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- КОНФИГ ----------
TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN")
    or os.getenv("BOT_TOKEN")
    or os.getenv("TELEGRAM_BOT_TOKEN")
)
CHAT_ID = os.getenv("CHAT_ID")
PRICE_DROP_PERCENT = 15

# База в /app/data — переживает пересборку
DB_PATH = os.getenv("DB_PATH", "/app/data/prices.db")

# Поисковые запросы вместо subject ID
SEARCH_QUERIES = ["ноутбук", "планшет"]

# ---------- БАЗА ----------
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            article INTEGER PRIMARY KEY,
            name TEXT,
            last_price REAL
        )
    """)
    conn.commit()
    conn.close()

# ---------- ТОВАРЫ ----------
async def search_products(query):
    url = (
        "https://search.wb.ru/exactmatch/ru/common/v5/search"
        f"?query={query}&resultset=catalog&limit=100"
        f"&dest=-1257786&curr=rub&spp=30"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
        "Accept": "*/*",
        "Origin": "https://www.wildberries.ru",
        "Referer": "https://www.wildberries.ru/",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status != 200:
                    print(f"⚠️ Поиск '{query}': HTTP {response.status}")
                    return []
                data = await response.json()
                products = data.get("data", {}).get("products", [])
                print(f"📦 Поиск '{query}': загружено {len(products)} товаров.")
                return products
    except Exception as e:
        print(f"❌ Ошибка поиска '{query}': {e}")
        return []

# ---------- ОСНОВНОЙ ЦИКЛ (ВНУТРИ EVENT LOOP БОТА) ----------
async def price_monitor_loop(application: Application):
    # ждём, пока приложение реально стартует
    while not application.running:
        await asyncio.sleep(1)

    while True:
        print("🔄 Проверка категорий...")
        all_products = []
        for q in SEARCH_QUERIES:
            products = await search_products(q)
            all_products.extend(products)
            await asyncio.sleep(3)

        if not all_products:
            print("📭 Товары не получены.")
        else:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            alerts = 0

            for prod in all_products:
                article = prod.get("id")
                if not article:
                    continue

                name = f"{prod.get('brand', '')} {prod.get('name', '')}".strip()

                sizes = prod.get("sizes") or []
                if not sizes:
                    continue
                price_info = sizes[0].get("price", {})
                current_price = (price_info.get("salePriceU") or 0) / 100
                if current_price == 0:
                    continue

                cur.execute(
                    "SELECT name, last_price FROM products WHERE article = ?",
                    (article,),
                )
                row = cur.fetchone()

                if row is None:
                    cur.execute(
                        "INSERT INTO products (article, name, last_price) VALUES (?, ?, ?)",
                        (article, name, current_price),
                    )
                else:
                    _, last_price = row
                    if current_price < last_price:
                        drop = ((last_price - current_price) / last_price) * 100
                        if drop >= PRICE_DROP_PERCENT:
                            print(f"🔥 СКИДКА: {name} (-{drop:.1f}%)")
                            safe = (
                                name.replace("_", "\\_")
                                    .replace("*", "\\*")
                                    .replace("`", "\\`")
                            )
                            msg = (
                                f"🚨 *ЦЕНА УПАЛА!*\n\n"
                                f"📦 *Товар:* {safe}\n"
                                f"🆔 *Артикул:* `{article}`\n"
                                f"📉 *Было:* {last_price:.0f} ₽\n"
                                f"🔥 *Стало:* {current_price:.0f} ₽ (-{drop:.1f}%)\n\n"
                                f"🔗 [Открыть на WB](https://www.wildberries.ru/catalog/{article}/detail.aspx)"
                            )
                            try:
                                await application.bot.send_message(
                                    chat_id=CHAT_ID, text=msg, parse_mode="Markdown"
                                )
                                alerts += 1
                                await asyncio.sleep(0.5)
                            except Exception as te:
                                print(f"⚠️ Отправка: {te}")

                    cur.execute(
                        "UPDATE products SET last_price = ? WHERE article = ?",
                        (current_price, article),
                    )

            conn.commit()
            conn.close()
            print(f"✅ Обновлено. Алертов: {alerts}")

        print("💤 Сон 5 минут...")
        await asyncio.sleep(300)

# ---------- TELEGRAM ----------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Привет, {user_name}! 👋\n\n"
        f"🤖 Мониторю *Ноутбуки* и *Планшеты* на WB.\n"
        f"📉 Если цена упадёт на {PRICE_DROP_PERCENT}% и больше — пришлю алерт."
    )

async def on_startup(application: Application):
    """Запускает фоновый цикл внутри уже работающего event loop."""
    application.create_task(price_monitor_loop(application))

# ---------- MAIN ----------
def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Нет TELEGRAM_TOKEN или CHAT_ID!")
        return
    init_db()
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(on_startup)
        .build()
    )
    app.add_handler(CommandHandler("start", start_command))
    print("🚀 Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()

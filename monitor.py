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

# База в /app/data — переживает пересборку контейнера на BotHost
DB_PATH = os.getenv("DB_PATH", "/app/data/prices.db")

# Внутренние subject ID подкатегорий WB
CATEGORIES = [5130, 5133]  # ноутбуки, планшеты
SHARD = "electronic"

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
async def get_category_products(subject_id):
    url = (
        f"https://catalog.wb.ru/catalog/{SHARD}/v2/catalog"
        f"?appType=1&curr=rub&dest=-1257786&sort=popular"
        f"&spp=30&subject={subject_id}&page=1"
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
                    print(f"⚠️ Категория {subject_id}: HTTP {response.status}")
                    return []
                data = await response.json()
                products = data.get("data", {}).get("products", [])
                print(f"📦 Категория {subject_id}: загружено {len(products)} товаров.")
                return products
    except Exception as e:
        print(f"❌ Ошибка категории {subject_id}: {e}")
        return []

# ---------- ЦИКЛ ----------
async def check_prices(application: Application):
    while True:
        print("🔄 Проверка категорий...")
        all_products = []
        for cat_id in CATEGORIES:
            products = await get_category_products(cat_id)
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

async def post_init(application: Application):
    application.create_task(check_prices(application))

# ---------- MAIN ----------
def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Нет TELEGRAM_TOKEN или CHAT_ID!")
        return
    init_db()
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start_command))
    print("🚀 Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()

import os
import time
import sqlite3
import requests
from telegram import Bot
from dotenv import load_dotenv

# Загружаем переменные из файла .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PRICE_DROP_PERCENT = 15 

# Твои тестовые артикулы техники
TRACKED_ARTICLES = [
    214328456,  
    154673412,
    180900123
]

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: Переменные TELEGRAM_TOKEN или CHAT_ID не найдены в .env!")
    exit(1)

bot = Bot(token=TELEGRAM_TOKEN)

def init_db():
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

def get_wb_data(articles):
    id_list = ";".join(map(str, articles))
    # Актуальный и стабильный API эндпоинт каталога WB
    url = f"https://wb.ru{id_list}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", {}).get("products", [])
    except Exception as e:
        print(f"Ошибка при запросе к WB: {e}")
    return []

def check_prices():
    print("🔄 Проверяю цены на Wildberries...")
    products = get_wb_data(TRACKED_ARTICLES)
    
    if not products:
        print("📭 Не удалось получить данные о товарах. Возможно, API изменился или временный сбой.")
        return

    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()

    for prod in products:
        article = prod.get("id")
        name = prod.get("name")
        # Берём цену со всеми скидками (salePriceU). Делим на 100, так как WB отдаёт в копейках.
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
                        bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
                    except Exception as te:
                        print(f"⚠️ Ошибка отправки в TG: {te}")

            cursor.execute("UPDATE products SET last_price = ? WHERE article = ?", (current_price, article))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    while True:
        try:
            check_prices()
        except Exception as global_e:
            print(f"💥 Критическая ошибка: {global_e}")
            
        print("💤 Жду 5 минут...")
        time.sleep(300)

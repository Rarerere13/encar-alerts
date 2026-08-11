"""
Телеграм-бот: следит за новыми объявлениями на encar.com по заданному фильтру
и присылает уведомления в Telegram.

Как это работает:
1. Скрипт запускается по расписанию (каждые 10 минут через GitHub Actions).
2. Делает запрос к внутреннему API encar.com с твоим фильтром (ENCAR_API_URL).
3. Сравнивает список ID объявлений с тем, что видел в прошлый раз (seen_ids.json).
4. Если появились новые ID — присылает по ним сообщения в Telegram.
5. Сохраняет обновлённый список ID (через GitHub Actions cache — см. workflow).

Важно: на самом первом запуске бот НЕ будет спамить всей историей объявлений —
он просто запомнит текущий список как точку отсчёта.
"""

import os
import json
import time
import logging
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("encar-bot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
ENCAR_API_URL = os.environ["ENCAR_API_URL"]

STATE_FILE = "seen_ids.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "http://www.encar.com/",
    "Accept": "application/json, text/plain, */*",
}


def load_seen_ids():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                return set()
    return set()


def save_seen_ids(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False)


def fetch_listings():
    resp = requests.get(ENCAR_API_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    # ВАЖНО: структура ответа encar может отличаться в зависимости от версии API.
    # Если бот при первом запуске в логах GitHub Actions пишет "0 listings fetched",
    # хотя объявления точно есть — открой Actions -> последний запуск -> в шаге
    # "Run bot" добавь временно print(json.dumps(data)[:2000]) и посмотри, как
    # реально называется ключ со списком объявлений (обычно SearchResults).
    listings = data.get("SearchResults", [])
    log.info("Fetched %d listings from encar", len(listings))
    return listings


def format_message(car):
    manufacturer = car.get("Manufacturer", "")
    model = car.get("Model", "")
    badge = car.get("Badge", "")
    title = " ".join(part for part in [manufacturer, model, badge] if part)

    year = car.get("FormYear") or car.get("Year")
    mileage = car.get("Mileage")
    price = car.get("Price")
    car_id = car.get("Id")

    url = f"http://www.encar.com/dc/dc_cardetailview.do?carid={car_id}"

    lines = [f"🚗 {title or 'Новое объявление'}"]
    if year:
        lines.append(f"Год: {year}")
    if mileage is not None:
        try:
            lines.append(f"Пробег: {int(mileage):,} км".replace(",", " "))
        except (TypeError, ValueError):
            lines.append(f"Пробег: {mileage}")
    if price is not None:
        lines.append(f"Цена: {price} (в единицах encar — обычно ×10 000 KRW)")
    lines.append(url)
    return "\n".join(lines)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    if not resp.ok:
        log.error("Telegram send failed: %s", resp.text)


def main():
    seen = load_seen_ids()
    first_run = len(seen) == 0
    log.info("Loaded %d previously seen listing IDs", len(seen))

    try:
        listings = fetch_listings()
    except Exception as e:
        log.error("Failed to fetch encar listings: %s", e)
        return

    current_ids = {str(car.get("Id")) for car in listings if car.get("Id") is not None}

    if first_run:
        log.info(
            "First run — saving %d listings as baseline, no notifications sent.",
            len(current_ids),
        )
    else:
        fresh = [car for car in listings if str(car.get("Id")) not in seen]
        log.info("Found %d new listing(s).", len(fresh))
        for car in fresh:
            send_telegram(format_message(car))
            time.sleep(1)  # не спамим Telegram API слишком быстро

    save_seen_ids(seen | current_ids)


if __name__ == "__main__":
    main()

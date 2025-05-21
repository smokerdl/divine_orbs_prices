import requests
from bs4 import BeautifulSoup
import logging
import json
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    filename=f"funpay_debug_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Заголовки для имитации браузера
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

# URL для PoE и PoE2
POE_URL = "https://funpay.com/chips/173/?server=10480"  # (pc)_settlers_of_kalguur
POE2_URL = "https://funpay.com/chips/209/?server=11287"  # dawn_of_the_hunt

def fetch_offers(url):
    """Получение и парсинг страницы FunPay."""
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        logging.info(f"Успешно получена страница: {url}")
        return response.text
    except requests.RequestException as e:
        logging.error(f"Ошибка при запросе {url}: {e}")
        return None

def parse_offers(html, game_name):
    """Парсинг офферов из HTML."""
    soup = BeautifulSoup(html, "html.parser")
    offers = soup.select(".tc-item")  # Селектор для строк офферов
    if not offers:
        logging.warning(f"Не найдено офферов на странице для {game_name}")
        return []

    result = []
    for offer in offers:
        try:
            # Извлечение данных
            name_elem = offer.select_one(".tc-desc-text")
            price_elem = offer.select_one(".tc-price")
            amount_elem = offer.select_one(".tc-amount")
            seller_status = offer.select_one(".media-user-status")

            # Сырые данные для лога
            raw_name = name_elem.text.strip() if name_elem else "N/A"
            raw_price = price_elem.text.strip() if price_elem else "N/A"
            raw_amount = amount_elem.text.strip() if amount_elem else "N/A"
            raw_status = seller_status.text.strip() if seller_status else "N/A"

            # Логирование сырых данных
            logging.debug(f"Оффер ({game_name}): name={raw_name}, price={raw_price}, amount={raw_amount}, status={raw_status}")

            # Проверка на Divine Orbs
            if not name_elem or not ("divine orb" in raw_name.lower() or "божественная сфера" in raw_name.lower()):
                logging.debug(f"Пропущен оффер: неверное название ({raw_name})")
                continue

            # Проверка статуса продавца
            is_online = "online" in raw_status.lower()
            if not is_online:
                logging.debug(f"Пропущен оффер: продавец не онлайн ({raw_status})")
                continue

            # Проверка наличия цены и количества
            if not price_elem or not amount_elem:
                logging.debug(f"Пропущен оффер: отсутствует цена или количество")
                continue

            # Извлечение числовых данных
            try:
                price = float(price_elem.text.strip().replace("₽", "").replace(",", "."))
                amount = int(amount_elem.text.strip().replace(" ", ""))
            except ValueError as e:
                logging.debug(f"Пропущен оффер: ошибка преобразования цены/количества ({e})")
                continue

            # Формирование результата
            offer_data = {
                "name": raw_name,
                "price_rub": price,
                "amount": amount,
                "seller_status": raw_status
            }
            result.append(offer_data)
            logging.info(f"Добавлен оффер: {offer_data}")
        except Exception as e:
            logging.error(f"Ошибка при обработке оффера: {e}")
            continue

    return result

def main():
    """Основная функция."""
    # Парсинг PoE
    poe_html = fetch_offers(POE_URL)
    if poe_html:
        poe_offers = parse_offers(poe_html, "PoE")
        logging.info(f"Найдено {len(poe_offers)} офферов для PoE")
        with open("poe_offers.json", "w", encoding="utf-8") as f:
            json.dump(poe_offers, f, ensure_ascii=False, indent=2)

    # Парсинг PoE2
    poe2_html = fetch_offers(POE2_URL)
    if poe2_html:
        poe2_offers = parse_offers(poe2_html, "PoE2")
        logging.info(f"Найдено {len(poe2_offers)} офферов для PoE2")
        with open("poe2_offers.json", "w", encoding="utf-8") as f:
            json.dump(poe2_offers, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()

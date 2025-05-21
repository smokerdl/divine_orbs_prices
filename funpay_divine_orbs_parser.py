import json
import logging
import re
from datetime import datetime

import pytz
import requests
from bs4 import BeautifulSoup

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("parser.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Константы
POE_URL = "https://funpay.com/clips/173/"
POE2_URL = "https://funpay.com/clips/209/"
CBRF_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
LEAGUES_FILE = "current_leagues.json"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}

def get_exchange_rate():
    """Получить курс USD/RUB от ЦБ РФ."""
    logger.info("Получение курса USD/RUB от ЦБ РФ...")
    try:
        response = requests.get(CBRF_URL, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.warning(f"Не удалось получить курс USD/RUB: {response.status_code}")
            return 80.0  # Фиктивный курс
        data = response.json()
        rate = data["Valute"]["USD"]["Value"]
        logger.info(f"Курс USD/RUB: {rate}")
        return rate
    except Exception as e:
        logger.error(f"Ошибка получения курса USD/RUB: {e}")
        return 80.0  # Фиктивный курс

def get_league_id(game, url):
    """Получить ID лиги для игры."""
    logger.info(f"Получение списка лиг для {game}...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        logger.info(f"Статус ответа FunPay для {game}: {response.status_code}")
        if response.status_code != 200:
            logger.warning(f"Не удалось получить список лиг для {game}")
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        with open(f'funpay_leagues_{game}.html', 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        logger.info(f"HTML страницы лиг для {game} сохранён")
        
        if game == 'poe':
            league_name = 'settlers_of_kalguur'
            select = soup.find('select', {'name': 'server'})
            if not select:
                logger.warning(f"Селектор select[name=server] не найден для {game}")
                return None
            option = select.find('option', string=lambda text: text and league_name in text.lower())
            if not option:
                logger.warning(f"Лига {league_name} не найдена для {game}")
                return None
            league_id = option['value']
            logger.info(f"Найдена лига для {game}: {league_name} (ID: {league_id})")
            return league_id
        else:  # poe2
            league_name = 'dawn_of_the_hunt'
            select = soup.find('select', {'name': 'server'})
            if not select:
                logger.warning(f"Селектор select[name=server] не найден для {game}")
                return None
            option = select.find('option', string=lambda text: text and league_name in text.lower())
            if not option:
                logger.warning(f"Лига {league_name} не найдена для {game}")
                return None
            league_id = option['value']
            logger.info(f"Найдена лига для {game}: {league_name} (ID: {league_id})")
            return league_id
    except Exception as e:
        logger.error(f"Ошибка получения списка лиг для {game}: {e}")
        return None

def get_sellers(game, league_id):
    """Получить данные о продавцах для лиги (без онлайн-фильтра, с отладкой Divine Orbs)."""
    logger.info(f"Сбор данных о продавцах для {game} (лига {league_id})...")
    url = POE_URL if game == 'poe' else POE2_URL + "?currency=0"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        logger.info(f"Статус ответа FunPay для {game} (лига {league_id}): {response.status_code}")
        if response.status_code != 200:
            logger.warning(f"Не удалось получить продавцов для {game} (лига {league_id})")
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        with open(f'funpay_sellers_{game}.html', 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        logger.info(f"HTML продавцов для {game} сохранён")
        
        offers = soup.find_all("a", class_="tc-item", attrs={"data-server": league_id})
        logger.info(f"Найдено продавцов для {game} (лига {league_id}): {len(offers)}")
        if not offers:
            logger.warning(f"Селектор a.tc-item с data-server={league_id} не нашёл продавцов")
            return []
        
        sellers = []
        exchange_rate = get_exchange_rate()
        for index, offer in enumerate(offers, 1):
            try:
                # Логирование онлайн-статуса (для отладки)
                tc_user = offer.find("div", class_="tc-user")
                avatar_photo = offer.find("div", class_="avatar-photo")
                logger.debug(f"Продавец на позиции {index}: tc-user: {tc_user.get('class', [])}, avatar: {avatar_photo.get('class', [])}")
                
                # Проверка Divine Orbs (для PoE 2)
                if game == 'poe2':
                    desc_elem = offer.find("div", class_="tc-desc")
                    desc_text = desc_elem.text.strip() if desc_elem else "отсутствует"
                    logger.debug(f"Продавец на позиции {index}: Divine Orbs check (найдено: {desc_text})")
                
                # Имя продавца
                username_elem = offer.find("div", class_="media-user-name")
                username = username_elem.text.strip() if username_elem else None
                if not username:
                    logger.debug(f"Пропущен оффер на позиции {index}: отсутствует имя")
                    continue
                
                # Количество
                amount_elem = offer.find("div", class_="tc-amount")
                amount = re.sub(r"[^\d]", "", amount_elem.text.strip()) if amount_elem else "0"
                
                # Цена
                price_elem = offer.find("div", class_="tc-price")
                if not price_elem:
                    logger.debug(f"Пропущен оффер для {username}: отсутствует цена")
                    continue
                price_inner = price_elem.find("div")
                if not price_inner:
                    logger.debug(f"Пропущен оффер для {username}: отсутствует div в tc-price")
                    continue
                price_text = price_inner.text
                price_span = price_inner.find("span", class_="unit")
                if price_span:
                    price_text = price_text.replace(price_span.text, "").strip()
                price = re.sub(r"[^\d.]", "", price_text.replace(",", "."))
                try:
                    price = float(price)
                    if "$" in price_elem.text:
                        price = price * exchange_rate
                        logger.debug(f"Конверсия для {username}: {price / exchange_rate} $ -> {price} ₽")
                    price = round(price, 2)
                except ValueError:
                    logger.debug(f"Пропущен оффер для {username}: неверный формат цены ({price_text})")
                    continue
                
                logger.debug(f"Обработан продавец: {username} (позиция {index}, {amount} шт., {price} ₽)")
                sellers.append({
                    "Timestamp": datetime.now(pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S"),
                    "Seller": username,
                    "Stock": amount,
                    "Price": price,
                    "Position": index
                })
            except Exception as e:
                logger.debug(f"Ошибка обработки продавца на позиции {index}: {e}")
                continue
        
        # Фильтрация позиций 4–13
        filtered_sellers = [s for s in sellers if 3 < s["Position"] <= 13]
        logger.info(f"Отфильтровано продавцов для {game}: {len(filtered_sellers)} (позиции 4–13)")
        return filtered_sellers
    except Exception as e:
        logger.error(f"Ошибка получения продавцов для {game} (лига {league_id}): {e}")
        return []

def save_leagues(leagues):
    """Сохранить данные о лигах в JSON."""
    try:
        with open(LEAGUES_FILE, 'w', encoding='utf-8') as f:
            json.dump(leagues, f, ensure_ascii=False, indent=4)
        logger.info(f"Файл {LEAGUES_FILE} обновлён")
    except Exception as e:
        logger.error(f"Ошибка сохранения файла {LEAGUES_FILE}: {e}")

def save_sellers(game, league_name, sellers):
    """Сохранить данные о продавцах в JSON."""
    if not sellers:
        logger.info(f"Нет данных о продавцах для {game} ({league_name})")
        return
    year_month = datetime.now().strftime("%Y-%m")
    filename = f"prices_{game}_{league_name}_{year_month}.json"
    try:
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except FileNotFoundError:
            existing_data = []
        existing_data.extend(sellers)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Файл {filename} создан, записей: {len(sellers)}")
    except Exception as e:
        logger.error(f"Ошибка сохранения файла {filename}: {e}")

def main():
    """Основная функция парсера."""
    logger.info("Парсер запущен")
    
    # Получение лиг
    poe_league_id = get_league_id('poe', POE_URL)
    poe2_league_id = get_league_id('poe2', POE2_URL)
    
    leagues = {'poe': [], 'poe2': []}
    if poe_league_id:
        leagues['poe'].append('settlers_of_kalguur')
    if poe2_league_id:
        leagues['poe2'].append('dawn_of_the_hunt')
    
    # Получение продавцов
    poe_sellers = get_sellers('poe', poe_league_id) if poe_league_id else []
    poe2_sellers = get_sellers('poe2', poe2_league_id) if poe2_league_id else []
    
    # Сохранение данных
    save_sellers('poe', 'settlers_of_kalguur', poe_sellers)
    save_sellers('poe2', 'dawn_of_the_hunt', poe2_sellers)
    save_leagues(leagues)
    
    logger.info(f"Завершено: {datetime.now(pytz.timezone('Europe/Moscow')).isoformat()}")

if __name__ == "__main__":
    main()

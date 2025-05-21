import json
import logging
import os
import re
import time
from datetime import datetime
import pytz
import requests
from bs4 import BeautifulSoup
from github import Github
from fake_useragent import UserAgent

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('0_parse.txt', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Константы
POE_URL = "https://funpay.com/chips/86/"
POE2_URL = "https://funpay.com/chips/209/"
log_dir = os.path.dirname(os.path.abspath(__file__))
ua = UserAgent()
headers = {
    "User-Agent": ua.random,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

# Получение продавцов
def get_sellers(game, league_id):
    logger.info(f"Сбор данных о продавцах для {game} (лига {league_id})...")
    url = POE_URL if game == 'poe' else POE2_URL
    session = requests.Session()
    session.headers.update(headers)
    SBP_COMMISSION = 1.2118
    CARD_COMMISSION = 1.2526
    FUNPAY_EXCHANGE_RATE = 79.89
    
    for attempt in range(3):
        try:
            response = session.get(url, timeout=15)
            logger.info(f"Статус ответа FunPay для {game} (лига {league_id}): {response.status_code}")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            with open(os.path.join(log_dir, f'funpay_sellers_{game}.html'), 'w', encoding='utf-8') as f:
                f.write(soup.prettify())
            logger.info(f"HTML продавцов для {game} сохранён")
            
            offers = soup.find_all("a", class_="tc-item")
            logger.info(f"Найдено продавцов для {game} (лига {league_id}): {len(offers)}")
            if not offers:
                logger.warning(f"Селектор a.tc-item с data-server={league_id} не нашёл продавцов")
                return []
            
            sellers = []
            min_price_rub = 0.5 if game == 'poe' else 5.0
            target_positions = [4, 5, 6, 7, 8]  # Собираем только 4–8 места
            valid_offers = []
            debug_count = 0  # Для логирования первых 10 офферов
            
            for index, offer in enumerate(offers, 1):
                try:
                    if str(offer.get("data-server")) != str(league_id):
                        continue
                    
                    username_elem = offer.find("div", class_="media-user-name")
                    username = username_elem.text.strip() if username_elem else None
                    if not username:
                        logger.debug(f"Пропущен оффер {index}: нет имени пользователя")
                        continue
                    
                    orb_type = "Божественные сферы" if game == 'poe' else "Неизвестно"
                    if game == 'poe2':
                        desc_elem = offer.find("div", class_="tc-desc")
                        desc_text = desc_elem.text.strip().lower() if desc_elem else ""
                        side_elem = offer.find("div", class_="tc-side") or offer.find("div", class_="tc-side-inside")
                        side_text = side_elem.text.strip().lower() if side_elem else ""
                        logger.debug(f"tc-desc для {username}: {desc_text}")
                        logger.debug(f"tc-side для {username}: {side_text}")
                        # Проверяем наличие Divine Orbs
                        divine_keywords = ["divine", "божественные сферы", "divine orb", "божественная сфера"]
                        if not any(keyword in desc_text or keyword in side_text for keyword in divine_keywords):
                            logger.debug(f"Пропущен оффер для {username}: нет Divine Orbs в описании")
                            continue
                        # Исключаем другие валюты и нежелательные офферы
                        exclude_keywords = [
                            "хаос", "ваал", "exalted", "chaos", "vaal", "exalt", "regal", "alch", 
                            "blessed", "chromatic", "jeweller", "fusing", "scour", "chance", 
                            "аккаунт", "услуги", "account", "service"
                        ]
                        if any(keyword in desc_text or keyword in side_text for keyword in exclude_keywords):
                            logger.debug(f"Пропущен оффер для {username}: содержит нежелательные ключевые слова")
                            continue
                        orb_type = "Божественные сферы"
                    
                    amount_elem = offer.find("div", class_="tc-amount")
                    amount = re.sub(r"[^\d]", "", amount_elem.text.strip()) if amount_elem else "0"
                    logger.debug(f"Сток для {username}: {amount}")
                    
                    price_elem = offer.find("div", class_="tc-price")
                    if not price_elem:
                        logger.debug(f"Пропущен оффер для {username}: нет элемента цены")
                        continue
                    price_inner = price_elem.find("div") or price_elem.find("span")
                    price_text = price_inner.text.strip() if price_inner else price_elem.text.strip()
                    logger.debug(f"Сырой текст цены для {username}: '{price_text}'")
                    
                    if not price_text:
                        logger.debug(f"Пропущен оффер для {username}: пустой текст цены")
                        continue
                    
                    price_text_clean = re.sub(r"[^\d.]", "", price_text).strip()
                    logger.debug(f"Очищенный текст цены для {username}: '{price_text_clean}'")
                    # Проверка формата цены (10, 10.0, 10.00)
                    if not re.match(r"^\d+(\.\d{1,2})?$", price_text_clean):
                        logger.debug(f"Пропущен оффер для {username}: неверный формат цены ({price_text_clean})")
                        continue
                    try:
                        price_rub = float(price_text_clean)
                        logger.debug(f"Цена в RUB для {username}: {price_rub}")
                        if price_rub < min_price_rub:
                            logger.debug(f"Пропущен оффер для {username}: цена слишком низкая ({price_rub} RUB)")
                            continue
                        price_usd = round(price_rub / FUNPAY_EXCHANGE_RATE, 3)
                        price_sbp = round(price_rub * SBP_COMMISSION, 2)
                        price_card = round(price_rub * CARD_COMMISSION, 2)
                        logger.debug(f"Цена для {username}: {price_rub} RUB (USD: {price_usd} $, СБП: {price_sbp} ₽, Карта: {price_card} ₽)")
                    except ValueError:
                        logger.debug(f"Пропущен оффер для {username}: ошибка преобразования цены ({price_text_clean})")
                        continue
                    
                    valid_offers.append({
                        "Timestamp": datetime.now(pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S"),
                        "Seller": username,
                        "Stock": amount,
                        "Price": price_usd,
                        "Currency": "RUB",
                        "Position": index
                    })
                    
                    # Отладка: логируем первые 10 офферов
                    if debug_count < 10:
                        logger.debug(f"Отладка оффера {index}: {username}, Цена: {price_rub} RUB, tc-desc: {desc_text}, tc-side: {side_text}")
                        debug_count += 1
                
                except Exception as e:
                    logger.debug(f"Ошибка обработки оффера {index}: {e}")
                    continue
            
            logger.info(f"Найдено валидных офферов для {game}: {len(valid_offers)}")
            valid_offers.sort(key=lambda x: x["Position"])
            for offer in valid_offers:
                if len(sellers) < 5 and offer["Position"] in target_positions:
                    sellers.append(offer)
            
            logger.info(f"Собрано продавцов для {game}: {len(sellers)} (позиции 4–8)")
            return sellers
        except requests.exceptions.RequestException as e:
            logger.error(f"Попытка {attempt + 1} не удалась для {url}: {e}")
            if attempt == 2:
                logger.error(f"Все попытки исчерпаны для {game} (лига {league_id})")
                return []
            time.sleep(2)

# Получение лиг
def get_leagues(game):
    logger.info(f"Получение лиг для {game}...")
    url = POE_URL if game == 'poe' else POE2_URL
    session = requests.Session()
    session.headers.update(headers)
    
    for attempt in range(3):
        try:
            response = session.get(url, timeout=15)
            logger.info(f"Статус ответа FunPay для лиг {game}: {response.status_code}")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            with open(os.path.join(log_dir, f'funpay_leagues_{game}.html'), 'w', encoding='utf-8') as f:
                f.write(soup.prettify())
            logger.info(f"HTML лиг для {game} сохранён")
            
            league_select = soup.find("select", class_="form-control")
            leagues = []
            if league_select:
                options = league_select.find_all("option")
                logger.info(f"Найдено лиг для {game}: {len(options)}")
                for option in options:
                    league_id = option.get("value")
                    league_name = option.text.strip()
                    if league_id and league_name:
                        leagues.append({"id": league_id, "name": league_name})
            
            logger.info(f"Данные успешно сохранены в {os.path.join(log_dir, 'league_ids.json')}")
            return leagues
        except requests.exceptions.RequestException as e:
            logger.error(f"Попытка {attempt + 1} не удалась для {url}: {e}")
            if attempt == 2:
                logger.error(f"Все попытки исчерпаны для лиг {game}")
                return []
            time.sleep(2)

# Сохранение данных
def save_data(data, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logger.info(f"Данные успешно сохранены в {filename}")

# Обновление репозитория
def update_repository(filename, commit_message, github_token):
    g = Github(github_token)
    repo = g.get_repo("smokerdl/divine_orbs_prices")
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    file_path = os.path.basename(filename)
    try:
        contents = repo.get_contents(file_path)
        repo.update_file(contents.path, commit_message, content, contents.sha)
    except:
        repo.create_file(file_path, commit_message, content)
    logger.info(f"Файл {file_path} обновлён в репозитории")

# Основная функция
def main():
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("GITHUB_TOKEN не установлен")
        return
    
    games = [
        {"name": "poe", "league_id": "10480", "output_file": "prices_poe_settlers_of_kalguur_2024-07.json"},
        {"name": "poe2", "league_id": "11287", "output_file": "prices_poe2_dawn_of_the_hunt_2024-12.json"}
    ]
    
    for game in games:
        logger.info(f"Обработка игры: {game['name']}")
        sellers = get_sellers(game["name"], game["league_id"])
        if sellers:
            output_file = os.path.join(log_dir, game["output_file"])
            save_data(sellers, output_file)
            update_repository(output_file, f"Update {game['output_file']}", github_token)
        else:
            logger.warning(f"Нет данных для сохранения для {game['name']}")
        
        leagues = get_leagues(game["name"])
        if leagues:
            league_file = os.path.join(log_dir, "league_ids.json")
            save_data(leagues, league_file)
            update_repository(league_file, "Update league_ids.json", github_token)
        logger.info(f"Сохранено в {game['output_file']}")
        logger.info(f"Сохранено в league_ids.json")

if __name__ == "__main__":
    main()

import os
import requests
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import json
import logging
from fake_useragent import UserAgent
from github import Github

# Настройка логирования
log_dir = "c:/Users/smk79/Documents/Скрипты Pythons/"
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, "0_parse.txt"),
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Консольный вывод
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(console_handler)

POE_URL = "https://funpay.com/chips/173/"
POE2_URL = "https://funpay.com/chips/209/?side=106"
ua = UserAgent()

headers = {
    "User-Agent": ua.random,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Referer": "https://funpay.com/",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1"
}

def get_sellers(game, league_id):
    logger.info(f"Сбор данных о продавцах для {game} (лига {league_id})...")
    url = POE_URL if game == 'poe' else POE2_URL
    session = requests.Session()
    session.headers.update(headers)
    
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
            for index, offer in enumerate(offers, 1):
                try:
                    logger.debug(f"Обрабатываем оффер {index}: {offer.prettify()[:200]}...")
                    
                    # Проверка data-server
                    if str(offer.get("data-server")) != str(league_id):
                        logger.debug(f"Пропущен оффер {index}: data-server ({offer.get('data-server')}) не соответствует лиге {league_id}")
                        continue
                    
                    username_elem = offer.find("div", class_="media-user-name")
                    username = username_elem.text.strip() if username_elem else None
                    if not username:
                        logger.debug(f"Пропущен оффер {index}: отсутствует имя")
                        continue
                    
                    # Поиск типа сферы
                    orb_type = "Божественные сферы" if game == 'poe' else "Неизвестно"
                    if game == 'poe2':
                        desc_elem = offer.find("div", class_="tc-desc")
                        desc_text = desc_elem.text.strip().lower() if desc_elem else ""
                        logger.debug(f"tc-desc для {username}: {desc_text}")
                        side_elem = offer.find("div", class_="tc-side") or offer.find("div", class_="tc-side-inside")
                        side_text = side_elem.text.strip().lower() if side_elem else ""
                        logger.debug(f"tc-side или tc-side-inside для {username}: {side_text}")
                        if ("divine" in desc_text or "божественные сферы" in side_text.lower() or offer.get("data-side") == "106"):
                            orb_type = "Божественные сферы"
                        if orb_type != "Божественные сферы":
                            logger.debug(f"Пропущен оффер для {username}: тип сферы не Divine Orbs ({orb_type})")
                            continue
                    
                    amount_elem = offer.find("div", class_="tc-amount")
                    amount = re.sub(r"[^\d]", "", amount_elem.text.strip()) if amount_elem else "0"
                    logger.debug(f"Сток для {username}: {amount}")
                    
                    price_elem = offer.find("div", class_="tc-price")
                    if not price_elem:
                        logger.debug(f"Пропущен оффер {index}: отсутствует цена")
                        continue
                    price_inner = price_elem.find("div") or price_elem.find("span")
                    price_text = price_inner.text.strip() if price_inner else ""
                    logger.debug(f"Сырой текст цены для {username}: {price_text}")
                    
                    if not price_text:
                        logger.debug(f"Пропущен оффер {index}: пустая цена")
                        continue
                    
                    # Определение валюты
                    currency_elem = price_inner.find("span", class_="unit") if price_inner else None
                    currency = "RUB"  # По умолчанию рубли
                    if currency_elem:
                        currency_text = currency_elem.text.strip()
                        currency = "USD" if "$" in currency_text else "RUB"
                    logger.debug(f"Валюта для {username}: {currency}")
                    
                    # Очистка цены
                    price_text = re.sub(r"[^\d.]", "", price_text).strip()
                    if not re.match(r"^\d*\.\d+$", price_text):
                        logger.debug(f"Пропущен оффер для {username}: неверный формат цены ({price_text})")
                        continue
                    try:
                        price = float(price_text)
                        price = round(price, 2)
                    except ValueError:
                        logger.debug(f"Пропущен оффер для {username}: не удалось преобразовать цену ({price_text})")
                        continue
                    
                    logger.debug(f"Обработан продавец: {username} (позиция {index}, {amount} шт., {price} {currency}, тип: {orb_type})")
                    sellers.append({
                        "Timestamp": datetime.now(pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S"),
                        "Seller": username,
                        "Stock": amount,
                        "Price": price,
                        "Currency": currency,
                        "Position": index
                    })
                
                except Exception as e:
                    logger.debug(f"Ошибка обработки оффера {index}: {e}")
                    continue
            
            logger.info(f"Собрано продавцов для {game}: {len(sellers)}")
            if not sellers:
                logger.warning(f"Нет валидных продавцов для {game} (лига {league_id})")
                return []
            
            # Фильтр цен для PoE 2
            filtered_sellers = sellers
            if game == 'poe2' and sellers:
                min_price = min(s["Price"] for s in sellers)
                logger.info(f"Минимальная цена для PoE 2: {min_price} {sellers[0]['Currency']}")
                filtered_sellers = [s for s in sellers if s["Price"] <= min_price * 2]
                logger.info(f"После фильтра цен (<= {min_price * 2} {sellers[0]['Currency']}): {len(filtered_sellers)} продавцов")
            
            return filtered_sellers
        except requests.exceptions.RequestException as e:
            logger.error(f"Попытка {attempt + 1} не удалась для {url}: {e}")
            if attempt == 2:
                logger.error(f"Все попытки исчерпаны для {game} (лига {league_id})")
                return []
            time.sleep(2)

def get_leagues(game):
    logger.info(f"Получение лиг для {game}...")
    url = "https://funpay.com/chips/" + ("173/" if game == "poe" else "209/")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        logger.info(f"Статус ответа FunPay для лиг {game}: {response.status_code}")
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        with open(os.path.join(log_dir, f'funpay_leagues_{game}.html'), 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        logger.info(f"HTML лиг для {game} сохранён")
        
        leagues = []
        for option in soup.find_all("option"):
            league_name = option.text.strip()
            league_id = option.get("value")
            if league_id:
                leagues.append({"name": league_name, "id": league_id})
                logger.debug(f"Найдена лига: {league_name} (ID: {league_id})")
        logger.info(f"Найдено лиг для {game}: {len(leagues)}")
        return leagues
    except Exception as e:
        logger.error(f"Ошибка получения лиг для {game}: {e}")
        return []

def save_to_json(data, filename):
    try:
        logger.debug(f"Попытка сохранить данные в {filename}: {data}")
        if not data:
            logger.warning(f"Нет данных для сохранения в {filename}")
            return
        filepath = os.path.join(log_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"Данные успешно сохранены в {filepath}")
    except Exception as e:
        logger.error(f"Ошибка сохранения в {filepath}: {e}")
        raise

def upload_to_github(data, filename, repo_name, token):
    logger.debug(f"Начало загрузки {filename} в GitHub")
    try:
        if not token:
            logger.error("GITHUB_TOKEN не задан")
            return
        g = Github(token)
        repo = g.get_repo(repo_name)
        content = json.dumps(data, ensure_ascii=False, indent=4)
        logger.debug(f"Содержимое для {filename}: {content[:100]}...")
        try:
            file = repo.get_contents(filename)
            repo.update_file(file.path, f"Update {filename}", content, file.sha)
            logger.info(f"Файл {filename} обновлён в репозитории")
        except Exception as create_e:
            logger.debug(f"Файл {filename} не существует, создаём: {create_e}")
            repo.create_file(filename, f"Create {filename}", content)
            logger.info(f"Файл {filename} создан в репозитории")
    except Exception as e:
        logger.error(f"Ошибка загрузки в GitHub для {filename}: {str(e)}")
        raise

def main():
    games = [
        {"name": "poe", "league_name": "Settlers of Kalguur", "league_id": "10480", "file_prefix": "poe_settlers_of_kalguur_2024-07"},
        {"name": "poe2", "league_name": "Dawn of the Hunt", "league_id": "11287", "file_prefix": "poe2_dawn_of_the_hunt_2024-12"}
    ]
    
    for game in games:
        logger.info(f"Обработка игры: {game['name']}")
        print(f"Обработка игры: {game['name']}")
        sellers = get_sellers(game["name"], game["league_id"])
        filename = f"prices_{game['file_prefix']}.json"
        logger.debug(f"Перед сохранением {filename}: {sellers}")
        if not sellers:
            logger.warning(f"Нет данных для сохранения в {filename}")
            print(f"Нет данных для {filename}")
            continue
        save_to_json(sellers, filename)
        print(f"Сохранено в {filename}")
        upload_to_github(sellers, filename, "smokerdl/divine_orbs_prices", os.getenv("GITHUB_TOKEN"))
        
        leagues = get_leagues(game["name"])
        if leagues:
            save_to_json(leagues, f"league_ids.json")
            print(f"Сохранено в league_ids.json")
            upload_to_github(leagues, f"league_ids.json", "smokerdl/divine_orbs_prices", os.getenv("GITHUB_TOKEN"))

if __name__ == "__main__":
    main()

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
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
        logging.StreamHandler()  # Исправлено: loggingStreamHandler -> StreamHandler
    ]
)
logger = logging.getLogger(__name__)

# Константы
POE_URL = "https://funpay.com/chips/173/"  # PoE 1 Divine Orbs
POE2_URL = "https://funpay.com/chips/209/"  # PoE 2 Divine Orbs
log_dir = os.path.dirname(os.path.abspath(__file__))
ua = UserAgent()
headers = {
    "User-Agent": ua.random,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",  # Для цен в RUB
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}
FUNPAY_EXCHANGE_RATE = 79.89
SBP_COMMISSION = 1.2118
CARD_COMMISSION = 1.2526

# Получение продавцов
def get_sellers(game, league_id):
    logger.info(f"Сбор данных о продавцах для {game} (лига {league_id})...")
    url = POE_URL if game == 'poe' else POE2_URL
    session = requests.Session()
    session.headers.update(headers)
    session.cookies.update({
        f'sc-filters-section-chip-{173 if game == "poe" else 209}': '{"online": "1"}'
    })
    
    offers = []
    page_num = 1
    max_pages = 2  # Ограничение для надежности
    while len(offers) < 8 and page_num <= max_pages:
        for attempt in range(3):
            try:
                page_url = f"{url}?page={page_num}"
                response = session.get(page_url, timeout=15)
                logger.info(f"Статус ответа FunPay для {game} (лига {league_id}, страница {page_num}): {response.status_code}")
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                with open(os.path.join(log_dir, f'funpay_sellers_{game}_page{page_num}.html'), 'w', encoding='utf-8') as f:
                    f.write(soup.prettify())
                logger.info(f"HTML продавцов для {game} (страница {page_num}) сохранён")
                
                page_offers = soup.find_all("a", class_="tc-item")
                logger.info(f"Найдено продавцов для {game} (лига {league_id}, страница {page_num}): {len(page_offers)}")
                if not page_offers:
                    logger.warning(f"Селектор a.tc-item с data-server={league_id} не нашёл продавцов на странице {page_num}")
                    break
                
                offers.extend(page_offers)
                next_page = soup.find("a", class_="pagination-next")
                if not next_page:
                    logger.info(f"Пагинация завершена для {game} на странице {page_num}")
                    break
                page_num += 1
                break
            except requests.exceptions.RequestException as e:
                logger.error(f"Попытка {attempt + 1} не удалась для {page_url}: {e}")
                if attempt == 2:
                    logger.error(f"Все попытки исчерпаны для {game} (лига {league_id}, страница {page_num})")
                    return []
                time.sleep(2)
        if not page_offers or not next_page:
            break
    
    valid_offers = []
    debug_count = 0
    
    for index, offer in enumerate(offers, 1):
        try:
            if str(offer.get("data-server")) != str(league_id):
                logger.debug(f"Пропущен оффер {index}: data-server не {league_id}")
                continue
            
            username_elem = offer.find("div", class_="media-user-name")
            username = username_elem.text.strip() if username_elem else None
            if not username:
                logger.debug(f"Пропущен оффер {index}: нет имени пользователя")
                continue
            
            orb_type = "Божественные сферы" if game == 'poe' else "Неизвестно"
            desc_elem = offer.find("div", class_="tc-desc")
            desc_text = desc_elem.text.strip().lower() if desc_elem else ""
            side_elem = offer.find("div", class_="tc-side") or offer.find("div", class_="tc-side-inside")
            side_text = side_elem.text.strip().lower() if side_elem else ""
            logger.debug(f"tc-desc для {username}: {desc_text}")
            logger.debug(f"tc-side для {username}: {side_text}")
            
            divine_keywords = [
                r"divine\s*orb", r"божественн[а-я]*\s*сфер[а-я]*", r"div\s*orb"
            ]
            has_divine = any(
                re.search(keyword, desc_text, re.IGNORECASE) or re.search(keyword, side_text, re.IGNORECASE)
                for keyword in divine_keywords
            )
            exclude_keywords = [
                "хаос", "ваал", "exalted", "chaos", "vaal", "exalt", "regal", "alch", 
                "blessed", "chromatic", "jeweller", "fusing", "scour", "chance", 
                "аккаунт", "услуги", "account", "service", "gem", "map", "fragment"
            ]
            has_exclude = any(keyword in desc_text or keyword in side_text for keyword in exclude_keywords)
            
            amount_elem = offer.find("div", class_="tc-amount")
            amount = re.sub(r"[^\d]", "", amount_elem.text.strip()) if amount_elem else "0"
            amount_num = int(amount) if amount.isdigit() else 0
            logger.debug(f"Сток для {username}: {amount}")
            
            if not has_divine and (desc_text or side_text):
                logger.debug(f"Пропущен оффер для {username}: нет Divine Orbs в описании")
                continue
            if has_exclude:
                logger.debug(f"Пропущен оффер для {username}: содержит нежелательные ключевые слова")
                continue
            orb_type = "Божественные сферы"
            
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
            
            if '₽' in price_text:
                price_text_clean = re.sub(r'[^\d,.]', '', price_text).replace(',', '.')
                price_rub = float(price_text_clean)
                price_usd = round(price_rub / FUNPAY_EXCHANGE_RATE, 3)
            else:
                price_text_clean = re.sub(r"[^\d.]", "", price_text).strip()
                price_usd = float(price_text_clean)
                price_rub = round(price_usd * FUNPAY_EXCHANGE_RATE, 2)
            
            if not re.match(r"^\d+(\.\d+)?$", str(price_usd)):
                logger.debug(f"Пропущен оффер для {username}: неверный формат цены ({price_text_clean})")
                continue
            
            price_sbp = round(price_rub * SBP_COMMISSION, 2)
            price_card = round(price_rub * CARD_COMMISSION, 2)
            logger.debug(f"Цена для {username}: {price_usd} USD ({price_rub} RUB, СБП: {price_sbp} ₽, Карта: {price_card} ₽)")
            
            valid_offers.append({
                "Timestamp": datetime.now(pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S"),
                "Seller": username,
                "Stock": amount_num,
                "Price": price_usd,
                "Price_rub": price_rub,
                "Currency": "USD",
                "Position": index,
                "DisplayPosition": 0,
                "Online": True
            })
            
            if debug_count < 10:
                logger.debug(f"Отладка оффера {index}: {username}, Цена: {price_usd} USD ({price_rub} RUB), tc-desc: {desc_text}, tc-side: {side_text}")
                debug_count += 1
        
        except Exception as e:
            logger.debug(f"Ошибка обработки оффера {index}: {e}")
            continue
    
    logger.info(f"Найдено валидных офферов для {game}: {len(valid_offers)}")
    
    valid_offers.sort(key=lambda x: x["Price"])
    sellers = []
    start_position = 4 if len(valid_offers) >= 8 else 1
    end_position = min(len(valid_offers), 8 if len(valid_offers) >= 8 else len(valid_offers))
    for i, offer in enumerate(valid_offers, 1):
        if start_position <= i <= end_position:
            offer["DisplayPosition"] = i - start_position + 1
            sellers.append(offer)
    
    logger.info(f"Собрано продавцов для {game}: {len(sellers)} (позиции {start_position}–{end_position})")
    logger.debug(f"Содержимое sellers: {sellers}")
    return sellers

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
                f.write(soup.pretty_print())
            logger.info(f"HTML лиг для {game} сохранён")
            
            league_select = soup.find("select", class_="form-control")
            leagues = []
            if league_select:
                options = league_select.find_all("option")
                logger.info(f"Найдено лиг для {game}: {len(options)}")
                for option in options:
                    league_id = option.get("value")
                    league_name = option.text.strip()
                    if league_id and league_name and not any(keyword in league_name.lower() for keyword in ["standard", "hardcore"]):
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
    logger.info(f"Попытка сохранить данные в {filename}: {len(data)} записей")
    try:
        existing_data = []
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                if not isinstance(existing_data, list):
                    existing_data = []
            except json.JSONDecodeError:
                logger.warning(f"Файл {filename} повреждён, создаём новый")
                existing_data = []
        
        existing_data.extend(data)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False)  # Без indent для экономии места
        logger.info(f"Данные успешно сохранены в {filename}: {len(existing_data)} записей")
        if os.path.getsize(filename) > 10 * 1024 * 1024:
            logger.warning(f"Размер файла {filename} превысил 10 Мб")
    except Exception as e:
        logger.error(f"Ошибка сохранения данных в {filename}: {e}")

# Обновление репозитория
def update_repository(filename, commit_message, github_token):
    logger.info(f"Обновление репозитория для {filename}")
    try:
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
    except Exception as e:
        logger.error(f"Ошибка обновления репозитория для {filename}: {e}")

# Основная функция
def main():
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("GITHUB_TOKEN не установлен")
        return
    
    games = [
        {"name": "poe", "default_league_id": "10480", "default_file": "prices_poe_settlers_of_kalguur_2024-07.json"},
        {"name": "poe2", "default_league_id": "11287", "default_file": "prices_poe2_dawn_of_the_hunt_2024-12.json"}
    ]
    
    for game in games:
        logger.info(f"Обработка игры: {game['name']}")
        current_leagues = get_leagues(game["name"])
        if not current_leagues:
            logger.warning(f"Не удалось получить лиги для {game['name']}, использую дефолтную лигу")
            league_id = game["default_league_id"]
            output_file = game["default_file"]
        else:
            default_league_id = game["default_league_id"]
            league = next((l for l in current_leagues if l["id"] == default_league_id), current_leagues[0])
            league_id = league["id"]
            league_name = re.sub(r'[^\w-]', '_', league["name"].lower())
            output_file = f"prices_{game['name']}_{league_name}_{datetime.now().strftime('%Y-%m')}.json"
            if league_id != default_league_id:
                old_file = game["default_file"]
                if os.path.exists(old_file):
                    os.rename(old_file, f"{old_file}.{datetime.now().strftime('%Y%m%d')}")
                    logger.info(f"Смена лиги для {game['name']}: архивирован {old_file}")
        
        sellers = get_sellers(game["name"], league_id)
        logger.info(f"Результат get_sellers для {game['name']}: {len(sellers)} продавцов")
        logger.debug(f"Содержимое sellers для {game['name']}: {sellers}")
        if sellers:
            output_file_path = os.path.join(log_dir, output_file)
            save_data(sellers, output_file_path)
            update_repository(output_file_path, f"Update {output_file}", github_token)
        else:
            logger.warning(f"Нет данных для сохранения для {game['name']}")
        
        if current_leagues:
            league_file = os.path.join(log_dir, "league_ids.json")
            save_data(current_leagues, league_file)
            update_repository(league_file, "Update league_ids.json", github_token)
        logger.info(f"Сохранено в {output_file}")
        logger.info(f"Сохранено в league_ids.json")

if __name__ == "__main__":
    main()

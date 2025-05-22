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
POE_URL = "https://funpay.com/chips/173/"  # PoE 1 Divine Orbs
POE2_URL = "https://funpay.com/chips/209/"  # PoE 2 Divine Orbs
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
    session.cookies.update({
        f'sc-filters-section-chip-{173 if game == "poe" else 209}': '{"online": "1"}'
    })
    
    offers = []
    page_num = 1
    while True:
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
                "divine", "божественные сферы", "divine orb", "божественная сфера", 
                "div orb", "divine orbs", "div orbs", "божеств сфера"
            ]
            has_divine = any(keyword in desc_text or keyword in side_text for keyword in divine_keywords)
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
            
            price_text_clean = re.sub(r"[^\d.]", "", price_text).strip()
            if not re.match(r"^\d+(\.\d+)?$", price_text_clean):
                logger.debug(f"Пропущен оффер для {username}: неверный формат цены ({price_text_clean})")
                continue
            try:
                price_usd = float(price_text_clean)
                logger.debug(f"Цена для {username}: {price_usd} USD")
            except ValueError:
                logger.debug(f"Пропущен оффер для {username}: ошибка преобразования цены ({price_text_clean})")
                continue
            
            valid_offers.append({
                "Timestamp": datetime.now(pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S"),
                "Seller": username,
                "Stock": amount,
                "Price": price_usd,
                "Currency": "USD",
                "Position": index,
                "DisplayPosition": 0,
                "Online": True,
                "League": league_id
            })
            
            if debug_count < 10:
                logger.debug(f"Отладка оффера {index}: {username}, Цена: {price_usd} USD, tc-desc: {desc_text}, tc-side: {side_text}")
                debug_count += 1
        
        except Exception as e:
            logger.debug(f"Ошибка обработки оффера {index}: {e}")
            continue
    
    logger.info(f"Найдено валидных офферов для {game}: {len(valid_offers)}")
    
    valid_offers.sort(key=lambda x: x["Price"])
    sellers = []
    for i, offer in enumerate(valid_offers, 1):
        if 4 <= i <= 8:
            offer["DisplayPosition"] = i
            sellers.append(offer)
    
    logger.info(f"Собрано продавцов для {game}: {len(sellers)} (позиции 4–8)")
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
            
            logger.info(f"Данные лиг для {game}: {leagues}")
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
            json.dump(existing_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Данные успешно сохранены в {filename}: {len(existing_data)} записей")
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
        {"name": "poe", "default_league_id": "10480", "default_output_file": "prices_poe_settlers_of_kalguur_2024-07.json"},
        {"name": "poe2", "default_league_id": "11287", "default_output_file": "prices_poe2_dawn_of_the_hunt_2024-12.json"}
    ]
    
    for game in games:
        logger.info(f"Обработка игры: {game['name']}")
        
        # Получение актуальных лиг
        leagues = get_leagues(game["name"])
        if not leagues:
            logger.warning(f"Не удалось получить лиги для {game['name']}, используем дефолтную лигу {game['default_league_id']}")
            league_id = game["default_league_id"]
            output_file = game["default_output_file"]
            league_name = output_file.split('_')[2].replace('.json', '')
        else:
            # Проверяем, есть ли дефолтная лига в списке
            current_league = next((l for l in leagues if l["id"] == game["default_league_id"]), None)
            if not current_league:
                logger.warning(f"Лига {game['default_league_id']} не найдена для {game['name']}, архивируем старый JSON")
                # Архивируем старый JSON
                old_file = os.path.join(log_dir, game["default_output_file"])
                if os.path.exists(old_file):
                    archive_file = old_file.replace('.json', '_archive.json')
                    os.rename(old_file, archive_file)
                    update_repository(archive_file, f"Archive {game['default_output_file']}", github_token)
                    logger.info(f"Старый JSON архивирован: {archive_file}")
                
                # Выбираем первую доступную лигу
                current_league = leagues[0]
                league_id = current_league["id"]
                league_name = current_league["name"].lower().replace(' ', '_')
                output_file = os.path.join(log_dir, f"prices_{game['name']}_{league_name}_{datetime.now().strftime('%Y-%m')}.json")
            else:
                league_id = current_league["id"]
                league_name = current_league["name"].lower().replace(' ', '_')
                output_file = game["default_output_file"]
        
        sellers = get_sellers(game["name"], league_id)
        logger.info(f"Результат get_sellers для {game['name']}: {len(sellers)} продавцов")
        logger.debug(f"Содержимое sellers для {game['name']}: {sellers}")
        if sellers:
            output_file = os.path.join(log_dir, output_file)
            save_data(sellers, output_file)
            update_repository(output_file, f"Update {os.path.basename(output_file)}", github_token)
        else:
            logger.warning(f"Нет данных для сохранения для {game['name']}")
        
        if leagues:
            league_file = os.path.join(log_dir, "league_ids.json")
            save_data(leagues, league_file)
            update_repository(league_file, "Update league_ids.json", github_token)
        logger.info(f"Сохранено в {output_file}")
        logger.info(f"Сохранено в league_ids.json")

if __name__ == "__main__":
    main()

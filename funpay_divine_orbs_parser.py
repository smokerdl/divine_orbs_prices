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
POE_URL = "https://funpay.com/chips/173/"
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

def filter_relevant_leagues(leagues, game):
    """Фильтрация лиг по актуальности и платформе"""
    filtered = []
    
    for league in leagues:
        league_name = league["name"].lower()
        league_id = league["id"]
        
        # Исключаем лиги по ключевым словам
        exclude_keywords = [
            "hardcore", "ruthless", "hc", "standard", 
            "ps", "xbox", "playstation", "лига", "private", "pl"
        ]
        if any(keyword in league_name for keyword in exclude_keywords):
            continue
            
        # Для PoE исключаем лиги PoE2 и лиги с префиксом PL
        if game == "poe" and (league_id.startswith("PL") or league_name == "dawn of the hunt"):
            continue
            
        filtered.append(league)
    
    # Сортируем по ID (новые лиги имеют большие ID)
    filtered.sort(key=lambda x: x["id"], reverse=True)
    
    return filtered

def get_leagues(game):
    """Получение и фильтрация лиг"""
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
            
            league_select = soup.find("select", class_="form-control")
            leagues = []
            if league_select:
                options = league_select.find_all("option")
                for option in options:
                    league_id = option.get("value")
                    league_name = option.text.strip()
                    if league_id and league_name:
                        leagues.append({"id": league_id, "name": league_name})
            
            logger.debug(f"Полный список лиг до фильтрации: {leagues}")
            filtered_leagues = filter_relevant_leagues(leagues, game)
            logger.info(f"Отфильтрованные лиги для {game}: {[l['name'] for l in filtered_leagues]}")
            
            return filtered_leagues if filtered_leagues else leagues[:1]
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Попытка {attempt + 1} не удалась: {e}")
            if attempt == 2:
                logger.error(f"Все попытки исчерпаны для лиг {game}")
                return []
            time.sleep(2)

def select_current_league(leagues, game):
    """Выбор текущей актуальной лиги"""
    if not leagues:
        return None
    
    last_league_file = os.path.join(log_dir, f"last_league_{game}.txt")
    previous_league_id = None
    if os.path.exists(last_league_file):
        with open(last_league_file, 'r', encoding='utf-8') as f:
            previous_league_id = f.read().strip()
    
    current_league = leagues[0]
    
    if previous_league_id != current_league["id"]:
        with open(last_league_file, 'w', encoding='utf-8') as f:
            f.write(current_league["id"])
        logger.info(f"Обновлена текущая лига для {game}: {current_league['name']} (ID: {current_league['id']})")
    
    return current_league

def archive_old_data(file_path, github_token):
    """Архивация старых данных"""
    if os.path.exists(file_path):
        archive_file = file_path.replace('.json', f'_archive_{datetime.now().strftime("%Y%m%d")}.json')
        os.rename(file_path, archive_file)
        if os.path.exists(file_path):
            os.remove(file_path)
        update_repository(archive_file, f"Archive {os.path.basename(archive_file)}", github_token)
        logger.info(f"Данные архивированы: {archive_file}")

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
            has_exclude = any(keyword in desc_text or side_text for keyword in exclude_keywords)
            
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

def save_data(data, output_file, overwrite=False):
    """Сохранение данных в JSON файл"""
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        existing_data = []
        
        if not overwrite and os.path.exists(output_file):
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                if not isinstance(existing_data, list):
                    logger.warning(f"Файл {output_file} содержит некорректные данные, создаём новый")
                    existing_data = []
            except json.JSONDecodeError:
                logger.warning(f"Файл {output_file} повреждён, создаём новый")
                existing_data = []
        
        if overwrite or not existing_data:
            existing_data = data
        else:
            existing_data.extend(data)
        
        # Удаляем дубликаты для league_ids
        if 'league_ids' in output_file:
            unique_leagues = {league['id']: league for league in existing_data}.values()
            existing_data = list(unique_leagues)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Данные сохранены в {output_file}: {len(existing_data)} записей")
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных в {output_file}: {e}")
        raise

def update_repository(file_path, commit_message, github_token):
    """Обновление файла в репозитории GitHub"""
    try:
        g = Github(github_token)
        repo = g.get_repo("smokerdl/divine_orbs_prices")
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        file_name = os.path.basename(file_path)
        try:
            contents = repo.get_contents(file_name)
            repo.update_file(file_name, commit_message, content, contents.sha)
            logger.info(f"Файл {file_name} обновлен в репозитории")
        except:
            repo.create_file(file_name, commit_message, content)
            logger.info(f"Файл {file_name} создан в репозитории")
    except Exception as e:
        logger.error(f"Ошибка при обновлении репозитория для {file_path}: {e}")
        raise

def main():
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("GITHUB_TOKEN не установлен")
        return
    
    games = [
        {
            "name": "poe",
            "default_league_id": "10480",
            "default_output_file": "prices_poe_settlers_of_kalguur_2024-07.json"
        },
        {
            "name": "poe2",
            "default_league_id": "11287",
            "default_output_file": "prices_poe2_dawn_of_the_hunt_2024-12.json"
        }
    ]
    
    for game in games:
        logger.info(f"Обработка игры: {game['name']}")
        
        leagues = get_leagues(game["name"])
        if not leagues:
            logger.warning(f"Не удалось получить лиги для {game['name']}, используем дефолтную лигу {game['default_league_id']}")
            league_id = game["default_league_id"]
            output_file = os.path.join(log_dir, game["default_output_file"])
            league_name = game["default_output_file"].split('_')[2].replace('.json', '')
        else:
            current_league = select_current_league(leagues, game["name"])
            if not current_league:
                logger.error(f"Не удалось выбрать лигу для {game['name']}")
                continue
                
            league_id = current_league["id"]
            last_output_file = os.path.join(log_dir, f"last_output_{game['name']}.txt")
            previous_output_file = None
            if os.path.exists(last_output_file):
                with open(last_output_file, 'r', encoding='utf-8') as f:
                    previous_output_file = f.read().strip()
            
            league_name = re.sub(r'\(pc\)\s*', '', current_league["name"], flags=re.IGNORECASE).lower().replace(' ', '_')
            output_file = os.path.join(log_dir, f"prices_{game['name']}_{league_name}_{datetime.now().strftime('%Y-%m')}.json")
            
            if previous_output_file and previous_output_file != output_file:
                archive_old_data(previous_output_file, github_token)
            
            with open(last_output_file, 'w', encoding='utf-8') as f:
                f.write(output_file)
        
        logger.info(f"Выбрано имя файла: {output_file}, лига: {league_name}, ID: {league_id}")
        
        sellers = get_sellers(game["name"], league_id)
        if sellers:
            save_data(sellers, output_file)
            update_repository(output_file, f"Update {os.path.basename(output_file)}", github_token)
        else:
            logger.warning(f"Нет данных для сохранения для {game['name']}")
        
        league_file = os.path.join(log_dir, f"league_ids_{game['name']}.json")
        save_data(leagues, league_file, overwrite=True)
        update_repository(league_file, f"Update league_ids_{game['name']}.json", github_token)
        logger.info(f"Сохранено в {league_file}")
        logger.info(f"Сохранено в {output_file}")

if __name__ == "__main__":
    main()

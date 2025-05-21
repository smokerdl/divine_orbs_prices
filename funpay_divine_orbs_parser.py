import os
import json
import logging
import requests
import pytz
import re
from datetime import datetime
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from github import Github, GithubException

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Константы
POE_URL = "https://funpay.com/chips/173/"
POE2_URL = "https://funpay.com/chips/209/"
RELEVANT_LEAGUES = {
    'poe': ['settlers_of_kalguur'],
    'poe2': ['dawn_of_the_hunt']
}
KNOWN_LEAGUE_DATES = {
    'settlers_of_kalguur': '2024-07',
    'dawn_of_the_hunt': '2024-12'
}
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
REPO_NAME = "smokerdl/divine_orbs_prices"
FALLBACK_USD_TO_RUB_RATE = 80.0

# Инициализация
ua = UserAgent()
headers = {
    "User-Agent": ua.random,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://funpay.com/",
    "Accept-Language": "ru-RU,ru;q=1.0",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

def get_exchange_rate():
    """Получить курс USD/RUB от ЦБ РФ."""
    logger.info("Получение курса USD/RUB от ЦБ РФ...")
    try:
        response = requests.get('https://www.cbr-xml-daily.ru/daily_json.js', headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        rate = data['Valute']['USD']['Value']
        logger.info(f"Курс USD/RUB: {rate}")
        return rate
    except Exception as e:
        logger.error(f"Ошибка получения курса: {e}")
        logger.info(f"Использую fallback-курс: {FALLBACK_USD_TO_RUB_RATE}")
        return FALLBACK_USD_TO_RUB_RATE

def get_leagues(game, url):
    """Получить список лиг с FunPay с фильтрацией."""
    logger.info(f"Получение списка лиг для {game}...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        logger.info(f"Статус ответа FunPay для {game}: {response.status_code}")
        if response.status_code != 200:
            logger.warning(f"Не удалось получить лиги для {game}")
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        with open(f'funpay_leagues_{game}.html', 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        logger.info(f"HTML страницы лиг для {game} сохранён")
        
        leagues = []
        select = soup.select_one('select[name="server"]')
        if not select:
            logger.warning(f"Не найден select[name='server'] для {game}")
            return []
        options = select.find_all('option')
        logger.debug(f"Найдено {len(options)} опций в select для {game}")
        for option in options:
            league_id = option.get('value', '')
            if not league_id:
                continue
            league_name_raw = option.text.strip()
            league_name = league_name_raw.replace(' ', '_').lower()
            logger.debug(f"Лига для {game}: raw='{league_name_raw}', normalized='{league_name}' (ID: {league_id})")
            if game == 'poe':
                if not ('pc' in league_name or '(pc)' in league_name):
                    logger.debug(f"Пропущена лига для {game}: {league_name} (нет PC)")
                    continue
            elif game == 'poe2':
                if '(pc)' in league_name or '(ps)' in league_name or '(xbox)' in league_name:
                    logger.debug(f"Пропущена лига для {game}: {league_name} (есть приставка)")
                    continue
            if any(x in league_name for x in ['"лига"', '"hardcore"', '"ruthless"', '"standart"', 'standard']):
                logger.debug(f"Пропущена лига для {game}: {league_name} (запрещённое название)")
                continue
            if re.search(r'\[(hardcore|ruthless|ruthless_hardcore)\]', league_name):
                logger.debug(f"Пропущена лига для {game}: {league_name} (есть запрещённое окончание)")
                continue
            for relevant_league in RELEVANT_LEAGUES[game]:
                if relevant_league in league_name:
                    logger.info(f"Найдена лига для {game}: {relevant_league} (ID: {league_id})")
                    leagues.append({'id': league_id, 'name': relevant_league})
                    break
            else:
                logger.debug(f"Пропущена лига для {game}: {league_name} (не в RELEVANT_LEAGUES)")
        if not leagues:
            logger.warning(f"Не найдено подходящих лиг для {game}")
        return leagues
    except Exception as e:
        logger.error(f"Ошибка получения лиг для {game}: {e}")
        return []

def get_sellers(game, league_id):
    """Получить данные о продавцах для лиги (с исправленной конвертацией для PoE 2)."""
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
                # Логирование классов для отладки
                tc_user = offer.find("div", class_="tc-user")
                avatar_photo = offer.find("div", class_="avatar-photo")
                logger.debug(f"Продавец на позиции {index}: tc-user: {tc_user.get('class', [])}, avatar: {avatar_photo.get('class', [])}")
                
                # Логирование Divine Orbs (PoE 2)
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
                    # Принудительная конвертация для PoE 2
                    if game == 'poe2' or "$" in price_elem.text:
                        logger.debug(f"Конверсия для {username}: {price} $ -> {price * exchange_rate} ₽")
                        price = price * exchange_rate
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
def save_data(game, league_name, start_date, data):
    """Сохранить данные в JSON."""
    try:
        filename = f"prices_{game}_{league_name}_{start_date}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Файл {filename} создан, записей: {len(data)}")
        
        # Коммит в GitHub
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        try:
            contents = repo.get_contents(filename)
            existing_data = json.loads(contents.decoded_content.decode()) if contents.decoded_content else []
            if not isinstance(existing_data, list):
                existing_data = []
            existing_data.extend(data)
            repo.update_file(
                contents.path,
                f"Update {filename}",
                json.dumps(existing_data, ensure_ascii=False, indent=2),
                contents.sha
            )
        except GithubException as e:
            if e.status == 404:
                repo.create_file(
                    filename,
                    f"Create {filename}",
                    json.dumps(data, ensure_ascii=False, indent=2)
                )
            else:
                raise e
    except Exception as e:
        logger.error(f"Ошибка сохранения данных для {game} (лига: {league_name}): {e}")

def update_current_leagues(current_leagues):
    """Обновить current_leagues.json."""
    try:
        filename = 'current_leagues.json'
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(current_leagues, f, ensure_ascii=False, indent=2)
        logger.info("Файл current_leagues.json обновлён")
        
        # Коммит в GitHub
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        try:
            contents = repo.get_contents(filename)
            repo.update_file(
                contents.path,
                "Update current_leagues.json",
                json.dumps(current_leagues, ensure_ascii=False, indent=2),
                contents.sha
            )
        except GithubException as e:
            if e.status == 404:
                repo.create_file(
                    filename,
                    "Create current_leagues.json",
                    json.dumps(current_leagues, ensure_ascii=False, indent=2)
                )
            else:
                raise e
    except Exception as e:
        logger.error(f"Ошибка обновления current_leagues.json: {e}")

def main():
    logger.info("Парсер запущен")
    
    # Текущие лиги
    current_leagues = {'poe': [], 'poe2': []}
    
    # Обработка PoE
    logger.info("Получение списка лиг для poe...")
    poe_leagues = get_leagues('poe', POE_URL)
    for league in poe_leagues:
        league_name = league['name']
        start_date = KNOWN_LEAGUE_DATES.get(league_name, '2024-07')
        league_data = get_sellers('poe', league['id'])
        if league_data:
            save_data('poe', league_name, start_date, league_data)
            current_leagues['poe'].append(league_name)
    
    # Обработка PoE 2
    logger.info("Получение списка лиг для poe2...")
    poe2_leagues = get_leagues('poe2', POE2_URL)
    for league in poe2_leagues:
        league_name = league['name']
        start_date = KNOWN_LEAGUE_DATES.get(league_name, '2024-12')
        league_data = get_sellers('poe2', league['id'])
        if league_data:
            save_data('poe2', league_name, start_date, league_data)
            current_leagues['poe2'].append(league_name)
    
    # Обновить current_leagues.json
    update_current_leagues(current_leagues)
    
    logger.info(f"Завершено: {datetime.now(pytz.timezone('Europe/Moscow')).isoformat()}")

if __name__ == "__main__":
    main()

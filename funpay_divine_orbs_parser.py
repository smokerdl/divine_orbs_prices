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

import logging
import requests
from bs4 import BeautifulSoup
import json
import datetime
import re

# Настройка логов
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_sellers(html_content, league_name, currency_type, usd_rub_rate):
    """
    Парсит данные о продавцах из HTML FunPay для указанной лиги и валюты.
    
    Args:
        html_content (str): HTML-код страницы с продавцами.
        league_name (str): Название лиги (например, "Dawn of the Hunt").
        currency_type (str): Тип валюты (например, "Божественные сферы").
        usd_rub_rate (float): Курс USD к RUB.
    
    Returns:
        list: Список словарей с данными продавцов.
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        sellers = []
        position = 1

        # Находим строки таблицы с данными продавцов
        rows = soup.select('div.tc-item')
        if not rows:
            logging.warning("Не найдено строк с продавцами в HTML.")
            return []

        for row in rows:
            # Извлекаем лигу
            league = row.select_one('div.tc-league')
            if not league or league.text.strip() != league_name:
                continue

            # Извлекаем тип валюты
            currency = row.select_one('div.tc-desc')
            if not currency or currency.text.strip() != currency_type:
                continue

            # Извлекаем имя продавца
            seller = row.select_one('div.tc-user')
            seller_name = seller.text.strip() if seller else ""

            # Извлекаем сток
            stock = row.select_one('div.tc-amount')
            stock_value = stock.text.strip().replace(' ', '') if stock else "0"
            stock_value = re.sub(r'[^\d]', '', stock_value)  # Удаляем не-цифры
            stock_value = int(stock_value) if stock_value.isdigit() else 0

            # Извлекаем цену (в рублях)
            price = row.select_one('div.tc-price div.media')
            price_value = price.text.strip() if price else "0"
            price_value = re.sub(r'[^\d.]', '', price_value)  # Оставляем цифры и точку
            try:
                price_rub = float(price_value)
                logging.info(f"Найдена цена для {seller_name}: {price_rub} ₽")
            except ValueError:
                logging.warning(f"Неверный формат цены для продавца {seller_name}: {price_value}")
                price_rub = 0.0

            # Конвертируем цену в доллары
            price_usd = round(price_rub / usd_rub_rate, 2) if price_rub > 0 else 0.0

            # Добавляем данные продавца
            sellers.append({
                "Timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Seller": seller_name,
                "Stock": str(stock_value),
                "Price": price_usd,
                "Position": position
            })
            position += 1

        # Фильтруем топ-10 продавцов (позиции 4–13)
        filtered_sellers = [s for s in sellers if 4 <= s["Position"] <= 13]
        logging.info(f"Отфильтровано продавцов для {currency_type}: {len(filtered_sellers)} (позиции 4–13)")
        return filtered_sellers

    except Exception as e:
        logging.error(f"Ошибка в get_sellers: {str(e)}")
        return []

def get_leagues(html_content, game):
    """Парсит доступные лиги из HTML FunPay."""
    soup = BeautifulSoup(html_content, 'html.parser')
    leagues = {}
    for link in soup.select('a[href*="/lots/"]'):
        href = link.get('href')
        if '/lots/' in href:
            league_id = href.split('/')[-2]
            league_name = link.text.strip().lower().replace(' ', '_')
            leagues[league_name] = league_id
    return leagues

def main():
    games = {
        'poe': 'https://funpay.com/chips/104/',
        'poe2': 'https://funpay.com/chips/209/'
    }
    currency_type = "Божественные сферы"  # Изменено на Божественные сферы
    usd_rub_rate = 80.3075  # Курс из твоего лога

    for game, url in games.items():
        logging.info(f"Получение списка лиг для {game}...")
        response = requests.get(url)
        if response.status_code != 200:
            logging.error(f"Ошибка при получении лиг для {game}: {response.status_code}")
            continue

        logging.info(f"Статус ответа FunPay для {game}: {response.status_code}")
        with open(f'leagues_{game}.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        logging.info(f"HTML страницы лиг для {game} сохранён")

        leagues = get_leagues(response.text, game)
        target_league = 'settlers_of_kalguur' if game == 'poe' else 'dawn_of_the_hunt'
        league_id = leagues.get(target_league)

        if not league_id:
            logging.error(f"Лига {target_league} не найдена для {game}")
            continue

        logging.info(f"Найдена лига для {game}: {target_league} (ID: {league_id})")
        logging.info(f"Сбор данных о продавцах для {game} (лига {league_id})...")

        sellers_url = f"https://funpay.com/chips/{league_id}/"
        response = requests.get(sellers_url)
        if response.status_code != 200:
            logging.error(f"Ошибка при получении продавцов для {game}: {response.status_code}")
            continue

        logging.info(f"Статус ответа FunPay для {game} (лига {league_id}): {response.status_code}")
        with open(f'sellers_{game}.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        logging.info(f"HTML продавцов для {game} сохранён")

        sellers = get_sellers(response.text, target_league.replace('_', ' ').title(), currency_type, usd_rub_rate)
        logging.info(f"Найдено продавцов для {game} (лига {league_id}): {len(sellers)}")

        # Сохраняем отфильтрованных продавцов в JSON
        output_file = f"prices_{game}_{target_league}_{datetime.datetime.now().strftime('%Y-%m')}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(sellers, f, ensure_ascii=False, indent=2)
        logging.info(f"Файл {output_file} создан, записей: {len(sellers)}")

    # Обновляем current_leagues.json
    with open('current_leagues.json', 'w', encoding='utf-8') as f:
        json.dump({'poe': 'settlers_of_kalguur', 'poe2': 'dawn_of_the_hunt'}, f, ensure_ascii=False, indent=2)
    logging.info("Файл current_leagues.json обновлён")

    logging.info(f"Завершено: {datetime.datetime.now().isoformat()}")

if __name__ == "__main__":
    main()
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

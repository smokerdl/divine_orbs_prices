import os
import json
import logging
import requests
import pytz
import re
from datetime import datetime
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from github import Github

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
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

# Инициализация
ua = UserAgent()
headers = {'User-Agent': ua.random}

def get_exchange_rate():
    """Получить курс USD/RUB от ЦБ РФ."""
    try:
        response = requests.get('https://www.cbr-xml-daily.ru/daily_json.js', headers=headers)
        response.raise_for_status()
        data = response.json()
        rate = data['Valute']['USD']['Value']
        logger.info(f"Курс USD/RUB: {rate}")
        return rate
    except Exception as e:
        logger.error(f"Ошибка получения курса: {e}")
        return 90.0  # Запасной курс

def get_leagues(game, url):
    """Получить список лиг с FunPay с фильтрацией."""
    try:
        response = requests.get(url, headers=headers)
        logger.info(f"Статус ответа FunPay для {game}: {response.status_code}")
        if response.status_code != 200:
            logger.warning(f"Не удалось получить лиги для {game}")
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        with open(f'funpay_leagues_{game}.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
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
    """Получить данные о продавцах для лиги."""
    try:
        base_url = POE_URL if game == 'poe' else POE2_URL
        url = f"{base_url}?server={league_id}"
        response = requests.get(url, headers=headers)
        logger.info(f"Статус ответа FunPay для {game} (лига {league_id}): {response.status_code}")
        if response.status_code != 200:
            logger.warning(f"Не удалось получить продавцов для {game} (лига {league_id})")
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        with open(f'funpay_sellers_{game}.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        logger.info(f"HTML продавцов для {game} сохранён")
        sellers = []
        offers = soup.select('.tc-item')
        if not offers:
            logger.warning(f"Не найдено элементов .tc-item для {game} (лига {league_id})")
            container = soup.select_one('.showcase') or soup.select_one('.content')
            if container:
                logger.debug(f"Найден контейнер для {game}: {str(container)[:500]}...")
            return []
        for offer in offers:
            username_elem = offer.select_one('.tc-user .media-user-name span')
            price_elem = offer.select_one('.tc-price > div')
            amount_elem = offer.select_one('.tc-amount')
            if not (username_elem and price_elem and amount_elem):
                logger.debug(f"Пропущен оффер для {game}: отсутствует имя, цена или количество")
                continue
            username = username_elem.text.strip()
            price_rub = float(price_elem.text.split()[0].replace(',', '.'))
            amount = int(amount_elem.get('data-s', '0'))
            if amount == 0:
                logger.debug(f"Пропущен оффер для {game}: количество = 0 (продавец: {username})")
                continue
            sellers.append({
                'username': username,
                'price_rub': price_rub,
                'amount': amount
            })
        logger.info(f"Найдено продавцов для {game} (лига {league_id}): {len(sellers)}")
        return sellers
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
            repo.update_file(contents.path, f"Update {filename}", json.dumps(data, ensure_ascii=False, indent=2), contents.sha)
        except:
            repo.create_file(filename, f"Create {filename}", json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"Ошибка сохранения данных для {game} (лига: {league_name}): {e}")

def update_current_leagues(current_leagues):
    """Обновить current_leagues.json."""
    try:
        if not os.path.exists('current_leagues.json'):
            logger.warning("Файл current_leagues.json не найден, создаю новый")
            with open('current_leagues.json', 'w', encoding='utf-8') as f:
                json.dump({'poe': [], 'poe2': []}, f, ensure_ascii=False, indent=2)
        
        with open('current_leagues.json', 'w', encoding='utf-8') as f:
            json.dump(current_leagues, f, ensure_ascii=False, indent=2)
        logger.info("Файл current_leagues.json обновлён")
        
        # Коммит в GitHub
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        try:
            contents = repo.get_contents('current_leagues.json')
            repo.update_file(contents.path, "Update current_leagues.json", json.dumps(current_leagues, ensure_ascii=False, indent=2), contents.sha)
        except:
            repo.create_file('current_leagues.json', "Create current_leagues.json", json.dumps(current_leagues, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"Ошибка обновления current_leagues.json: {e}")

def process_league(game, league_id, league_name, start_date, exchange_rate):
    """Обработать лигу."""
    logger.info(f"Обработка {game}: лига {league_name} (ID: {league_id}), дата: {start_date}")
    sellers = get_sellers(game, league_id)
    if not sellers:
        logger.warning(f"Нет продавцов для {game} (лига {league_id})")
        save_data(game, league_name, start_date, [])
        return []

    # Конверсия цен
    data = []
    prices_rub = []
    for seller in sellers:
        price_rub = seller['price_rub']
        price_usd = price_rub / exchange_rate
        prices_rub.append(price_rub)
        logger.debug(f"Конверсия для {seller['username']}: {price_rub} ₽ -> {price_usd:.4f} $")
        data.append({
            'username': seller['username'],
            'price_usd': price_usd,
            'price_rub': price_rub,
            'amount': seller['amount'],
            'timestamp': datetime.now(pytz.timezone('Europe/Moscow')).isoformat()
        })

    # Итоговая статистика
    if prices_rub:
        min_price_rub, max_price_rub = min(prices_rub), max(prices_rub)
        min_price_usd = min_price_rub / exchange_rate
        max_price_usd = max_price_rub / exchange_rate
        logger.info(f"Лига {league_name}: {len(sellers)} продавцов, цены от {min_price_rub:.2f} ₽ ({min_price_usd:.4f} $) до {max_price_rub:.2f} ₽ ({max_price_usd:.4f} $)")

    # Фильтрация продавцов (позиции 4–13)
    filtered_data = data[3:13] if len(data) > 3 else data
    logger.info(f"Отфильтровано продавцов для {game}: {len(filtered_data)} (позиции 4–13)")
    
    save_data(game, league_name, start_date, filtered_data)
    return filtered_data

def main():
    logger.info("Парсер запущен")
    
    # Получить курс один раз
    exchange_rate = get_exchange_rate()
    
    # Текущие лиги
    current_leagues = {'poe': [], 'poe2': []}
    
    # Обработка PoE
    logger.info("Получение списка лиг для poe...")
    poe_leagues = get_leagues('poe', POE_URL)
    for league in poe_leagues:
        league_name = league['name']
        start_date = KNOWN_LEAGUE_DATES.get(league_name, '2024-07')
        league_data = process_league('poe', league['id'], league_name, start_date, exchange_rate)
        if league_data:
            current_leagues['poe'].append(league_name)
    
    # Обработка PoE 2
    logger.info("Получение списка лиг для poe2...")
    poe2_leagues = get_leagues('poe2', POE2_URL)
    for league in poe2_leagues:
        league_name = league['name']
        start_date = KNOWN_LEAGUE_DATES.get(league_name, '2024-12')
        league_data = process_league('poe2', league['id'], league_name, start_date, exchange_rate)
        if league_data:
            current_leagues['poe2'].append(league_name)
    
    # Обновить current_leagues.json
    update_current_leagues(current_leagues)
    
    logger.info(f"Завершено: {datetime.now(pytz.timezone('Europe/Moscow')).isoformat()}")

if __name__ == "__main__":
    main()

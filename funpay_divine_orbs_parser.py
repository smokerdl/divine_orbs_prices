import logging
import requests
from bs4 import BeautifulSoup
import json
import re
import datetime
import pytz

# Настройка логов
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_leagues(html_content, game):
    """Парсит доступные лиги из HTML FunPay."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        leagues = {}
        for link in soup.select('a[href*="/lots/"]'):
            href = link.get('href')
            if '/lots/' in href:
                league_id = href.split('/')[-2]
                league_name = link.text.strip().lower().replace(' ', '_')
                leagues[league_name] = league_id
                logger.info(f"Найдена лига: {league_name} (ID: {league_id})")
        if not leagues:
            logger.warning(f"Лиги не найдены для {game}")
        return leagues
    except Exception as e:
        logger.error(f"Ошибка в get_leagues для {game}: {str(e)}")
        return {}

def get_sellers(html_content, league_name, usd_rub_rate):
    """
    Парсит данные о продавцах Божественных сфер из HTML FunPay для указанной лиги.
    
    Args:
        html_content (str): HTML-код страницы с продавцами.
        league_name (str): Название лиги (например, "Dawn of the Hunt").
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
            logger.warning("Не найдено строк с продавцами в HTML.")
            return []

        for row in rows:
            # Извлекаем лигу
            league = row.select_one('div.tc-league')
            if not league or league.text.strip() != league_name:
                continue

            # Проверяем, что это Божественные сферы
            currency = row.select_one('div.tc-desc')
            if not currency or currency.text.strip() != "Божественные сферы":
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
                logger.info(f"Найдена цена для {seller_name}: {price_rub} ₽")
            except ValueError:
                logger.warning(f"Неверный формат цены для продавца {seller_name}: {price_value}")
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
        logger.info(f"Отфильтровано продавцов для Божественных сфер: {len(filtered_sellers)} (позиции 4–13)")
        return filtered_sellers
    except Exception as e:
        logger.error(f"Ошибка в get_sellers: {str(e)}")
        return []

def main():
    games = {
        'poe': 'https://funpay.com/chips/104/',
        'poe2': 'https://funpay.com/chips/209/'
    }
    usd_rub_rate = 80.3075  # Курс из лога

    for game, url in games.items():
        logger.info(f"Получение списка лиг для {game}...")
        response = requests.get(url)
        if response.status_code != 200:
            logger.error(f"Ошибка при получении лиг для {game}: {response.status_code}")
            continue

        logger.info(f"Статус ответа FunPay для {game}: {response.status_code}")
        with open(f'leagues_{game}.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        logger.info(f"HTML страницы лиг для {game} сохранён")

        leagues = get_leagues(response.text, game)
        target_league = 'settlers_of_kalguur' if game == 'poe' else 'dawn_of_the_hunt'
        league_id = leagues.get(target_league)

        if not league_id:
            logger.error(f"Лига {target_league} не найдена для {game}")
            continue

        logger.info(f"Найдена лига для {game}: {target_league} (ID: {league_id})")
        logger.info(f"Сбор данных о продавцах для {game} (лига {league_id})...")

        sellers_url = f"https://funpay.com/chips/{league_id}/"
        response = requests.get(sellers_url)
        if response.status_code != 200:
            logger.error(f"Ошибка при получении продавцов для {game}: {response.status_code}")
            continue

        logger.info(f"Статус ответа FunPay для {game} (лига {league_id}): {response.status_code}")
        with open(f'sellers_{game}.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        logger.info(f"HTML продавцов для {game} сохранён")

        sellers = get_sellers(response.text, target_league.replace('_', ' ').title(), usd_rub_rate)
        logger.info(f"Найдено продавцов для {game} (лига {league_id}): {len(sellers)}")

        # Сохраняем отфильтрованных продавцов в JSON
        output_file = f"prices_{game}_{target_league}_{datetime.datetime.now().strftime('%Y-%m')}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(sellers, f, ensure_ascii=False, indent=2)
        logger.info(f"Файл {output_file} создан, записей: {len(sellers)}")

    # Обновляем current_leagues.json
    with open('current_leagues.json', 'w', encoding='utf-8') as f:
        json.dump({'poe': 'settlers_of_kalguur', 'poe2': 'dawn_of_the_hunt'}, f, ensure_ascii=False, indent=2)
    logger.info("Файл current_leagues.json обновлён")

    # Исправленный вызов datetime.now
    moscow_tz = pytz.timezone('Europe/Moscow')
    logger.info(f"Завершено: {datetime.datetime.now(moscow_tz).isoformat()}")

if __name__ == "__main__":
    logger.info("Парсер запущен")
    main()

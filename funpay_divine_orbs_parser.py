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
logging.basicConfig(
    filename="0_parse.txt",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

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

def get_exchange_rate():
    logger.info("Получение курса USD/RUB от ЦБ РФ...")
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        rate = data["Valute"]["USD"]["Value"]
        logger.info(f"Курс USD/RUB: {rate}")
        return rate
    except Exception as e:
        logger.error(f"Ошибка получения курса: {e}")
        return 80.0  # Fallback

def get_sellers(game, league_id):
    logger.info(f"Сбор данных о продавцах для {game} (лига {league_id})...")
    url = POE_URL if game == 'poe' else POE2_URL
    session = requests.Session()
    session.headers.update(headers)
    
    for attempt in range(3):
        try:
            response = session.get(url, timeout=15)
            logger.debug(f"Заголовки запроса: {response.request.headers}")
            logger.debug(f"Куки: {session.cookies.get_dict()}")
            logger.info(f"Статус ответа FunPay для {game} (лига {league_id}): {response.status_code}")
            if response.status_code == 404:
                logger.warning(f"Страница {url} не найдена (404)")
                with open(f'funpay_sellers_error_{game}.html', 'w', encoding='utf-8') as f:
                    f.write(response.text)
                continue
            
            response.raise_for_status()
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
                    username_elem = offer.find("div", class_="media-user-name")
                    username = username_elem.text.strip() if username_elem else None
                    if not username:
                        logger.debug(f"Пропущен оффер на позиции {index}: отсутствует имя")
                        continue
                    
                    # Поиск типа сферы
                    orb_type = "Божественные сферы" if game == 'poe' else "Неизвестно"
                    if game == 'poe2':
                        side_elem = offer.find("div", class_="tc-side")
                        if side_elem and side_elem.text.strip():
                            orb_type = side_elem.text.strip()
                            logger.debug(f"Найден tc-side для {username}: {orb_type}")
                        else:
                            side_inside_elem = offer.find("div", class_="tc-side-inside")
                            if side_inside_elem and side_inside_elem.text.strip():
                                orb_type = side_inside_elem.text.strip()
                                logger.debug(f"Найден tc-side-inside для {username}: {orb_type}")
                            elif offer.get("data-side") == "106":
                                orb_type = "Божественные сферы"
                                logger.debug(f"Найден data-side=106 для {username}, установлено: {orb_type}")
                        desc_elem = offer.find("div", class_="tc-desc")
                        logger.debug(f"tc-desc для {username}: {desc_elem.text.strip() if desc_elem else 'Пусто'}")
                    logger.debug(f"Тип сферы для {username} (позиция {index}): {orb_type}")
                    
                    if game == 'poe2' and orb_type != "Божественные сферы":
                        logger.debug(f"Пропущен оффер для {username}: тип сферы не Divine Orbs ({orb_type})")
                        continue
                    
                    amount_elem = offer.find("div", class_="tc-amount")
                    amount = re.sub(r"[^\d]", "", amount_elem.text.strip()) if amount_elem else "0"
                    
                    price_elem = offer.find("div", class_="tc-price")
                    if not price_elem:
                        logger.debug(f"Пропущен оффер на позиции {index}: отсутствует цена")
                        continue
                    price_inner = price_elem.find("div")
                    if not price_inner:
                        logger.debug(f"Пропущен оффер на позиции {index}: отсутствует div в tc-price")
                        continue
                    price_text = price_inner.text.strip()
                    logger.debug(f"Сырой текст цены для {username} (позиция {index}): {price_text}")
                    
                    price_span = price_inner.find("span", class_="unit")
                    if price_span:
                        price_text = price_text.replace(price_span.text, "").strip()
                    
                    price_text = price_text.replace(",", ".")
                    price_match = re.match(r"^\d*\.?\d+$", price_text)
                    if not price_match:
                        logger.debug(f"Пропущен оффер для {username}: неверный формат цены ({price_text})")
                        continue
                    try:
                        price = float(price_text)
                        logger.debug(f"Исходная цена для {username}: {price} {'$' if '$' in price_elem.text else '₽'}, за 1 сферу")
                        if price < 0.1 and "$" not in price_elem.text:
                            logger.warning(f"Аномально низкая цена для {username}: {price} ₽, пропускаем")
                            continue
                        if "$" in price_elem.text:
                            price = price * exchange_rate
                            logger.debug(f"Конверсия для {username}: {price / exchange_rate} $ -> {price} ₽")
                        price = round(price, 2)
                    except ValueError:
                        logger.debug(f"Пропущен оффер для {username}: не удалось преобразовать цену ({price_text})")
                        continue
                    
                    logger.debug(f"Обработан продавец: {username} (позиция {index}, {amount} шт., {price} ₽, тип: {orb_type})")
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
            
            # Фильтр позиций 4–13
            filtered_sellers = [s for s in sellers if 3 < s["Position"] <= 13]
            logger.info(f"Отфильтровано продавцов для {game}: {len(filtered_sellers)} (позиции 4–13)")
            
            # Фильтр цен для PoE 2
            if game == 'poe2' and filtered_sellers:
                valid_sellers = [s for s in filtered_sellers if s["Price"] < 1000]
                if not valid_sellers:
                    logger.warning("Нет валидных цен <1000 ₽, возвращаем пустой список")
                    filtered_sellers = []
                else:
                    min_price = min(s["Price"] for s in valid_sellers)
                    logger.info(f"Минимальная цена для PoE 2: {min_price} ₽")
                    filtered_sellers = [s for s in filtered_sellers if s["Price"] <= min_price * 2]
                    logger.info(f"После фильтра цен (<= {min_price * 2} ₽): {len(filtered_sellers)} продавцов")
            
            logger.debug(f"Возвращаем filtered_sellers для {game}: {filtered_sellers}")
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
        with open(f'funpay_leagues_{game}.html', 'w', encoding='utf-8') as f:
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
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"Данные успешно сохранены в {filename}: {data}")
    except Exception as e:
        logger.error(f"Ошибка сохранения в {filename}: {e}")
        raise

def upload_to_github(data, filename, repo_name, token):
    try:
        logger.debug(f"Попытка загрузки {filename} в GitHub: {data}")
        if not token:
            logger.error("GITHUB_TOKEN не задан")
            return
        g = Github(token)
        repo = g.get_repo(repo_name)
        content = json.dumps(data, ensure_ascii=False, indent=4)
        try:
            file = repo.get_contents(filename)
            repo.update_file(file.path, f"Update {filename}", content, file.sha)
            logger.info(f"Файл {filename} обновлён в репозитории")
        except Exception as e:
            if hasattr(e, 'response'):
                logger.error(f"GitHub API error: {e.response.status_code} - {e.response.text}")
            repo.create_file(filename, f"Create {filename}", content)
            logger.info(f"Файл {filename} создан в репозитории")
    except Exception as e:
        logger.error(f"Ошибка загрузки в GitHub для {filename}: {e}")
        if hasattr(e, 'response'):
            logger.error(f"GitHub API error: {e.response.status_code} - {e.response.text}")
        raise

def main():
    games = [
        {"name": "poe", "league_name": "Settlers of Kalguur", "league_id": "10480", "file_prefix": "poe_settlers_of_kalguur_2024-07"},
        {"name": "poe2", "league_name": "Dawn of the Hunt", "league_id": "11287", "file_prefix": "poe2_dawn_of_the_hunt_2024-12"}
    ]
    
    for game in games:
        sellers = get_sellers(game["name"], game["league_id"])
        filename = f"prices_{game['file_prefix']}.json"
        logger.debug(f"Перед сохранением {filename}: {sellers}")
        if not sellers:
            logger.warning(f"Нет данных для сохранения в {filename}")
            continue
        save_to_json(sellers, filename)
        # upload_to_github(sellers, filename, "smokerdl/divine_orbs_prices", os.getenv("GITHUB_TOKEN"))
        
        leagues = get_leagues(game["name"])
        if leagues:
            save_to_json(leagues, f"league_ids.json")
            # upload_to_github(leagues, f"league_ids.json", "smokerdl/divine_orbs_prices", os.getenv("GITHUB_TOKEN"))

if __name__ == "__main__":
    main()

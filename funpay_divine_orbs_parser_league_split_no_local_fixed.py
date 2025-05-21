import requests
from requests import Session
from bs4 import BeautifulSoup
import json
import time
import random
from datetime import datetime
from github import Github, GithubException
import os
import re
from fake_useragent import UserAgent
import logging
import pytz

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Словарь с играми и URL
GAMES = {
    "poe": {"url": "https://funpay.com/chips/173/", "league_prefix": "(PC)"},
    "poe2": {"url": "https://funpay.com/chips/209/", "league_prefix": ""}
}

# Словарь с известными датами лиг
KNOWN_LEAGUE_DATES = {
    "settlers_of_kalguur": "2024-07",
    "dawn_of_the_hunt": "2024-07"
}

# Fallback-курс
FALLBACK_USD_TO_RUB_RATE = 80.0

def get_usd_to_rub_rate():
    logging.info("Получение курса USD/RUB от ЦБ РФ...")
    try:
        response = requests.get("http://www.cbr-xml-daily.ru/daily_json.js", timeout=10)
        response.raise_for_status()
        data = response.json()
        rate = data["Valute"]["USD"]["Value"]
        logging.info(f"Курс USD/RUB: {rate}")
        return rate
    except Exception as e:
        logging.error(f"Ошибка получения курса USD/RUB: {str(e)}")
        logging.info(f"Использую fallback-курс: {FALLBACK_USD_TO_RUB_RATE}")
        return FALLBACK_USD_TO_RUB_RATE

def get_leagues(game, url, prefix):
    logging.info(f"Получение списка лиг для {game}...")
    headers = {
        "User-Agent": UserAgent().random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://funpay.com/",
        "Accept-Language": "ru-RU,ru;q=1.0",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    leagues = []
    with Session() as session:
        for attempt in range(3):
            try:
                response = session.get(url, headers=headers, timeout=10)
                logging.info(f"Статус ответа FunPay для {game}: {response.status_code}")
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                
                with open(f"funpay_leagues_{game}.html", "w", encoding="utf-8") as f:
                    f.write(soup.prettify())
                logging.info(f"HTML страницы лиг для {game} сохранён")
                
                select = soup.find("select", {"name": "server"})
                if not select:
                    logging.error(f"Не найден элемент <select name='server'> для {game}")
                    continue
                
                options = select.find_all("option")
                for option in options:
                    try:
                        league_id = option["value"]
                        league_text = option.text.strip()
                        # Очищаем название лиги от префикса
                        league_name = re.sub(r'^\(PC\)|\(PS\)|\(XBOX\)\s*', '', league_text).lower().replace(" ", "_")
                        if league_id and league_name:
                            leagues.append({"name": league_name, "id": league_id})
                            logging.info(f"Найдена лига для {game}: {league_name} (ID: {league_id})")
                    except Exception as e:
                        logging.error(f"Ошибка обработки опции лиги для {game}: {str(e)}")
                        continue
                
                if leagues:
                    return leagues
                logging.warning(f"Лиги для {game} не найдены")
                time.sleep(random.uniform(2, 5))
                continue
            except Exception as e:
                logging.error(f"Ошибка получения лиг для {game} (попытка {attempt + 1}): {str(e)}")
                time.sleep(random.uniform(2, 5))
                continue
    
    logging.error(f"Не удалось найти лиги для {game}, возвращаем пустой список")
    return []

def get_sellers_data(game, url, league_id):
    logging.info(f"Сбор данных о продавцах для {game} (лига ID: {league_id})...")
    all_offers = []
    headers = {
        "User-Agent": UserAgent().random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://funpay.com/",
        "Accept-Language": "ru-RU,ru;q=1.0",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    usd_to_rub_rate = get_usd_to_rub_rate()
    timestamp = datetime.now(pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S")
    
    with Session() as session:
        for attempt in range(3):
            try:
                response = session.get(url, headers=headers, timeout=10)
                logging.info(f"Статус ответа FunPay для {game}: {response.status_code}")
                response.raise_for_status()
                
                with open(f"funpay_sellers_{game}.html", "w", encoding="utf-8") as f:
                    f.write(response.text)
                logging.info(f"HTML продавцов для {game} сохранён")
                
                soup = BeautifulSoup(response.text, "html.parser")
                offers = soup.find_all("a", class_="tc-item", attrs={"data-server": league_id})
                logging.info(f"Найдено продавцов для {game} (лига {league_id}): {len(offers)}")
                
                if not offers:
                    logging.warning(f"Нет продавцов для {game} (лига {league_id})")
                    return []  # Пустой список для недоступной страницы
                
                for index, offer in enumerate(offers, 1):
                    try:
                        seller_name_elem = offer.find("div", class_="media-user-name")
                        seller_name = seller_name_elem.text.strip() if seller_name_elem else None
                        if not seller_name:
                            logging.error(f"Не найдено имя продавца для {game} на позиции {index}")
                            continue
                        
                        stock_elem = offer.find("div", class_="tc-amount")
                        stock = stock_elem.text.strip() if stock_elem else "0"
                        stock = re.sub(r"[^\d]", "", stock)
                        
                        price_text = None
                        price_div = offer.find("div", class_="tc-price")
                        if price_div:
                            price_inner_div = price_div.find("div")
                            if price_inner_div:
                                price_span = price_inner_div.find("span", class_="unit")
                                if price_span:
                                    price_text = price_inner_div.text.replace(price_span.text, "").strip()
                        
                        if price_text:
                            price = re.sub(r"[^\d.]", "", price_text.replace(",", "."))
                            try:
                                price = float(price)
                                if "$" in price_div.text:
                                    price = price * usd_to_rub_rate
                                    logging.info(f"Конверсия для {seller_name}: {price / usd_to_rub_rate} $ -> {price} ₽")
                                price = round(price, 2)
                            except ValueError:
                                logging.error(f"Не удалось преобразовать цену для {seller_name}: {price_text}")
                                continue
                        else:
                            logging.error(f"Не найдена цена для {seller_name} на позиции {index}")
                            continue
                        
                        all_offers.append({
                            "Timestamp": timestamp,
                            "Seller": seller_name,
                            "Stock": stock,
                            "Price": price,
                            "Position": index
                        })
                    except Exception as e:
                        logging.error(f"Ошибка обработки продавца для {game} на позиции {index}: {str(e)}")
                        continue
                
                if all_offers:
                    filtered_offers = [offer for offer in all_offers if 3 < offer["Position"] <= 13]
                    logging.info(f"Отфильтровано продавцов для {game}: {len(filtered_offers)} (позиции 4–13)")
                    return filtered_offers
                return []
            except Exception as e:
                logging.error(f"Ошибка загрузки страницы для {game} (попытка {attempt + 1}): {str(e)}")
                time.sleep(random.uniform(2, 5))
                continue
    
    logging.error(f"Не удалось загрузить продавцов для {game}, возвращаем пустой список")
    return []

def get_league_start_date(league_name):
    logging.info(f"Получение даты начала лиги {league_name}...")
    headers = {
        "User-Agent": UserAgent().random,
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=1.0",
        "Connection": "keep-alive"
    }
    for attempt in range(3):
        try:
            response = requests.get("https://www.pathofexile.com/api/leagues?type=main", headers=headers, timeout=10)
            response.raise_for_status()
            leagues = response.json()
            
            with open("poe_api_response.json", "w", encoding="utf-8") as f:
                json.dump(leagues, f, indent=4)
            logging.info("Ответ PoE API сохранён")
            
            for league in leagues:
                if league["id"].lower().replace(" ", "_") == league_name:
                    logging.info(f"Найдена лига: {league['id']} (старт: {league['startAt']})")
                    return league["startAt"][:7]
            
            logging.warning(f"Лига {league_name} не найдена, использую KNOWN_LEAGUE_DATES")
            return KNOWN_LEAGUE_DATES.get(league_name, datetime.now().strftime("%Y-%m"))
        except Exception as e:
            logging.error(f"Ошибка API PoE (попытка {attempt + 1}): {str(e)}")
            time.sleep(random.uniform(2, 5))
            continue
    logging.error(f"Не удалось получить дату для {league_name}, использую KNOWN_LEAGUE_DATES")
    return KNOWN_LEAGUE_DATES.get(league_name, datetime.now().strftime("%Y-%m"))

def save_to_github(data, game, league_name, start_date):
    logging.info(f"Сохранение данных для {game} (лига: {league_name})...")
    try:
        g = Github(os.getenv("GITHUB_TOKEN"))
        repo = g.get_repo("smokerdl/divine_orbs_prices")
        
        filename = f"prices_{game}_{league_name}_{start_date}.json"
        try:
            contents = repo.get_contents(filename)
            existing_data = json.loads(contents.decoded_content.decode())
            if not isinstance(existing_data, list):
                existing_data = []
            existing_data.extend(data)
            repo.update_file(
                contents.path,
                f"Update {filename}",
                json.dumps(existing_data, indent=4),
                contents.sha
            )
            logging.info(f"Файл {filename} обновлён, записей: {len(existing_data)}")
        except GithubException as e:
            if e.status == 404:
                repo.create_file(
                    filename,
                    f"Create {filename}",
                    json.dumps(data, indent=4)
                )
                logging.info(f"Файл {filename} создан, записей: {len(data)}")
            else:
                raise e
        
        # Обновляем current_leagues.json
        current_leagues = {}
        try:
            contents = repo.get_contents("current_leagues.json")
            current_leagues = json.loads(contents.decoded_content.decode())
        except GithubException as e:
            if e.status != 404:
                logging.error(f"Ошибка чтения current_leagues.json: {str(e)}")
        
        current_leagues[game] = {"league_name": league_name, "start_date": start_date}
        try:
            contents = repo.get_contents("current_leagues.json")
            repo.update_file(
                contents.path,
                "Update current_leagues.json",
                json.dumps(current_leagues, indent=4),
                contents.sha
            )
        except GithubException as e:
            if e.status == 404:
                repo.create_file(
                    "current_leagues.json",
                    "Create current_leagues.json",
                    json.dumps(current_leagues, indent=4)
                )
            else:
                raise e
        logging.info("Файл current_leagues.json обновлён")
    except Exception as e:
        logging.error(f"Ошибка сохранения на GitHub для {game}: {str(e)}")

def main():
    logging.info("Парсер запущен.")
    for game, config in GAMES.items():
        url = config["url"]
        prefix = config["league_prefix"]
        leagues = get_leagues(game, url, prefix)
        
        for league in leagues:
            league_name = league["name"]
            league_id = league["id"]
            start_date = get_league_start_date(league_name)
            logging.info(f"Обработка {game}: лига {league_name} (ID: {league_id}), дата: {start_date}")
            
            sellers_data = get_sellers_data(game, url, league_id)
            if sellers_data or not sellers_data:  # Сохраняем даже пустой список
                save_to_github(sellers_data, game, league_name, start_date)
    
    logging.info(f"Завершено: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()

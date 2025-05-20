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

# Словарь с известными датами лиг
KNOWN_LEAGUE_DATES = {
    "settlers_of_kalguur": "2024-07"
}

def get_leagues():
    logging.info("Получение списка лиг...")
    headers = {
        "User-Agent": UserAgent().random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://funpay.com/",
        "Accept-Language": "ru-RU,ru;q=1.0",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": "currency=rub"
    }
    
    leagues = []
    url = "https://funpay.com/chips/173/?currency=RUB"
    
    with Session() as session:
        # Предварительный запрос для установки сессии
        try:
            init_url = "https://funpay.com/?currency=RUB"
            init_response = session.get(init_url, headers=headers, timeout=10)
            logging.info(f"Статус ответа FunPay (инициализация): {init_response.status_code}")
            init_response.raise_for_status()
            # Логируем куки
            cookies = session.cookies.get_dict()
            logging.info(f"Полученные куки после инициализации: {cookies}")
        except Exception as e:
            logging.error(f"Ошибка инициализации сессии: {str(e)}")
        
        for attempt in range(3):
            try:
                response = session.get(url, headers=headers, timeout=10)
                logging.info(f"Статус ответа FunPay: {response.status_code}")
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Логируем HTML для отладки
                with open("funpay_leagues.html", "w", encoding="utf-8") as f:
                    f.write(soup.prettify())
                logging.info("HTML страницы лиг сохранён в funpay_leagues.html")
                
                select = soup.find("select", {"name": "server"})
                if not select:
                    logging.error("Не найден элемент <select name='server'>")
                    continue
                
                options = select.find_all("option")
                for option in options:
                    try:
                        league_id = option["value"]
                        league_name = option.text.strip().lower().replace(" ", "_")
                        if league_id and league_name == "(pc)_settlers_of_kalguur":
                            leagues.append({"name": "settlers_of_kalguur", "id": league_id})
                            logging.info(f"Найдена лига: {league_name} (ID: {league_id})")
                    except Exception as e:
                        logging.error(f"Ошибка обработки опции лиги: {str(e)}")
                        continue
                
                if leagues:
                    # Сохраняем ID лиг в JSON
                    try:
                        league_data = [{"name": l["name"], "id": l["id"], "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")} for l in leagues]
                        g = Github(os.getenv("GITHUB_TOKEN"))
                        repo = g.get_repo("smokerdl/divine_orbs_prices")
                        logging.info("Подключение к GitHub успешно")
                        try:
                            contents = repo.get_contents("league_ids.json")
                            existing_data = json.loads(contents.decoded_content.decode())
                            existing_data.extend(league_data)
                            repo.update_file(
                                contents.path,
                                "Update league_ids.json",
                                json.dumps(existing_data, indent=4),
                                contents.sha
                            )
                            logging.info("Файл league_ids.json обновлён")
                        except GithubException as e:
                            if e.status == 404:
                                repo.create_file(
                                    "league_ids.json",
                                    "Create league_ids.json",
                                    json.dumps(league_data, indent=4)
                                )
                                logging.info("Файл league_ids.json создан")
                            else:
                                logging.error(f"Ошибка GitHub API: {str(e)}")
                    except Exception as e:
                        logging.error(f"Ошибка сохранения league_ids.json: {str(e)}")
                    
                    logging.info(f"Найдено подходящих лиг: {len(leagues)}")
                    time.sleep(random.uniform(5, 10))
                    return leagues
                else:
                    logging.warning("Лига (PC) Settlers of Kalguur не найдена")
                    time.sleep(random.uniform(2, 5))
                    continue
            except Exception as e:
                logging.error(f"Ошибка получения лиг (попытка {attempt + 1}): {str(e)}")
                time.sleep(random.uniform(2, 5))
                continue
    
    logging.error("Не удалось найти лигу, возвращаем пустой список")
    return []

def get_sellers_data(league_id):
    logging.info("Сбор данных о продавцах...")
    sellers = []
    url = "https://funpay.com/chips/173/?currency=RUB"
    headers = {
        "User-Agent": UserAgent().random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://funpay.com/",
        "Accept-Language": "ru-RU,ru;q=1.0",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": "currency=rub"
    }
    
    with Session() as session:
        # Предварительный запрос для установки сессии
        try:
            init_url = "https://funpay.com/?currency=RUB"
            init_response = session.get(init_url, headers=headers, timeout=10)
            logging.info(f"Статус ответа FunPay (инициализация): {init_response.status_code}")
            init_response.raise_for_status()
            # Логируем куки
            cookies = session.cookies.get_dict()
            logging.info(f"Полученные куки после инициализации: {cookies}")
        except Exception as e:
            logging.error(f"Ошибка инициализации сессии: {str(e)}")
        
        for attempt in range(3):
            try:
                response = session.get(url, headers=headers, timeout=10)
                logging.info(f"Статус ответа FunPay для {url}: {response.status_code}")
                response.raise_for_status()
                
                # Логируем полный ответ для отладки
                with open("funpay_sellers_response.html", "w", encoding="utf-8") as f:
                    f.write(response.text)
                logging.info("Ответ FunPay сохранён в funpay_sellers_response.html")
                
                soup = BeautifulSoup(response.text, "html.parser")
                with open("funpay_sellers.html", "w", encoding="utf-8") as f:
                    f.write(soup.prettify())
                logging.info("HTML страницы продавцов сохранён в funpay_sellers.html")
                
                # Фильтруем продавцов по data-server
                offers = soup.find_all("a", class_="tc-item", attrs={"data-server": league_id})
                logging.info(f"Найдено продавцов для лиги {league_id}: {len(offers)}")
                
                if not offers:
                    logging.warning(f"Селектор a.tc-item с data-server={league_id} не нашёл продавцов на {url}")
                    break
                
                for offer in offers:
                    try:
                        # Имя продавца
                        seller_name_elem = offer.find("div", class_="media-user-name")
                        seller_name = seller_name_elem.text.strip() if seller_name_elem else None
                        if not seller_name:
                            logging.error("Не найдено имя продавца")
                            continue
                        
                        # Количество
                        stock_elem = offer.find("div", class_="tc-amount")
                        stock = stock_elem.text.strip() if stock_elem else "0"
                        stock = re.sub(r"[^\d]", "", stock)  # Очищаем количество
                        
                        # Цена
                        price_text = None
                        price_div = offer.find("div", class_="tc-price")
                        if price_div:
                            logging.info(f"Сырой текст div.tc-price для {seller_name}: {price_div.text}")
                            price_inner_div = price_div.find("div")
                            if price_inner_div:
                                logging.info(f"Сырой текст price_inner_div для {seller_name}: {price_inner_div.text}")
                                price_span = price_inner_div.find("span", class_="unit")
                                if price_span:
                                    price_text = price_inner_div.text.replace(price_span.text, "").strip()
                                    logging.info(f"Очищенный текст цены для {seller_name}: {price_text}")
                        
                        if price_text:
                            # Очищаем цену
                            price = re.sub(r"[^\d.]", "", price_text.replace(",", "."))
                            try:
                                price = float(price)
                                logging.info(f"Финальная цена для {seller_name}: {price}")
                            except ValueError:
                                logging.error(f"Не удалось преобразовать цену для {seller_name}: {price_text}")
                                continue
                        else:
                            logging.error(f"Не найдён элемент цены для {seller_name}")
                            continue
                        
                        sellers.append({
                            "Timestamp": datetime.now(pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S"),
                            "Seller": seller_name,
                            "Stock": stock,
                            "Price": price
                        })
                    except Exception as e:
                        logging.error(f"Ошибка обработки продавца: {str(e)}")
                        continue
                
                if sellers:
                    logging.info(f"Собрано продавцов: {len(sellers)}")
                    time.sleep(random.uniform(5, 10))
                    return sellers
                break
            except Exception as e:
                logging.error(f"Ошибка загрузки страницы FunPay для {url} (попытка {attempt + 1}): {str(e)}")
                time.sleep(random.uniform(2, 5))
                continue
    
    logging.error(f"Не удалось загрузить страницу продавцов: {url}")
    return []

def get_league_start_date(league_name):
    logging.info("Получение даты начала лиги через API PoE...")
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
            logging.info(f"API PoE вернул {len(leagues)} лиг")
            
            # Логируем ответ API для отладки
            with open("poe_api_response.json", "w", encoding="utf-8") as f:
                json.dump(leagues, f, indent=4)
            logging.info("Ответ PoE API сохранён в poe_api_response.json")
            
            for league in leagues:
                if league["id"].lower().replace(" ", "_") == league_name:
                    start_date = league["startAt"]
                    logging.info(f"Найдена лига: {league['id']} (старт: {start_date})")
                    return start_date[:7]
            
            logging.warning(f"Лига {league_name} не найдена в API, использую KNOWN_LEAGUE_DATES")
            return KNOWN_LEAGUE_DATES.get(league_name, datetime.now().strftime("%Y-%m"))
        except Exception as e:
            logging.error(f"Ошибка API PoE (попытка {attempt + 1}): {str(e)}")
            if attempt < 2:
                time.sleep(random.uniform(2, 5))
            continue
    logging.error("Не удалось получить данные от API PoE, использую KNOWN_LEAGUE_DATES")
    return KNOWN_LEAGUE_DATES.get(league_name, datetime.now().strftime("%Y-%m"))

def save_to_github(data, league_name, start_date):
    logging.info("Попытка подключения к GitHub...")
    try:
        g = Github(os.getenv("GITHUB_TOKEN"))
        repo = g.get_repo("smokerdl/divine_orbs_prices")
        logging.info(f"Репозиторий smokerdl/divine_orbs_prices успешно найден.")
        
        filename = f"prices_{league_name}_{start_date}.json"
        try:
            contents = repo.get_contents(filename)
            logging.info(f"Файл {filename} уже существует, обновляем...")
            existing_data = json.loads(contents.decoded_content.decode())
            existing_data.extend(data)
            repo.update_file(
                contents.path,
                f"Update {filename} with new data",
                json.dumps(existing_data, indent=4),
                contents.sha
            )
        except GithubException as e:
            if e.status == 404:
                logging.info(f"Файл {filename} не существует, создаём новый...")
                repo.create_file(
                    filename,
                    f"Create {filename} with initial data",
                    json.dumps(data, indent=4)
                )
            else:
                logging.error(f"Ошибка GitHub API: {str(e)}")
                raise e
        
        logging.info(f"Файл {filename} обновлён, записей: {len(data) if 'existing_data' not in locals() else len(existing_data)}")
    except Exception as e:
        logging.error(f"Ошибка сохранения на GitHub: {str(e)}")

def main():
    logging.info("Парсер запущен.")
    leagues = get_leagues()
    
    for league in leagues:
        league_name = league["name"]
        league_id = league["id"]
        start_date = get_league_start_date(league_name)
        logging.info(f"Текущая лига: {league_name} (ID: {league_id}), дата старта: {start_date}")
        
        sellers_data = get_sellers_data(league_id)
        if sellers_data:
            save_to_github(sellers_data, league_name, start_date)
    
    logging.info(f"Данные обработаны: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()

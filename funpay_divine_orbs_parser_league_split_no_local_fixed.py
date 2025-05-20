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

# Временное решение: захардкодим лигу
HARDCODED_LEAGUES = [
    {"name": "settlers_of_kalguur", "id": "10480"}
]

def get_leagues():
    logging.info("Получение списка лиг...")
    headers = {
        "User-Agent": UserAgent().random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://funpay.com/",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    # Временное решение: возвращаем захардкоденную лигу
    logging.info("Используем захардкоденную лигу settlers_of_kalguur (ID: 10480)")
    return HARDCODED_LEAGUES
    
    # Попытка парсинга (закомментировано до проверки селекторов)
    """
    try:
        with Session() as session:
            response = session.get("https://funpay.com/chips/173/", headers=headers)
            logging.info(f"Статус ответа FunPay: {response.status_code}")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Логируем HTML для отладки
            with open("funpay_leagues.html", "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            logging.info("HTML страницы лиг сохранён в funpay_leagues.html")
            
            league_elements = soup.find_all("a", class_="tc-item")
            leagues = []
            for elem in league_elements:
                try:
                    desc_elem = elem.find("div", class_="tc-desc") or elem.find("div", class_="league-name")
                    if desc_elem:
                        league_name = desc_elem.text.strip().lower().replace(" ", "_")
                        league_id = elem["href"].split("/")[-2]
                        if "settlers" in league_name:
                            leagues.append({"name": league_name, "id": league_id})
                            logging.info(f"Найдена лига: {league_name} (ID: {league_id})")
                    else:
                        logging.warning("Не найден элемент с названием лиги")
                except Exception as e:
                    logging.error(f"Ошибка обработки элемента лиги: {str(e)}")
                    continue
            
            logging.info(f"Найдено подходящих лиг: {len(leagues)}")
            time.sleep(random.uniform(5, 10))
            return leagues
    except Exception as e:
        logging.error(f"Ошибка получения лиг: {str(e)}")
        return []
    """

def get_sellers_data(league_id):
    logging.info("Сбор данных о продавцах...")
    sellers = []
    url = f"https://funpay.com/lots/{league_id}/"
    headers = {
        "User-Agent": UserAgent().random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://funpay.com/",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    try:
        with Session() as session:
            response = session.get(url, headers=headers)
            logging.info(f"Статус ответа FunPay: {response.status_code}")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Логируем HTML для отладки
            with open("funpay_sellers.html", "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            logging.info("HTML страницы продавцов сохранён в funpay_sellers.html")
            
            offers = soup.find_all("a", class_="tc-item")
            logging.info(f"Найдено продавцов: {len(offers)}")
            
            for offer in offers:
                try:
                    seller_name = offer.find("div", class_="tc-user").text.strip()
                    stock = offer.find("div", class_="tc-amount").text.strip()
                    stock = re.sub(r"[^\d]", "", stock)  # Очищаем количество
                    
                    # Пробуем несколько селекторов для цены
                    price_text = None
                    price_element = offer.find("div", class_="tc-price")
                    if price_element:
                        price_text = price_element.find("div", class_="amount").text.strip()
                    else:
                        price_element = offer.find("div", class_="price-block")
                        if price_element:
                            price_text = price_element.find("span", class_="price-amount").text.strip()
                    
                    if price_text:
                        logging.info(f"Извлечённая цена для {seller_name}: {price_text}")
                        # Очищаем цену: заменяем запятые на точки, убираем лишние символы
                        price = re.sub(r"[^\d.]", "", price_text.replace(",", "."))
                        try:
                            price = float(price)
                            # Проверяем, не слишком ли низкая цена
                            if price < 0.1:
                                logging.warning(f"Аномально низкая цена для {seller_name}: {price} рубля")
                                continue
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
                
            time.sleep(random.uniform(5, 10))
            return sellers
    except Exception as e:
        logging.error(f"Ошибка загрузки страницы FunPay: {str(e)}")
        return []

def get_league_start_date(league_name):
    logging.info("Получение даты начала лиги через API PoE...")
    try:
        response = requests.get("https://www.pathofexile.com/api/leagues?type=main")
        leagues = response.json()
        logging.info(f"API PoE вернул {len(leagues)} лиг")
        
        for league in leagues:
            if league["id"].lower().replace(" ", "_") == league_name:
                start_date = league["startAt"]
                logging.info(f"Найдена лига: {league['id']} (старт: {start_date})")
                return start_date[:7]
        
        logging.warning(f"Лига {league_name} не найдена в API, использую KNOWN_LEAGUE_DATES")
        return KNOWN_LEAGUE_DATES.get(league_name, datetime.now().strftime("%Y-%m"))
    except Exception as e:
        logging.error(f"Ошибка API PoE: {str(e)}")
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

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

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# URL страницы FunPay
URL = "https://funpay.com/chips/173/"

# Заголовки для имитации браузера
ua = UserAgent()
HEADERS = {
    "User-Agent": ua.random,  # Случайный User-Agent для каждого запроса
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1"
}

# GitHub настройки
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = "smokerdl/divine_orbs_prices"

# Fallback даты старта для известных лиг
KNOWN_LEAGUE_DATES = {
    "settlers_of_kalguur": "2024-07"
}

def normalize_league_name(name):
    """Нормализует имя лиги для сравнения."""
    name = re.sub(r"[^\w\s]", "", name).replace(" ", "").replace("_", "").lower()
    return name

def get_leagues():
    """Получает список подходящих лиг с FunPay, фильтруя по '(PC)' и исключая нежелательные."""
    try:
        time.sleep(random.uniform(5, 10))  # Случайная задержка
        session = Session()
        session.headers.update({**HEADERS, "User-Agent": ua.random})  # Обновляем User-Agent
        response = session.get(URL)
        logger.info(f"Статус ответа FunPay: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Ошибка загрузки страницы FunPay: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        select = soup.find("select", {"name": "server"}) or soup.find("select", {"class": "form-control showcase-filter-input"})
        if not select:
            logger.error("Не найдено выпадающее меню лиг")
            return []

        leagues = []
        for option in select.find_all("option"):
            league_id = option.get("value")
            league_name = option.text.strip()

            # Фильтрация: только лиги с приставкой (PC), исключаем Standard, Hardcore, Ruthless
            if not league_name.startswith("(PC)"):
                continue
            if "standard" in league_name.lower() or any(keyword in league_name.lower() for keyword in ["hardcore", "ruthless"]):
                continue
            if any(suffix in league_name for suffix in ["[Hardcore]", "[Ruthless Hardcore]", "[Ruthless]"]):
                continue

            # Нормализуем название для имени файла
            league_name_safe = re.sub(r"[^\w\s-]", "", league_name.replace("(PC)", "").strip()).replace(" ", "_").lower()
            leagues.append({"id": league_id, "name": league_name_safe})

        # Сортируем по ID, предполагая, что новая лига имеет самый высокий ID
        leagues.sort(key=lambda x: int(x["id"]), reverse=True)
        logger.info(f"Найдено подходящих лиг: {len(leagues)}")
        for league in leagues:
            logger.info(f"Лига: {league['name']} (ID: {league['id']})")
        return leagues
    except Exception as e:
        logger.error(f"Ошибка при парсинге лиг: {e}")
        return []

def get_league_start_date(league_name):
    """Получает дату старта лиги через API Path of Exile."""
    try:
        session = Session()
        session.headers.update({"User-Agent": ua.random})
        response = session.get("https://api.pathofexile.com/leagues")
        if response.status_code != 200:
            logger.error(f"Ошибка загрузки API PoE: {response.status_code}")
            return KNOWN_LEAGUE_DATES.get(league_name, datetime.now().strftime("%Y-%m"))

        leagues = response.json()
        logger.info(f"API PoE вернул {len(leagues)} лиг")
        normalized_input = normalize_league_name(league_name)
        for league in leagues:
            normalized_api_name = normalize_league_name(league["id"])
            if normalized_api_name in normalized_input:
                start_date = league.get("startAt")
                if start_date:
                    logger.info(f"Найдена лига: {league['id']} (старт: {start_date})")
                    return datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m")

        logger.warning(f"Дата старта для лиги {league_name} не найдена в API, используется fallback")
        return KNOWN_LEAGUE_DATES.get(league_name, datetime.now().strftime("%Y-%m"))
    except Exception as e:
        logger.error(f"Ошибка при получении даты лиги: {e}")
        return KNOWN_LEAGUE_DATES.get(league_name, datetime.now().strftime("%Y-%m"))

def get_sellers_data(league_id):
    """Получает данные о продавцах с сайта FunPay для указанной лиги."""
    try:
        time.sleep(random.uniform(5, 10))  # Случайная задержка
        session = Session()
        session.headers.update({**HEADERS, "User-Agent": ua.random})  # Обновляем User-Agent
        response = session.get(URL)
        if response.status_code != 200:
            logger.error(f"Ошибка загрузки страницы: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        offers = soup.find_all("a", {"class": "tc-item"})

        sellers = []
        for offer in offers:
            if offer.get("data-server") != league_id or offer.get("data-online") != "1":
                continue
            seller_name = offer.find("div", {"class": "media-user-name"}).text.strip()
            stock = offer.find("div", {"class": "tc-amount"}).text.strip()
            price = offer.find("div", {"class": "tc-price"}).text.strip().split()[0]
            sellers.append({
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Seller": seller_name,
                "Stock": stock,
                "Price": float(price)
            })
            if len(sellers) == 10:
                break
        logger.info(f"Найдено продавцов: {len(sellers)}")
        return sellers
    except Exception as e:
        logger.error(f"Ошибка при парсинге продавцов: {e}")
        return []

def upload_to_github(data, league_name, start_date):
    """Загружает данные в JSON-файл в GitHub-репозиторий."""
    file_path_in_repo = f"prices_{league_name}_{start_date}.json"
    try:
        if not GITHUB_TOKEN:
            logger.error("Ошибка: GITHUB_TOKEN не установлен в переменной окружения.")
            return False

        logger.info("Попытка подключения к GitHub...")
        g = Github(GITHUB_TOKEN)

        repo = g.get_repo(REPO_NAME)
        logger.info(f"Репозиторий {REPO_NAME} успешно найден.")

        # Получаем существующие данные из GitHub, если файл существует
        existing_data = []
        try:
            file = repo.get_contents(file_path_in_repo, ref="main")
            existing_data = json.loads(file.decoded_content.decode("utf-8"))
            logger.info(f"Файл {file_path_in_repo} уже существует, обновляем...")
        except GithubException as e:
            if e.status == 404:
                logger.info(f"Файл {file_path_in_repo} не существует, создаём...")
            else:
                logger.error(f"Ошибка GitHub API при получении файла: {e.status} - {e.data}")
                return False

        # Добавляем новые данные
        existing_data.extend(data)
        content = json.dumps(existing_data, indent=4)

        # Обновляем или создаём файл
        try:
            if existing_data and file:  # Файл существует
                repo.update_file(
                    path=file_path_in_repo,
                    message=f"Update {file_path_in_repo} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    content=content,
                    sha=file.sha,
                    branch="main"
                )
                logger.info(f"Файл {file_path_in_repo} обновлён, записей: {len(existing_data)}")
            else:  # Файл не существует
                repo.create_file(
                    path=file_path_in_repo,
                    message=f"Create {file_path_in_repo} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    content=content,
                    branch="main"
                )
                logger.info(f"Файл {file_path_in_repo} создан, записей: {len(existing_data)}")
            return True
        except GithubException as e:
            logger.error(f"Ошибка GitHub API при загрузке: {e.status} - {e.data}")
            return False
    except GithubException as e:
        logger.error(f"Ошибка авторизации или доступа к репозиторию: {e.status} - {e.data}")
        return False
    except Exception as e:
        logger.error(f"Общая ошибка при загрузке в GitHub: {e}")
        return False

def main():
    """Основная функция парсера."""
    logger.info("Парсер запущен.")
    try:
        # Получаем список подходящих лиг
        leagues = get_leagues()
        if not leagues:
            logger.error("Не удалось получить список лиг.")
            return

        # Текущая лига — первая в списке (с самым высоким ID)
        league_id = leagues[0]["id"]
        league_name = leagues[0]["name"]
        start_date = get_league_start_date(league_name)
        logger.info(f"Текущая лига: {league_name} (ID: {league_id}), дата старта: {start_date}")

        # Собираем данные продавцов
        sellers_data = get_sellers_data(league_id)
        if sellers_data:
            if upload_to_github(sellers_data, league_name, start_date):
                logger.info(f"Данные обработаны: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                logger.error("Ошибка при загрузке данных в GitHub.")
        else:
            logger.warning("Не найдено продавцов онлайн или данные недоступны.")
    except Exception as e:
        logger.error(f"Ошибка в основном цикле: {e}")

if __name__ == "__main__":
    main()

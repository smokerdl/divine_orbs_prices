import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import pytz
import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from github import Github

logger = logging.getLogger(__name__)

GAMES = {
    "poe": {"url": "https://funpay.com/chips/173/", "section_id": 173},
    "poe2": {"url": "https://funpay.com/chips/209/?side=106", "section_id": 209}
}

def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("0_parse.txt", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )

def filter_league_name(league_name, game):
    """Фильтрует название лиги согласно заданным правилам."""
    league_name = re.sub(r'[\'"]', '', league_name)
    league_name = re.sub(r'\[.*?\]', '', league_name).strip()
    if game == "poe":
        if not league_name.startswith('(PC)'):
            return None
        league_name = re.sub(r'\([^)]*\)', '', league_name).strip()
        league_name = league_name.replace('(PC)', '').strip()
    else:
        league_name = re.sub(r'\([^)]*\)', '', league_name).strip()
    
    if league_name.lower() == "лига":
        return None
    
    forbidden_words = ['standard', 'hardcore', 'ruthless']
    if any(word in league_name.lower() for word in forbidden_words):
        return None
    
    return league_name

def get_leagues(game, session):
    logger.info(f"Обработка игры: {game}")
    response = session.get(GAMES[game]["url"])
    if response.status_code != 200:
        logger.error(f"Ошибка загрузки страницы лиг для {game}: {response.status_code}")
        return []
    soup = BeautifulSoup(response.text, "lxml")
    with open(f"funpay_leagues_{game}.html", "w", encoding="utf-8") as f:
        f.write(response.text)
    select = soup.find("select", {"name": "server"})
    if not select:
        logger.error(f"Не найден селектор лиг для {game}")
        return []
    leagues = []
    for option in select.find_all("option"):
        league_id = option.get("value")
        league_name = option.text.strip()
        if not (league_id and league_name):
            continue
        filtered_name = filter_league_name(league_name, game)
        if filtered_name:
            leagues.append({"id": league_id, "name": filtered_name})
        else:
            logger.debug(f"Лига исключена: {league_name}")
    logger.info(f"Найдено лиг для {game}: {len(leagues)}")
    return leagues

def get_sellers(game, league_id, league_name, session):
    url = f"{GAMES[game]['url']}?server={league_id}"
    valid_offers = []
    response = session.get(url)
    if response.status_code != 200:
        logger.error(f"Ошибка загрузки страницы продавцов для {game}: {response.status_code}")
        return []
    content = response.text
    with open(f"funpay_sellers_{game}_page1.html", "w", encoding="utf-8") as f:
        f.write(content)
    soup = BeautifulSoup(content, "lxml")
    offers = soup.select(f'a.tc-item[data-server="{league_id}"]')
    logger.info(f"Найдено офферов для {game} (лига {league_name}): {len(offers)}")
    run_timestamp = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S")
    for index, offer in enumerate(offers, 1):
        # Проверяем тип валюты
        currency_elem = offer.find("div", class_="tc-side")
        currency = currency_elem.text.strip().lower() if currency_elem else ""
        data_side = offer.get("data-side")
        logger.debug(f"Обработка оффера: валюта={currency}, data-side={data_side}")
        
        # Проверяем Divine Orbs
        is_divine_orb = False
        if game == "poe2" and data_side == "106":
            is_divine_orb = True
        elif "divine orb" in currency or "божественные сферы" in currency:
            is_divine_orb = True
        
        if not is_divine_orb:
            logger.debug(f"Пропущен оффер: валюта={currency}, data-side={data_side} (не Divine Orb)")
            # Для отладки сохраняем HTML оффера
            with open(f"skipped_offer_{game}_{index}.html", "w", encoding="utf-8") as f:
                f.write(str(offer))
            continue
        
        # Извлекаем цену
        price_elem = offer.find("div", class_="tc-price")
        price_inner = price_elem.find("div") or price_elem.find("span")
        price_text = price_inner.text.strip() if price_inner else price_elem.text.strip()
        logger.debug(f"Сырой текст цены на позиции {index}: '{price_text}'")
        # Извлекаем количество
        amount_elem = offer.find("div", class_="tc-amount")
        amount_text = amount_elem.text.strip() if amount_elem else "0"
        amount_num = int(re.sub(r"[^\d]", "", amount_text)) if re.sub(r"[^\d]", "", amount_text) else 0
        # Извлекаем имя продавца
        user_elem = offer.find("div", class_="tc-user")
        username = user_elem.find("div", class_="media-user-name").text.strip() if user_elem else f"Unknown_{index}"
        # Парсим цену и валюту
        price = 0.0
        currency_code = "Unknown"
        price_text_clean = re.sub(r"[^\d.]", "", price_text).strip()
        try:
            price = float(price_text_clean)
            if '₽' in price_text or 'RUB' in price_text.lower():
                currency_code = "RUB"
            elif '$' in price_text or 'USD' in price_text.lower():
                currency_code = "USD"
            else:
                logger.warning(f"Неизвестная валюта для {username}: {price_text}")
                continue
        except ValueError:
            logger.error(f"Ошибка парсинга цены для {username}: {price_text}")
            continue
        valid_offers.append({
            "Timestamp": run_timestamp,
            "Seller": username,
            "Stock": amount_num,
            "Price": price,
            "Currency": currency_code,
            "Position": index,
            "DisplayPosition": 0,
            "Online": None
        })
    logger.info(f"Найдено валидных офферов для {game}: {len(valid_offers)}")
    selected_offers = sorted(valid_offers, key=lambda x: x["Price"])[:5]
    for idx, offer in enumerate(selected_offers, 1):
        offer["DisplayPosition"] = idx
    logger.info(f"Собрано продавцов для {game}: {len(selected_offers)} (позиции 1–{len(selected_offers)})")
    return selected_offers

def save_to_json(data, game, league_name, timestamp):
    safe_league_name = re.sub(r'[^\w\-]', '_', league_name.lower())
    year, month = timestamp.strftime("%Y-%m").split("-")
    filename = f"prices_{game}_{safe_league_name}_{year}-{month}.json"
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
    else:
        existing_data = []
    existing_data.extend(data)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)
    file_size = os.path.getsize(filename)
    if file_size > 20 * 1024 * 1024:
        logger.warning(f"Размер файла {filename} превысил 20 Мб: {file_size} байт")
    return filename

def commit_to_github(filenames):
    g = Github(os.getenv("GITHUB_TOKEN"))
    repo = g.get_repo(os.getenv("GITHUB_REPOSITORY"))
    for filename in filenames:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        try:
            repo_file = repo.get_contents(filename)
            repo.update_file(
                filename,
                f"Update {filename}",
                content,
                repo_file.sha
            )
            logger.info(f"Файл {filename} обновлён в репозитории")
        except:
            repo.create_file(
                filename,
                f"Create {filename}",
                content
            )
            logger.info(f"Файл {filename} создан в репозитории")

def main():
    setup_logging()
    ua = UserAgent()
    session = requests.Session()
    session.headers.update({
        "User-Agent": ua.random,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://funpay.com/"
    })
    session.cookies.update({
        "currency": "USD",
        "locale": "en",
        "cy": "USD"
    })
    filenames = []
    for game in GAMES:
        leagues = get_leagues(game, session)
        for league in leagues:
            sellers = get_sellers(game, league["id"], league["name"], session)
            if sellers:
                timestamp = datetime.now(pytz.UTC)
                filename = save_to_json(sellers, game, league["name"], timestamp)
                filenames.append(filename)
    if filenames:
        commit_to_github(filenames)

if __name__ == "__main__":
    main()

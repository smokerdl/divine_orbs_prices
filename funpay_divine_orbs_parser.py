import os
import re
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from github import Github
import json

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def get_leagues(game_name, headers, log_dir):
    logger.info(f"Получение лиг для {game_name}...")
    chip_id = "173" if game_name == "poe" else "209"
    url = f"https://funpay.com/chips/{chip_id}/"
    
    try:
        response = requests.get(url, headers=headers)
        logger.debug(f"https://funpay.com:443 \"GET /chips/{chip_id}/ HTTP/1.1\" {response.status_code} None")
        if response.status_code != 200:
            logger.error(f"Ошибка при получении лиг для {game_name}: статус {response.status_code}")
            return []
        
        logger.info(f"Статус ответа FunPay для лиг {game_name}: {response.status_code}")
        soup = BeautifulSoup(response.text, "lxml")
        
        with open(os.path.join(log_dir, f"funpay_leagues_{game_name}.html"), "w", encoding="utf-8") as f:
            f.write(response.text)
        logger.info(f"HTML лиг для {game_name} сохранён")
        
        leagues = []
        for option in soup.select("select.form-control option"):
            if not option["value"]:
                continue
            name = option.text.strip()
            # Общие фильтры: исключаем Hardcore, Ruthless, Standard
            if any(x in name.lower() for x in ["hardcore", "ruthless", "standard"]):
                continue
            # Фильтры для PoE
            if game_name == "poe":
                # Требуем (PC), исключаем (PS), (Xbox) и (PLxxxx)
                if not name.startswith("(PC)") or name.startswith("(PS)") or name.startswith("(Xbox)") or re.search(r'\(PL\d+\)', name):
                    continue
            # Фильтры для PoE 2: удаляем приставки (PC), (PS), (Xbox)
            elif game_name == "poe2":
                name = re.sub(r'^\([A-Za-z]+\)\s*', '', name)
            leagues.append({"id": option["value"], "name": name})
        
        logger.info(f"Найдено лиг для {game_name}: {len(leagues)}")
        logger.info(f"Данные лиг для {game_name}: {leagues}")
        return leagues
    
    except Exception as e:
        logger.error(f"Ошибка при получении лиг для {game_name}: {str(e)}")
        return []

def get_sellers(game_name, league_id, headers, log_dir):
    logger.info(f"Сбор данных о продавцах для {game_name} (лига {league_id})...")
    chip_id = "173" if game_name == "poe" else "209"
    sellers = []
    page = 1
    
    while True:
        url = f"https://funpay.com/chips/{chip_id}/?page={page}"
        try:
            response = requests.get(url, headers=headers)
            logger.debug(f"https://funpay.com:443 \"GET /chips/{chip_id}/?page={page} HTTP/1.1\" {response.status_code} None")
            if response.status_code != 200:
                logger.error(f"Ошибка при получении продавцов для {game_name} (лига {league_id}, страница {page}): статус {response.status_code}")
                break
            
            logger.info(f"Статус ответа FunPay для {game_name} (лига {league_id}, страница {page}): {response.status_code}")
            soup = BeautifulSoup(response.text, "lxml")
            
            with open(os.path.join(log_dir, f"funpay_sellers_{game_name}_page{page}.html"), "w", encoding="utf-8") as f:
                f.write(response.text)
            logger.info(f"HTML продавцов для {game_name} (страница {page}) сохранён")
            
            offers = soup.select("a.tc-item")
            logger.info(f"Найдено продавцов для {game_name} (лига {league_id}, страница {page}): {len(offers)}")
            
            for idx, offer in enumerate(offers, start=len(sellers) + 1):
                try:
                    if offer.get("data-server") != league_id:
                        logger.debug(f"Пропущен оффер {idx}: data-server не {league_id}")
                        continue
                    
                    tc_side = offer.select_one(".tc-side") or ""
                    tc_side_text = tc_side.text.strip().lower() if tc_side else ""
                    if "divine orb" not in tc_side_text:
                        logger.debug(f"Пропущен оффер для {offer.select_one('.tc-user').text.strip()}: нет Divine Orbs в описании")
                        continue
                    
                    seller = offer.select_one(".tc-user").text.strip()
                    stock = offer.select_one(".tc-amount").text.strip()
                    price_raw = offer.select_one(".tc-price").text.strip()
                    price = float(re.search(r"[\d.]+", price_raw).group())
                    currency = "USD"
                    
                    logger.debug(f"Сток для {seller}: {stock}")
                    logger.debug(f"Сырой текст цены для {seller}: '{price_raw}'")
                    logger.debug(f"Цена для {seller}: {price} {currency}")
                    logger.debug(f"Отладка оффера {idx}: {seller}, Цена: {price} {currency}, tc-desc: {tc_side_text}")
                    
                    sellers.append({
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Seller": seller,
                        "Stock": stock,
                        "Price": price,
                        "Currency": currency,
                        "Position": idx,
                        "DisplayPosition": len(sellers) + 3,
                        "Online": bool(offer.select_one(".user-status-online")),
                        "League": league_id
                    })
                
                except Exception as e:
                    logger.error(f"Ошибка при обработке оффера {idx} для {game_name}: {str(e)}")
                    continue
            
            if not soup.select_one("a.pagination-next"):
                logger.info(f"Пагинация завершена для {game_name} на странице {page}")
                break
            page += 1
        
        except Exception as e:
            logger.error(f"Ошибка при получении продавцов для {game_name} (страница {page}): {str(e)}")
            break
    
    logger.info(f"Найдено валидных офферов для {game_name}: {len(sellers)}")
    logger.debug(f"Содержимое sellers: {sellers}")
    return sellers

def save_data(data, output_file):
    try:
        existing_data = []
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        
        existing_data.extend(data)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Данные успешно сохранены в {output_file}: {len(data)} записей")
    
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных в {output_file}: {str(e)}")

def update_repository(file_path, commit_message, github_token):
    try:
        g = Github(github_token)
        repo = g.get_repo("smokerdl/divine_orbs_prices")
        with open(file_path, "rb") as f:
            content = f.read()
        file_name = os.path.basename(file_path)
        
        try:
            contents = repo.get_contents(file_name)
            repo.update_file(contents.path, commit_message, content, contents.sha)
        except:
            repo.create_file(file_name, commit_message, content)
        
        logger.info(f"Файл {file_name} обновлён в репозитории")
    
    except Exception as e:
        logger.error(f"Ошибка при обновлении репозитория для {file_path}: {str(e)}")

def main():
    log_dir = os.path.abspath(os.path.dirname(__file__))
    github_token = os.getenv("GITHUB_TOKEN")
    headers = {"User-Agent": UserAgent().random}
    
    games = [
        {
            "name": "poe",
            "default_league_id": "10480",
            "default_output_file": "prices_poe_settlers_of_kalguur_2024-07.json"
        },
        {
            "name": "poe2",
            "default_league_id": "11287",
            "default_output_file": "prices_poe2_dawn_of_the_hunt_2024-12.json"
        }
    ]
    
    for game in games:
        logger.info(f"Обработка игры: {game['name']}")
        leagues = get_leagues(game["name"], headers, log_dir)
        
        if not leagues:
            logger.error(f"Не удалось получить лиги для {game['name']}, пропускаем")
            continue
        
        current_league = next((l for l in leagues if l["id"] == game["default_league_id"]), None)
        
        if not current_league:
            logger.warning(f"Лига {game['default_league_id']} не найдена для {game['name']}")
            old_file = os.path.join(log_dir, game["default_output_file"])
            if os.path.exists(old_file):
                archive_file = old_file.replace('.json', '_archive.json')
                os.rename(old_file, archive_file)
                update_repository(archive_file, f"Archive {game['default_output_file']}", github_token)
                logger.info(f"Старый JSON архивирован: {archive_file}")
            
            if not leagues:
                logger.warning(f"Нет лиг, удовлетворяющих фильтрам для {game['name']}, пропускаем создание нового JSON")
                continue
            
            current_league = leagues[0]
            logger.info(f"Выбрана новая лига для {game['name']}: {current_league['name']} (ID: {current_league['id']})")
        
        league_id = current_league["id"]
        league_name = re.sub(r'[^\w\s-]', '', current_league["name"]).lower().replace(' ', '_')
        output_file = os.path.join(log_dir, f"prices_{game['name']}_{league_name}_{datetime.now().strftime('%Y-%m')}.json")
        
        logger.info(f"Сбор данных о продавцах для {game['name']} (лига {league_id})...")
        sellers = get_sellers(game["name"], league_id, headers, log_dir)
        
        if sellers:
            save_data(sellers, output_file)
            update_repository(output_file, f"Update {os.path.basename(output_file)}", github_token)
            logger.info(f"Сохранено в {output_file}")
        
        league_file = os.path.join(log_dir, "league_ids.json")
        save_data(leagues, league_file)
        update_repository(league_file, "Update league_ids.json", github_token)
        logger.info("Сохранено в league_ids.json")

if __name__ == "__main__":
    main()

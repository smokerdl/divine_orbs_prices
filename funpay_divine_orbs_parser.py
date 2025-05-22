import json
import os
from github import Github
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def save_to_json(offers, game, league_name, output_dir="parser-artifacts"):
    """Сохраняет офферы в JSON, добавляя их к существующим данным."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m")
    filename = f"{output_dir}/prices_{game}_{league_name.lower().replace(' ', '_')}_{timestamp}.json"
    
    # Читаем существующий JSON, если он есть
    existing_offers = []
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_offers = json.load(f)
            logger.debug(f"Прочитано {len(existing_offers)} существующих записей из {filename}")
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка при чтении {filename}: {e}")
    
    # Добавляем новые офферы
    all_offers = existing_offers + offers
    logger.debug(f"После добавления новых офферов: {len(all_offers)} записей")
    
    # Сохраняем объединённый список
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_offers, f, indent=2, ensure_ascii=False)
        file_size = os.path.getsize(filename)
        logger.info(f"Сохранено {len(all_offers)} записей в {filename} (размер: {file_size} байт)")
    except Exception as e:
        logger.error(f"Ошибка при сохранении {filename}: {e}")
    
    return filename

def upload_to_github(filename, github_token, repo_name):
    """Загружает файл в репозиторий GitHub."""
    try:
        g = Github(github_token)
        repo = g.get_repo(repo_name)
        file_path = os.path.basename(filename)
        
        # Читаем существующий файл из репозитория
        try:
            contents = repo.get_contents(file_path)
            existing_content = contents.decoded_content.decode('utf-8')
            existing_offers = json.loads(existing_content)
        except:
            existing_offers = []
        
        # Читаем локальный файл
        with open(filename, 'r', encoding='utf-8') as f:
            local_offers = json.load(f)
        
        # Объединяем данные
        all_offers = existing_offers + local_offers
        
        # Обновляем файл в репозитории
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_offers, f, indent=2, ensure_ascii=False)
        
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        
        try:
            repo.update_file(file_path, f"Update {file_path}", content, contents.sha)
        except:
            repo.create_file(file_path, f"Create {file_path}", content)
        
        logger.info(f"Файл {file_path} обновлён в репозитории")
    except Exception as e:
        logger.error(f"Ошибка при загрузке {file_path} в GitHub: {e}")

def parse_offers(html_content, game, league_name):
    """Парсит офферы продавцов из HTML."""
    from bs4 import BeautifulSoup
    import re
    logger.info(f"Парсинг продавцов для {game} (лига {league_name})")
    soup = BeautifulSoup(html_content, 'html.parser')
    offers = soup.select('a.tc-item')
    
    valid_offers = []
    skipped_count = 0
    divine_orbs_count = 0
    
    for index, offer in enumerate(offers, 1):
        try:
            currency_elem = offer.select_one('.tc-desc-text')
            currency = currency_elem.text.strip().lower() if currency_elem else ''
            data_side = offer.get('data-side', '')
            
            logger.debug(f"Обработка оффера: валюта={currency}, data-side={data_side}")
            
            # Проверяем, что это divine orbs
            if data_side != '106' or 'divine orb' not in currency.lower():
                logger.debug(f"Пропущен оффер: валюта={currency}, data-side={data_side}")
                skipped_count += 1
                with open(f'parser-artifacts/skipped_offer_{game}_{index}.html', 'w', encoding='utf-8') as f:
                    f.write(str(offer))
                continue
                
            divine_orbs_count += 1
            seller_elem = offer.select_one('.tc-user a')
            seller = seller_elem.text.strip() if seller_elem else ''
            
            stock_elem = offer.select_one('.tc-amount')
            stock = int(stock_elem.text.strip()) if stock_elem and stock_elem.text.strip().isdigit() else 0
            
            price_elem = offer.select_one('.tc-price div')
            price_str = price_elem.text.strip() if price_elem else ''
            price = float(re.search(r'\d+\.\d+', price_str).group()) if re.search(r'\d+\.\d+', price_str) else 0.0
            currency_type = 'USD' if '$' in price_str else 'Unknown'
            
            valid_offers.append({
                'Timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'Seller': seller,
                'Stock': stock,
                'Price': price,
                'Currency': currency_type,
                'Position': index,
                'DisplayPosition': index,
                'Online': None
            })
            
        except Exception as e:
            logger.error(f"Ошибка при парсинге оффера {index}: {e}")
            skipped_count += 1
            with open(f'parser-artifacts/skipped_offer_{game}_{index}.html', 'w', encoding='utf-8') as f:
                f.write(str(offer))
            continue
    
    logger.info(f"Найдено офферов для {game} (лига {league_name}): {len(offers)}")
    logger.info(f"Найдено офферов divine orbs: {divine_orbs_count}")
    logger.info(f"Найдено валидных офферов для {game}: {len(valid_offers)}")
    
    # Сортируем по позиции и берём позиции 4–8
    valid_offers.sort(key=lambda x: x['Position'])
    selected_offers = valid_offers[3:8] if len(valid_offers) >= 8 else valid_offers
    
    # Исправляем DisplayPosition
    for i, offer in enumerate(selected_offers, 4):
        offer['DisplayPosition'] = i
    
    logger.info(f"Собрано продавцов для {game}: {len(selected_offers)} (позиции 4–8)")
    logger.debug(f"Выбранные офферы для {game}: {selected_offers}")
    
    return selected_offers, skipped_count

# Пример основной функции (замените в вашем коде)
def main():
    import requests
    from fake_useragent import UserAgent
    
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    
    github_token = os.getenv('GITHUB_TOKEN')
    repo_name = os.getenv('GITHUB_REPOSITORY', 'smokerdl/divine_orbs_prices')
    
    games = {
        'poe': 'https://funpay.com/en/chips/173/',
        'poe2': 'https://funpay.com/en/chips/209/'
    }
    
    ua = UserAgent()
    headers = {'User-Agent': ua.random}
    
    for game, url in games.items():
        logger.info(f"Обработка игры: {game}")
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        leagues = soup.select('.server-list a')
        for league in leagues:
            league_name = league.text.strip()
            league_url = league['href']
            logger.debug(f"Фильтрация лиги: {league_name} для игры {game}")
            
            # Фильтрация лиг
            if not league_name.startswith('(PC)') or any(x in league_name.lower() for x in ['hardcore', 'ruthless', 'standard']):
                logger.debug(f"Лига исключена: {league_name}")
                continue
            
            cleaned_league_name = league_name.replace('(PC)', '').strip()
            logger.debug(f"Лига принята: {cleaned_league_name}")
            
            # Парсинг офферов
            response = requests.get(league_url, headers=headers)
            offers, skipped = parse_offers(response.text, game, cleaned_league_name)
            
            # Сохранение в JSON
            filename = save_to_json(offers, game, cleaned_league_name)
            
            # Загрузка в GitHub
            upload_to_github(filename, github_token, repo_name)

if __name__ == "__main__":
    main()

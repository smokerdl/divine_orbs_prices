import json
import os
import logging
import requests
from datetime import datetime
from github import Github
from bs4 import BeautifulSoup  # Добавляем импорт BeautifulSoup
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

def main():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    
    github_token = os.getenv('GITHUB_TOKEN')
    repo_name = os.getenv('GITHUB_REPOSITORY', 'smokerdl/divine_orbs_prices')
    
    games = {
        'poe': 'https://funpay.com/en/chips/173/?side=106',  # Divine Orbs
        'poe2': 'https://funpay.com/en/chips/209/?side=106&server=11287'  # Divine Orbs, Dawn of the Hunt
    }
    
    ua = UserAgent()
    headers = {'User-Agent': ua.random}
    
    for game, url in games.items():
        logger.info(f"Обработка игры: {game}")
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')  # Теперь BeautifulSoup определён
        
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

def main():
    github_token = os.getenv("POE_TOKEN")
    if not github_token:
        logger.error("POE_TOKEN не установлен")
        return
    
    games = [
        {
            "name": "poe",
            "default_league_id": "11512",
            "default_output_file": "prices_poe_secrets_of_the_atlas_2025-06.json"
        },
        {
            "name": "poe2",
            "default_league_id": "11287,
            "default_output_file": "prices_poe2_dawn_of_the_hunt_2025-06.json"
        }
    ]
    
    all_leagues = []
    
    for game in games:
        logger.info(f"Processing game: {game['name']}")
        
        leagues = get_leagues(game["name"])
        if not leagues:
            logger.warning(f"Не удалось получить лиг для {game['name']}, используя default league ID: {game['default_league_id']}")
            league_id = game["default_league_id"]
            output_file = os.path.join(log_dir, game["default_output_file"])
            league_name = game["default_output_file"].split('_')[2].replace('.json', '')
        else:
            current_league = select_current_league(leagues, game["name"])
            if not current_league:
                logger.error(f"Не удалось выбрать текущую лигу для {game['name']}")
                continue
                
            league_id = current_league["id']
            last_output_file = os.path.join(log_dir, f"last_output_{game['name']}.txt")
            previous_output_file = None
            if os.path.exists(last_output_file):
                with open(last_output_file, 'r', encoding='utf-8') as f:
                    previous_output_file = f.read().strip()
            
            league_name = re.sub(r'\(pc\)\s*', '', current_league["name"], flags=re.IGNORECASE).lower().replace(' ', '_')
            output_file = os.path.join(log_dir, f"prices_{game['name']}_{league_name}_{datetime.now().strftime('%Y-%m')}.json")
            
            if previous_output_file and previous_output_file != output_file:
                archive_old_data(previous_output_file, github_token)
            
            with open(last_output_file, 'w', encoding='utf-8') as f:
                f.write(output_file)
        
        logger.info(f"Selected output file: {output_file}, League: {league_name}, ID: {league_id}")
        
        sellers = get_sellers(game["name"], league_id)
        if sellers:
            save_data(sellers, output_file)
            update_repository(output_file, f"Update {os.path.basename(output_file)}", github_token)
        else:
            logger.warning(f"No data to save for {league_name}")
        
        # Добавляем лиги в общий список с указанием игры
        for league in leagues:
            league["game"] = game["name"]
        all_leagues.extend(leagues)
    
    # Сохраняем все лиги в единый файл
    league_file = os.path.join(log_dir, "league_ids.json")
    save_data(all_leagues, league_file, overwrite=True)
    update_repository(league_file, "Update league_ids.json", github_token)
    logger.info(f"Сохранено {len(all_leagues)} лиг в {league_file}")

if __name__ == "__main__":
    main()

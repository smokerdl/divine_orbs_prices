def get_sellers(game, league_id):
    logger.info(f"Сбор данных о продавцах для {game} (лига {league_id})...")
    url = POE_URL if game == 'poe' else POE2_URL
    session = requests.Session()
    session.headers.update(headers)
    SBP_COMMISSION = 1.2118
    CARD_COMMISSION = 1.2526
    FUNPAY_EXCHANGE_RATE = 79.89
    
    for attempt in range(3):
        try:
            response = session.get(url, timeout=15)
            logger.info(f"Статус ответа FunPay для {game} (лига {league_id}): {response.status_code}")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            with open(os.path.join(log_dir, f'funpay_sellers_{game}.html'), 'w', encoding='utf-8') as f:
                f.write(soup.prettify())
            logger.info(f"HTML продавцов для {game} сохранён")
            
            offers = soup.find_all("a", class_="tc-item")
            logger.info(f"Найдено продавцов для {game} (лига {league_id}): {len(offers)}")
            if not offers:
                logger.warning(f"Селектор a.tc-item с data-server={league_id} не нашёл продавцов")
                return []
            
            sellers = []
            min_price_rub = 0.5 if game == 'poe' else 5.0
            max_price_rub = 50.0  # Фильтр выбросов
            for index, offer in enumerate(offers, 1):
                try:
                    logger.debug(f"Обрабатываем оффер {index}: {offer.prettify()[:200]}...")
                    
                    if str(offer.get("data-server")) != str(league_id):
                        continue
                    
                    username_elem = offer.find("div", class_="media-user-name")
                    username = username_elem.text.strip() if username_elem else None
                    if not username:
                        continue
                    
                    orb_type = "Божественные сферы" if game == 'poe' else "Неизвестно"
                    if game == 'poe2':
                        desc_elem = offer.find("div", class_="tc-desc")
                        desc_text = desc_elem.text.strip().lower() if desc_elem else ""
                        side_elem = offer.find("div", class_="tc-side") or offer.find("div", class_="tc-side-inside")
                        side_text = side_elem.text.strip().lower() if side_elem else ""
                        logger.debug(f"tc-desc для {username}: {desc_text}")
                        logger.debug(f"tc-side для {username}: {side_text}")
                        if ("divine" in desc_text or "божественные сферы" in desc_text or 
                            "divine" in side_text or "божественные сферы" in side_text or 
                            offer.get("data-side") == "106"):
                            orb_type = "Божественные сферы"
                        if orb_type != "Божественные сферы":
                            logger.debug(f"Пропущен оффер для {username}: тип сферы не Divine Orbs ({orb_type})")
                            continue
                    
                    amount_elem = offer.find("div", class_="tc-amount")
                    amount = re.sub(r"[^\d]", "", amount_elem.text.strip()) if amount_elem else "0"
                    logger.debug(f"Сток для {username}: {amount}")
                    
                    price_elem = offer.find("div", class_="tc-price")
                    if not price_elem:
                        continue
                    price_inner = price_elem.find("div") or price_elem.find("span")
                    price_text = price_inner.text.strip() if price_inner else price_elem.text.strip()
                    logger.debug(f"Сырой текст цены для {username}: '{price_text}'")
                    
                    if not price_text:
                        continue
                    
                    price_text_clean = re.sub(r"[^\d.]", "", price_text).strip()
                    logger.debug(f"Очищенный текст цены для {username}: '{price_text_clean}'")
                    if not re.match(r"^\d+\.\d{1,2}$", price_text_clean):
                        logger.debug(f"Пропущен оффер для {username}: неверный формат цены ({price_text_clean})")
                        continue
                    try:
                        price_rub = float(price_text_clean)
                        logger.debug(f"Цена в RUB для {username}: {price_rub}")
                        if price_rub < min_price_rub or price_rub > max_price_rub:
                            logger.debug(f"Пропущен оффер для {username}: цена вне диапазона ({price_rub} RUB)")
                            continue
                        price_usd = round(price_rub / FUNPAY_EXCHANGE_RATE, 3)
                        price_sbp = round(price_rub * SBP_COMMISSION, 2)
                        price_card = round(price_rub * CARD_COMMISSION, 2)
                        logger.debug(f"Цена для {username}: {price_rub} RUB (USD: {price_usd} $, СБП: {price_sbp} ₽, Карта: {price_card} ₽)")
                    except ValueError:
                        continue
                    
                    sellers.append({
                        "Timestamp": datetime.now(pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S"),
                        "Seller": username,
                        "Stock": amount,
                        "Price": price_usd,
                        "Currency": "RUB",
                        "Position": index
                    })
                
                except Exception as e:
                    logger.debug(f"Ошибка обработки оффера {index}: {e}")
                    continue
            
            logger.info(f"Собрано продавцов для {game}: {len(sellers)}")
            logger.info(f"Все продавцы для {game}: {len(sellers)}")
            return sellers
        except requests.exceptions.RequestException as e:
            logger.error(f"Попытка {attempt + 1} не удалась для {url}: {e}")
            if attempt == 2:
                logger.error(f"Все попытки исчерпаны для {game} (лига {league_id})")
                return []
            time.sleep(2)

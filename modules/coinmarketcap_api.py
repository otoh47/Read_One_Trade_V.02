import requests
import streamlit as st
from datetime import datetime

def get_coinmarketcap_info(symbol: str, debug=False):
    headers = {"X-CMC_PRO_API_KEY": st.secrets["coinmarketcap"]["api_key"]}

    try:
        # Step 1: Get ID from symbol
        map_url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/map?symbol={symbol.upper()}"
        map_res = requests.get(map_url, headers=headers)
        token = None
        info_data = None

        if map_res.status_code == 200 and map_res.json().get("data"):
            token = map_res.json()["data"][0]
        else:
            # Fallback to full list
            fallback_url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map?listing_status=active"
            fallback_res = requests.get(fallback_url, headers=headers)
            if fallback_res.status_code == 200:
                match = next((item for item in fallback_res.json().get("data", []) if item["symbol"].upper() == symbol.upper()), None)
                if match:
                    token = match
                else:
                    # Last fallback: try using slug
                    import json
                    try:
                        with open("slug_lookup.json") as f:
                            slug_lookup = json.load(f)
                    except:
                        slug_lookup = {}

                    slug = slug_lookup.get(symbol.upper(), symbol.lower())
                    slug_url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/info?slug={slug}"
                    slug_res = requests.get(slug_url, headers=headers)
                    if slug_res.status_code == 200:
                        slug_data = slug_res.json().get("data")
                        if slug_data:
                            token_id = list(slug_data.keys())[0]
                            token = {"id": int(token_id), "slug": slug}
                            info_data = slug_data[token_id]
                        else:
                            return None
                    else:
                        return None
            else:
                return None

        token_id = token.get("id")
        token_slug = token.get("slug", "")

        # Step 2: Get info (skip if already fetched)
        if info_data is None:
            info_url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/info?id={token_id}"
            info_res = requests.get(info_url, headers=headers)
            info_data = info_res.json().get("data", {}).get(str(token_id), {}) if info_res.status_code == 200 else {}

        # Step 3: Get quotes in IDR
        quotes_url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?id={token_id}&convert=IDR"
        quotes_res = requests.get(quotes_url, headers=headers)
        quote_data = quotes_res.json().get("data", {}).get(str(token_id), {}) if quotes_res.status_code == 200 else {}
        quote_idr = quote_data.get("quote", {}).get("IDR", {})

        # Step 4: Market pairs
        market_url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/market-pairs/latest?id={token_id}"
        market_res = requests.get(market_url, headers=headers)
        exchange_count = len(market_res.json().get("data", {}).get("market_pairs", [])) if market_res.status_code == 200 else "-"

        return {
            "total_supply": quote_data.get("total_supply", 0),
            "circulating_supply": quote_data.get("circulating_supply", 0),
            "platform": info_data.get("platform", {}).get("name", "-") if info_data.get("platform") else "-",
            "launch_year": datetime.strptime(info_data.get("date_added", ""), "%Y-%m-%dT%H:%M:%S.%fZ").year if info_data.get("date_added") else "-",
            "exchange_count": exchange_count,
            "rank": quote_data.get("cmc_rank", "-"),
            "logo": info_data.get("logo", None),
            "slug": token_slug,
            "price_idr": quote_idr.get("price", 0),
            "market_cap": quote_idr.get("market_cap", 0),
            "ath": quote_idr.get("ath", "N/A")  # jika tersedia
        }
    except Exception as e:
        if debug:
            st.error(f"❗ Exception: {e}")
        return None

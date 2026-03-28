import os

import httpx

MOEX_TIMEOUT_SECONDS = float(os.getenv("MOEX_TIMEOUT_SECONDS", "8"))


class MoexTickerNotFoundError(Exception):
    pass


class MoexPriceNotFoundError(Exception):
    pass


def get_current_price(ticker: str) -> dict:
    """
    Возвращает текущую цену бумаги с MOEX для рынка акций TQBR.
    """
    symbol = ticker.upper().strip()
    if not symbol:
        raise MoexTickerNotFoundError("Ticker is empty")

    securities_url = "https://iss.moex.com/iss/securities.json"
    marketdata_url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{symbol}.json"

    with httpx.Client(timeout=MOEX_TIMEOUT_SECONDS) as client:
        sec_resp = client.get(
            securities_url,
            params={
                "q": symbol,
                "securities.columns": "SECID,PRIMARY_BOARDID",
            },
        )
        sec_resp.raise_for_status()
        sec_json = sec_resp.json()

        found_on_tqbr = False
        sec_rows = sec_json.get("securities", {}).get("data", [])
        for row in sec_rows:
            if len(row) >= 2 and row[0] == symbol and row[1] == "TQBR":
                found_on_tqbr = True
                break

        if not found_on_tqbr:
            raise MoexTickerNotFoundError(
                f"Ticker {symbol} не найден на рынке акций MOEX (TQBR)"
            )

        md_resp = client.get(
            marketdata_url,
            params={
                "iss.meta": "off",
                "iss.only": "marketdata,securities",
                "marketdata.columns": "SECID,LAST,LCURRENTPRICE,MARKETPRICE",
                "securities.columns": "SECID,CURRENCYID",
            },
        )
        md_resp.raise_for_status()
        md_json = md_resp.json()

    marketdata_rows = md_json.get("marketdata", {}).get("data", [])
    if not marketdata_rows:
        raise MoexPriceNotFoundError(f"Нет рыночных данных для {symbol}")

    row = marketdata_rows[0]
    price = row[1] or row[2] or row[3]

    if price is None:
        raise MoexPriceNotFoundError(f"Нет текущей цены для {symbol}")

    securities_rows = md_json.get("securities", {}).get("data", [])
    currency = "RUB"
    if securities_rows and len(securities_rows[0]) >= 2 and securities_rows[0][1]:
        currency = securities_rows[0][1]

    return {
        "ticker": symbol,
        "board": "TQBR",
        "price": float(price),
        "currency": currency,
    }

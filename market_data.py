"""
Market Data Provider

Bu modül piyasa verisini sağlar.

Kuralları:
- Teknik analiz yapmaz.
- AI kullanmaz.
- Risk hesaplamaz.
- Telegram mesajı göndermez.

Sadece veri döndürür.
"""

import requests

from config import TWELVEDATA_API_KEY
from symbol_mapping import get_symbol


class MarketData:

    BASE_URL = "https://api.twelvedata.com"

    def __init__(self, provider="twelvedata"):
        self.provider = provider

    ########################################################
    # Güncel fiyat
    ########################################################

    def get_current_price(self, symbol):

        if self.provider != "twelvedata":
            raise Exception(f"{self.provider} henüz desteklenmiyor.")

        td_symbol = get_symbol(symbol, "twelvedata")

        url = f"{self.BASE_URL}/price"

        params = {
            "symbol": td_symbol,
            "apikey": TWELVEDATA_API_KEY
        }

        response = requests.get(url, params=params)

        data = response.json()

        if "price" not in data:
            raise Exception(data)

        return float(data["price"])

    ########################################################
    # Mum Verileri
    ########################################################

    def get_candles(
        self,
        symbol,
        interval="15min",
        outputsize=500
    ):

        if self.provider != "twelvedata":
            raise Exception(f"{self.provider} henüz desteklenmiyor.")

        td_symbol = get_symbol(symbol, "twelvedata")

        url = f"{self.BASE_URL}/time_series"

        params = {
            "symbol": td_symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": TWELVEDATA_API_KEY
        }

        response = requests.get(url, params=params)

        return response.json()

    ########################################################
    # Son Mum
    ########################################################

    def get_last_candle(self, symbol):

        candles = self.get_candles(symbol)

        if "values" not in candles:
            return None

        return candles["values"][0]

    ########################################################
    # Son X Mum
    ########################################################

    def get_last_candles(
        self,
        symbol,
        interval="15min",
        outputsize=200
    ):

        candles = self.get_candles(
            symbol,
            interval,
            outputsize
        )

        if "values" not in candles:
            return []

        return candles["values"]

    ########################################################
    # Günlük Hacim
    ########################################################

    def get_volume(self, symbol):

        candle = self.get_last_candle(symbol)

        if candle is None:
            return None

        return float(candle.get("volume", 0))

    ########################################################
    # Enstrüman Bilgisi
    ########################################################

    def get_symbol_info(self, symbol):

        return {
            "symbol": symbol,
            "provider": self.provider,
            "provider_symbol": get_symbol(symbol, self.provider)
        }

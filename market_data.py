"""
Market Data Provider

Tüm piyasa verileri bu dosya üzerinden alınır.

Hiçbir modül (scanner, ai, risk vs.)
doğrudan API kullanmaz.

Her şey MarketData sınıfı üzerinden çalışır.
"""

import yfinance as yf

from symbol_mapping import get_symbol


class MarketData:

    def __init__(self, provider="yfinance"):

        self.provider = provider

    ########################################################
    # Güncel fiyat
    ########################################################

    def get_current_price(self, symbol):

        if self.provider == "yfinance":

            yf_symbol = get_symbol(symbol, "yfinance")

            ticker = yf.Ticker(yf_symbol)

            data = ticker.history(
                period="1d",
                interval="1m"
            )

            if data.empty:
                return None

            return float(data["Close"].iloc[-1])

        raise Exception(f"{self.provider} desteklenmiyor.")

    ########################################################
    # Mum verisi
    ########################################################

    def get_candles(
        self,
        symbol,
        interval="15m",
        period="5d"
    ):

        if self.provider == "yfinance":

            yf_symbol = get_symbol(symbol, "yfinance")

            ticker = yf.Ticker(yf_symbol)

            data = ticker.history(
                period=period,
                interval=interval
            )

            return data

        raise Exception(f"{self.provider} desteklenmiyor.")

    ########################################################
    # Hacim
    ########################################################

    def get_volume(self, symbol):

        candles = self.get_candles(
            symbol,
            interval="1m",
            period="1d"
        )

        if candles.empty:
            return None

        return float(candles["Volume"].iloc[-1])

    ########################################################
    # Son mum
    ########################################################

    def get_last_candle(self, symbol):

        candles = self.get_candles(
            symbol,
            interval="1m",
            period="1d"
        )

        if candles.empty:
            return None

        return candles.iloc[-1]

    ########################################################
    # Son X mum
    ########################################################

    def get_last_candles(
        self,
        symbol,
        count=200,
        interval="15m",
        period="60d"
    ):

        candles = self.get_candles(
            symbol,
            interval,
            period
        )

        return candles.tail(count)

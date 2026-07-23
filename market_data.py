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

import yfinance as yf


class MarketData:

    def get_candles(self, symbol, timeframe="15m", count=500):
        """
        Belirtilen sembol için mum verilerini döndürür.
        (Şimdilik daha sonra dolduracağız.)
        """
        raise NotImplementedError

    def get_current_price(self, symbol):
        """
        Güncel fiyatı döndürür.
        """

        ticker = yf.Ticker(symbol)

        data = ticker.history(period="1d", interval="1m")

        if data.empty:
            return None

        return float(data["Close"].iloc[-1])

    def get_symbol_info(self, symbol):
        """
        Enstrüman bilgilerini döndürür.
        (Daha sonra dolduracağız.)
        """
        raise NotImplementedError

    def get_volume(self, symbol):
        """
        Güncel hacim bilgisini döndürür.
        (Daha sonra dolduracağız.)
        """
        raise NotImplementedError

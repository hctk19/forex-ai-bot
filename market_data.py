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


class MarketData:

    def get_candles(self, symbol, timeframe, count):
        """
        Belirtilen sembol için mum verilerini döndürür.
        """
        raise NotImplementedError

    def get_current_price(self, symbol):
        """
        Güncel fiyatı döndürür.
        """
        raise NotImplementedError

    def get_symbol_info(self, symbol):
        """
        Enstrüman bilgilerini döndürür.
        """
        raise NotImplementedError

    def get_volume(self, symbol):
        """
        Güncel hacim bilgisini döndürür.
        """
        raise NotImplementedError

"""
Market Scanner

Bu dosya yalnızca piyasa verisini toplar.
Karar vermez.
Risk hesaplamaz.
Telegram mesajı göndermez.
AI kullanmaz.
"""

def scan_market(symbol):
    """
    Verilen sembolü tarar ve teknik verileri döndürür.
    Şimdilik sadece iskelet.
    """

    return {
        "symbol": symbol,
        "price": None,
        "trend": None,
        "ema20": None,
        "ema50": None,
        "ema200": None,
        "rsi": None,
        "macd": None,
        "atr": None,
        "volume": None,
        "support": None,
        "resistance": None
    }

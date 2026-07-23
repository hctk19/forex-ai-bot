"""
Symbol Mapping

Botun kullandığı sembolleri,
veri sağlayıcılarının kullandığı sembollere çevirir.
"""

SYMBOLS = {
    # ==========================
    # INDEXLER
    # ==========================
    "US100": {
        "yfinance": "^NDX",
        "twelvedata": "NDX",
    },

    "US500": {
        "yfinance": "^GSPC",
        "twelvedata": "SPX",
    },

    "GER40": {
        "yfinance": "^GDAXI",
        "twelvedata": "DAX",
    },

    "UK100": {
        "yfinance": "^FTSE",
        "twelvedata": "UKX",
    },

    # ==========================
    # EMTİALAR
    # ==========================
    "XAUUSD": {
        "yfinance": "GC=F",
        "twelvedata": "XAU/USD",
    },

    "XAGUSD": {
        "yfinance": "SI=F",
        "twelvedata": "XAG/USD",
    },

    "USOIL": {
        "yfinance": "CL=F",
        "twelvedata": "WTI",
    },

    "UKOIL": {
        "yfinance": "BZ=F",
        "twelvedata": "BRENT",
    },

    # ==========================
    # FOREX
    # ==========================
    "EURUSD": {
        "yfinance": "EURUSD=X",
        "twelvedata": "EUR/USD",
    },

    "GBPUSD": {
        "yfinance": "GBPUSD=X",
        "twelvedata": "GBP/USD",
    },

    "USDJPY": {
        "yfinance": "JPY=X",
        "twelvedata": "USD/JPY",
    },

    "AUDUSD": {
        "yfinance": "AUDUSD=X",
        "twelvedata": "AUD/USD",
    },

    "USDCAD": {
        "yfinance": "CAD=X",
        "twelvedata": "USD/CAD",
    },

    "USDCHF": {
        "yfinance": "CHF=X",
        "twelvedata": "USD/CHF",
    },

    "NZDUSD": {
        "yfinance": "NZDUSD=X",
        "twelvedata": "NZD/USD",
    },

    # ==========================
    # KRİPTO
    # ==========================
    "BTCUSD": {
        "yfinance": "BTC-USD",
        "twelvedata": "BTC/USD",
    },

    "ETHUSD": {
        "yfinance": "ETH-USD",
        "twelvedata": "ETH/USD",
    },

    "SOLUSD": {
        "yfinance": "SOL-USD",
        "twelvedata": "SOL/USD",
    },
}


def get_symbol(symbol: str, provider: str = "yfinance"):
    """
    Bot sembolünü veri sağlayıcısının sembolüne çevirir.
    """

    if symbol not in SYMBOLS:
        raise ValueError(f"Desteklenmeyen sembol: {symbol}")

    if provider not in SYMBOLS[symbol]:
        raise ValueError(f"{provider} için sembol bulunamadı.")

    return SYMBOLS[symbol][provider]

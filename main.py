import os
import time
import math
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import yfinance as yf

# =========================
# ENV
# =========================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
TWELVE_KEY = os.getenv("TWELVE_KEY", "").strip()
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()

SYMBOLS = [
    s.strip() for s in os.getenv(
        "SYMBOLS",
        "XAU/USD,XAG/USD,EUR/USD,GBP/USD,USD/JPY,USD/CHF,USD/CAD,AUD/USD,NZD/USD,EUR/JPY,GBP/JPY,BTC/USD,ETH/USD"
    ).split(",") if s.strip()
]

SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "70"))
COOLDOWN_MIN = int(os.getenv("COOLDOWN_MIN", "180"))
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
MAX_SIGNALS_PER_DAY = int(os.getenv("MAX_SIGNALS_PER_DAY", "3"))

NEWS_BLOCK_BEFORE_MIN = int(os.getenv("NEWS_BLOCK_BEFORE_MIN", "45"))
NEWS_BLOCK_AFTER_MIN = int(os.getenv("NEWS_BLOCK_AFTER_MIN", "30"))

TR_TZ = ZoneInfo("Europe/Istanbul")
UTC_TZ = ZoneInfo("UTC")

last_signal_times = {}
signals_sent_today = 0
signals_day = None
forex_was_closed = False

# =========================
# HELPERS
# =========================
def log(msg: str):
    now = datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now} TRT] {msg}", flush=True)


def format_price(p):
    if p >= 1000:
        return f"{p:.2f}"
    if p >= 100:
        return f"{p:.3f}"
    if p >= 1:
        return f"{p:.5f}"
    return f"{p:.6f}"


def validate_env():
    missing = []
    if not TG_BOT_TOKEN:
        missing.append("TG_BOT_TOKEN")
    if not TG_CHAT_ID:
        missing.append("TG_CHAT_ID")
    if not TWELVE_KEY:
        missing.append("TWELVE_KEY")
    if missing:
        raise RuntimeError(f"Eksik environment değişkenleri: {', '.join(missing)}")


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text
    }
    try:
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code != 200:
            log(f"Telegram hata {r.status_code}: {r.text}")
    except Exception as e:
        log(f"Telegram gönderim hatası: {e}")


def reset_daily_counter_if_needed():
    global signals_sent_today, signals_day
    today = datetime.now(TR_TZ).date()
    if signals_day != today:
        signals_day = today
        signals_sent_today = 0
        log("Günlük sinyal sayacı sıfırlandı.")


def cooldown_ok(symbol: str):
    if symbol not in last_signal_times:
        return True
    return datetime.now(UTC_TZ) - last_signal_times[symbol] >= timedelta(minutes=COOLDOWN_MIN)
    
def is_forex_closed():
    now = datetime.now(UTC_TZ)
    weekday = now.weekday()  # 0=Mon ... 6=Sun

    # Cumartesi tamamen kapalı
    if weekday == 5:
        return True

    # Pazar 22:00 UTC'e kadar kapalı
    if weekday == 6 and now.hour < 22:
        return True

    return False

# =========================
# MARKET DATA
# =========================
def fetch_ohlc(symbol: str, interval="15min", outputsize=120):

    try:

        symbol_map = {
            "XAU/USD": "GC=F",
            "XAG/USD": "SI=F",
            "BTC/USD": "BTC-USD",
            "ETH/USD": "ETH-USD",
            "SPX": "^GSPC",
            "NAS100": "^NDX",
            "US30": "^DJI",
            "GER40": "^GDAXI",
            "UK100": "^FTSE",
            "USOIL": "CL=F",
            "UKOIL": "BZ=F",
            "NATGAS": "NG=F"
        }

        yf_symbol = symbol_map.get(symbol, symbol.replace("/", "") + "=X")

        data = yf.download(
            yf_symbol,
            interval="15m",
            period="5d",
            progress=False
        )

        candles = []

        for index, row in data.iterrows():

            candles.append({
                "datetime": str(index),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"])
            })

        return candles

    except Exception as e:
        log(f"{symbol} veri alınamadı: {e}")
        return []
    return candles
def fetch_ohlc_tf(symbol: str, interval="1h", outputsize=120):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_KEY,
        "format": "JSON"
    }

    r = requests.get(url, params=params, timeout=20)
    data = r.json()

    if "values" not in data:
        return None

    values = list(reversed(data["values"]))

    candles = []
    for v in values:
        candles.append({
            "datetime": v["datetime"],
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
        })

    return candles

# =========================
# INDICATORS
# =========================
def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for price in values[period:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val


def stddev(values, period):
    if len(values) < period:
        return None
    vals = values[-period:]
    mean = sum(vals) / period
    variance = sum((x - mean) ** 2 for x in vals) / period
    return math.sqrt(variance)


def bollinger_bands(closes, period=20, mult=2):
    mid = sma(closes, period)
    sd = stddev(closes, period)
    if mid is None or sd is None:
        return None, None, None
    upper = mid + mult * sd
    lower = mid - mult * sd
    return lower, mid, upper


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0)
        loss = abs(min(diff, 0))
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None, None, None

    macd_series = []
    for i in range(slow, len(closes) + 1):
        subset = closes[:i]
        fast_ema = ema(subset, fast)
        slow_ema = ema(subset, slow)
        macd_series.append(fast_ema - slow_ema)

    signal_line = ema(macd_series, signal)
    macd_line = macd_series[-1]
    histogram = macd_line - signal_line if signal_line is not None else None
    return macd_line, signal_line, histogram


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period
def trend_direction(closes):
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    if ema50 is None or ema200 is None:
        return "NEUTRAL"

    if ema50 > ema200:
        return "UP"
    elif ema50 < ema200:
        return "DOWN"
    else:
        return "NEUTRAL"
def premium_discount_zone(candles, lookback=50):

    if len(candles) < lookback:
        return None

    highs = [c["high"] for c in candles[-lookback:]]
    lows = [c["low"] for c in candles[-lookback:]]

    range_high = max(highs)
    range_low = min(lows)

    equilibrium = (range_high + range_low) / 2

    price = candles[-1]["close"]

    if price < equilibrium:
        return "DISCOUNT"
    else:
        return "PREMIUM"
# =========================
# PRICE ACTION FILTERS
# =========================
def liquidity_sweep_long(candles, lookback=10):
    if len(candles) < lookback + 3:
        return False
    lows = [c["low"] for c in candles[-lookback-2:-2]]
    recent_low = candles[-2]["low"]
    current_close = candles[-1]["close"]
    return recent_low < min(lows) and current_close > recent_low


def liquidity_sweep_short(candles, lookback=10):
    if len(candles) < lookback + 3:
        return False
    highs = [c["high"] for c in candles[-lookback-2:-2]]
    recent_high = candles[-2]["high"]
    current_close = candles[-1]["close"]
    return recent_high > max(highs) and current_close < recent_high


def displacement_bullish(candles):
    if len(candles) < 1:
        return False
    body = abs(candles[-1]["close"] - candles[-1]["open"])
    rng = candles[-1]["high"] - candles[-1]["low"]
    return rng > 0 and (body / rng) >= 0.65 and candles[-1]["close"] > candles[-1]["open"]

def displacement_bearish(candles):
    if len(candles) < 1:
        return False
    body = abs(candles[-1]["close"] - candles[-1]["open"])
    rng = candles[-1]["high"] - candles[-1]["low"]
    return rng > 0 and (body / rng) >= 0.65 and candles[-1]["close"] < candles[-1]["open"]


# =========================
# SMART MONEY FILTERS
# =========================
def false_breakout_bullish(candles):
    if len(candles) < 3:
        return False

    prev_high = candles[-2]["high"]
    last_high = candles[-1]["high"]
    last_close = candles[-1]["close"]

    return last_high > prev_high and last_close < prev_high


def false_breakout_bearish(candles):
    if len(candles) < 3:
        return False

    prev_low = candles[-2]["low"]
    last_low = candles[-1]["low"]
    last_close = candles[-1]["close"]

    return last_low < prev_low and last_close > prev_low


def volatility_expansion(candles, atr_val):
    if len(candles) < 2:
        return False

    last_range = candles[-1]["high"] - candles[-1]["low"]
    prev_range = candles[-2]["high"] - candles[-2]["low"]

    return last_range > prev_range * 1.5 and last_range > atr_val * 0.8

def atr_squeeze(candles, atr_val):

    if len(candles) < 10:
        return False

    recent_ranges = [(c["high"] - c["low"]) for c in candles[-8:-2]]
    avg_range = sum(recent_ranges) / len(recent_ranges)

    return avg_range < atr_val * 0.6
# =========================
# NEWS FILTER
# =========================
USD_SENSITIVE = {"XAU/USD", "XAG/USD", "BTC/USD", "ETH/USD"}

COUNTRY_TO_CCY = {
    "united states": "USD",
    "usa": "USD",
    "us": "USD",
    "euro area": "EUR",
    "european union": "EUR",
    "germany": "EUR",
    "france": "EUR",
    "united kingdom": "GBP",
    "uk": "GBP",
    "japan": "JPY",
    "canada": "CAD",
    "switzerland": "CHF",
    "australia": "AUD",
    "new zealand": "NZD",
}

def fetch_economic_calendar():
    if not FMP_API_KEY:
        log("FMP_API_KEY yok, haber filtresi kapalı.")
        return []

    today = datetime.now(UTC_TZ).date()
    start_date = today.isoformat()
    end_date = (today + timedelta(days=1)).isoformat()

    url = "https://financialmodelingprep.com/stable/economic-calendar"
    params = {
        "from": start_date,
        "to": end_date,
        "apikey": FMP_API_KEY
    }

    try:
        r = requests.get(url, params=params, timeout=20)

        if r.status_code == 402:
            log("FMP planı economic-calendar için yetkisiz. Haber filtresi devre dışı.")
            return []

        r.raise_for_status()
        data = r.json()

        if isinstance(data, list):
            return data

        log("FMP beklenmeyen veri döndürdü.")
        return []

    except Exception as e:
        log(f"Haber verisi alınamadı: {e}")
        return []


def symbol_currencies(symbol: str):
    if symbol in USD_SENSITIVE:
        return {"USD"}

    raw = symbol.replace("/", "").upper()
    if len(raw) >= 6:
        return {raw[:3], raw[3:6]}
    return set()


def is_high_impact_event(event: dict):
    text = " ".join([
        str(event.get("event", "")),
        str(event.get("name", "")),
        str(event.get("impact", "")),
        str(event.get("importance", "")),
        str(event.get("economicImpact", "")),
    ]).lower()

    strong_keywords = [
        "cpi", "consumer price", "inflation", "nfp", "non-farm",
        "fomc", "fed", "interest rate", "rate decision", "powell",
        "ecb", "boe", "boj", "employment change", "unemployment rate",
        "gdp", "ppi", "core pce", "retail sales"
    ]

    if "high" in text:
        return True

    return any(k in text for k in strong_keywords)


def parse_event_datetime(event: dict):
    candidates = [
        event.get("date"),
        event.get("datetime"),
        event.get("releaseDate"),
        event.get("publicationDate"),
    ]

    for raw in candidates:
        if not raw:
            continue

        raw = str(raw).replace("T", " ").replace("Z", "").strip()

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.replace(tzinfo=UTC_TZ)
            except ValueError:
                pass

    return None


def event_currency(event: dict):
    raw_country = str(event.get("country", "") or event.get("countryLabel", "")).strip().lower()
    raw_currency = str(event.get("currency", "")).strip().upper()

    if raw_currency in {"USD", "EUR", "GBP", "JPY", "CAD", "CHF", "AUD", "NZD"}:
        return raw_currency

    for key, val in COUNTRY_TO_CCY.items():
        if key in raw_country:
            return val

    text = " ".join([
        str(event.get("event", "")),
        str(event.get("name", "")),
    ]).lower()

    if "fed" in text or "fomc" in text or "powell" in text:
        return "USD"
    if "ecb" in text:
        return "EUR"
    if "boe" in text:
        return "GBP"
    if "boj" in text:
        return "JPY"

    return None


def news_block_for_symbol(symbol: str, events: list):
    now_utc = datetime.now(UTC_TZ)
    affected_ccys = symbol_currencies(symbol)

    for ev in events:
        ccy = event_currency(ev)
        if not ccy or ccy not in affected_ccys:
            continue

        if not is_high_impact_event(ev):
            continue

        ev_time = parse_event_datetime(ev)
        if not ev_time:
            continue

        block_start = ev_time - timedelta(minutes=NEWS_BLOCK_BEFORE_MIN)
        block_end = ev_time + timedelta(minutes=NEWS_BLOCK_AFTER_MIN)

        if block_start <= now_utc <= block_end:
            event_name = ev.get("event") or ev.get("name") or "High impact news"
            return True, f"{symbol} haber engeli: {ccy} | {event_name}"

    return False, None

def analyze_symbol(symbol: str):


closes = [c["close"] for c in candles]
last = candles[-1]
price = last["close"]

candles_1h = fetch_ohlc_tf(symbol, "1h")

closes_1h = [c["close"] for c in candles_1h] if candles_1h else None
trend_1h = trend_direction(closes_1h) if closes_1h else "NEUTRAL"

rsi_val = rsi(closes, 14)
lower, mid, upper = bollinger_bands(closes, 20, 2)
ema20 = ema(closes, 20)
ema50 = ema(closes, 50)


    closes = [c["close"] for c in candles]
    last = candles[-1]
    price = last["close"]

    rsi_val = rsi(closes, 14)
    lower, mid, upper = bollinger_bands(closes, 20, 2)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    macd_line, signal_line, histogram = macd(closes)
    atr_val = atr(candles, 14)
    if not candles or len(candles) < 50:
        return None, f"{symbol} veri yetersiz"
# spread filtresi
    spread = candles[-1]["high"] - candles[-1]["low"]

    if spread > atr_val * 2:
        return None, f"{symbol} spread çok yüksek"

    # displacement kontrolü
    current_range = candles[-1]["high"] - candles[-1]["low"]
    strong_move = current_range > atr_val * 0.8

    if current_range > atr_val * 2.5:
        return None, f"{symbol} news spike volatility"
# candle range kontrolü
last_range = candles[-1]["high"] - candles[-1]["low"]
prev_range = candles[-2]["high"] - candles[-2]["low"]

# Liquidity Sweep
prev_high = candles[-2]["high"]
prev_low = candles[-2]["low"]

last_high = candles[-1]["high"]
last_low = candles[-1]["low"]
last_close = candles[-1]["close"]

liquidity_sweep_high = last_high > prev_high and last_close < prev_high
liquidity_sweep_low = last_low < prev_low and last_close > prev_low

if last_range < atr_val * 0.25 and prev_range < atr_val * 0.25:
    return None, f"{symbol} volatilite düşük"

score_long = 0
score_short = 0

reasons_long = []
reasons_short = []

# TREND REGIME FILTER


bb_range = (upper - lower)
bb_pos = (price - lower) / bb_range if bb_range != 0 else 0.5
atr_ratio = atr_val / price if price != 0 else 0

pd_zone = premium_discount_zone(candles)
squeeze = atr_squeeze(candles, atr_val)

# ================= LONG =================

if rsi_val <= 32:
    score_long += 18
    reasons_long.append("RSI güçlü dip")

elif rsi_val <= 36:
    score_long += 12
    reasons_long.append("RSI dip bölgesi")

    if price <= lower * 1.003:
        score_long += 12
        reasons_long.append("Alt Bollinger teması")
    elif bb_pos <= 0.20:
        score_long += 8
        reasons_long.append("Band altına yakın")

    if ema20 > ema50:
        score_long += 8
        reasons_long.append("EMA trend yukarı")

    if histogram is not None and histogram > 0:
        score_long += 6
        reasons_long.append("MACD pozitif")

    if atr_ratio >= 0.0025:
        score_long += 10
        reasons_long.append("Volatilite yeterli")

    if atr_ratio >= 0.0040:
        score_long += 5
        reasons_long.append("Volatilite güçlü")

    if closes[-1] > closes[-2]:
        score_long += 4
        reasons_long.append("Son mum toparlanıyor")

    if liquidity_sweep_long(candles):
        score_long += 18
        reasons_long.append("Likidite sweep long")

    if false_breakout_bearish(candles):
        score_long += 10
        reasons_long.append("Fake breakout aşağı")

    if volatility_expansion(candles, atr_val):
        score_long += 8
        reasons_long.append("Volatilite patlaması")
    if squeeze:
        score_long += 6
        reasons_long.append("ATR squeeze breakout")
    if displacement_bullish(candles):
        score_long += 16
        reasons_long.append("Bullish displacement")
        
    if pd_zone == "DISCOUNT":
        score_long += 12
        reasons_long.append("Discount zone")
        
    if trend_1h == "UP":
        score_long += 10
        reasons_long.append("1H trend yukarı")
    # ================= SHORT =================

    if rsi_val >= 68:
        score_short += 18
        reasons_short.append("RSI güçlü tepe")
    elif rsi_val >= 64:
        score_short += 12
        reasons_short.append("RSI tepe bölgesi")

    if price >= upper * 0.997:
        score_short += 12
        reasons_short.append("Üst Bollinger teması")
    elif bb_pos >= 0.80:
        score_short += 8
        reasons_short.append("Band üstüne yakın")

    if ema20 < ema50:
        score_short += 8
        reasons_short.append("EMA trend aşağı")

    if histogram is not None and histogram < 0:
        score_short += 6
        reasons_short.append("MACD negatif")

    if atr_ratio >= 0.0025:
        score_short += 10
        reasons_short.append("Volatilite yeterli")

    if atr_ratio >= 0.0040:
        score_short += 5
        reasons_short.append("Volatilite güçlü")

    if closes[-1] < closes[-2]:
        score_short += 4
        reasons_short.append("Son mum zayıf")

    if liquidity_sweep_short(candles):
        score_short += 18
        reasons_short.append("Likidite sweep short")

    if false_breakout_bullish(candles):
        score_short += 10
        reasons_short.append("Fake breakout yukarı")

    if volatility_expansion(candles, atr_val):
        score_short += 8
        reasons_short.append("Volatilite patlaması")

    if squeeze:
        score_short += 6
        reasons_short.append("ATR squeeze breakout")    
        
    if displacement_bearish(candles):
        score_short += 16
        reasons_short.append("Bearish displacement")
        
    if pd_zone == "PREMIUM":
        score_short += 12
        reasons_short.append("Premium zone")
        
    if trend_1h == "DOWN":
        score_short += 10
        reasons_short.append("1H trend aşağı")

    direction = None
    score = 0
    reasons = []

    if score_long >= SCORE_THRESHOLD and score_long > score_short:
        direction = "BUY"
        score = score_long
        reasons = reasons_long

    elif score_short >= SCORE_THRESHOLD and score_short > score_long:
        direction = "SELL"
        score = score_short
        reasons = reasons_short

    else:
        debug = (
            f"{symbol} setup yok | "
            f"LONG={score_long} SHORT={score_short} "
            f"RSI={rsi_val:.2f} ATR%={(atr_ratio * 100):.2f} "
            f"Price={format_price(price)}"
        )
        return None, debug

    if direction == "BUY":
        sl = price - atr_val * 1.5
        tp = price + atr_val * 3.0
    else:
        sl = price + atr_val * 1.5
        tp = price - atr_val * 3.0

    signal = {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "price": price,
        "sl": sl,
        "tp": tp,
        "rsi": rsi_val,
        "atr_ratio": atr_ratio,
        "reasons": reasons,
    }

    return signal, f"{symbol} sinyal bulundu | {direction} | skor={score}"
def build_message(signal: dict):
    reasons = ", ".join(signal["reasons"][:5])
    return (
        f"✅ Güçlü setup\n\n"
        f"Parite: {signal['symbol']}\n"
        f"Yön: {signal['direction']}\n"
        f"Entry: {format_price(signal['price'])}\n"
        f"SL: {format_price(signal['sl'])}\n"
        f"TP: {format_price(signal['tp'])}\n"
        f"RSI: {signal['rsi']:.2f}\n"
        f"ATR%: {(signal['atr_ratio'] * 100):.2f}\n"
        f"Skor: {signal['score']}\n"
        f"Neden: {reasons}"
    )


# =========================
# MAIN SCAN
# =========================

def fetch_forex_news():
    try:
        url = "https://api.tradingeconomics.com/calendar?c=guest:guest&f=json"
        r = requests.get(url, timeout=20)

        if r.status_code != 200:
            log(f"Haber API hata: {r.status_code}")
            return []

        data = r.json()
        events = []

        for event in data:

            title = str(event.get("Event", "")).lower()
            importance = str(event.get("Importance", "")).lower()
            country = str(event.get("Country", "")).upper()
            date = event.get("Date")

            if not date:
                continue

            try:
                ev_time = datetime.fromisoformat(date.replace("Z", "+00:00"))
            except:
                continue

            if "high" in importance or any(word in title for word in [
                "interest rate",
                "cpi",
                "inflation",
                "non farm",
                "fomc",
                "fed",
                "powell",
                "gdp",
                "ppi",
                "employment"
            ]):

                events.append({
                    "title": title,
                    "country": country,
                    "time": ev_time
                })

        return events

    except Exception as e:
        log(f"Haber alınamadı: {e}")
        return []
def run_scan():
    global signals_sent_today
    global forex_was_closed

    reset_daily_counter_if_needed()

    if signals_sent_today >= MAX_SIGNALS_PER_DAY:
        log("Günlük sinyal limiti doldu.")
        return

    log("Tarama başladı.")

    if is_forex_closed():

        if not forex_was_closed:
            log("Forex piyasası kapalı.")
            send_telegram("🔴 Forex piyasası kapalı (hafta sonu). Bot çalışıyor.")
            forex_was_closed = True

    else:

        if forex_was_closed:
            send_telegram("🟢 Forex piyasası açıldı. Bot taramaya başladı.")
            forex_was_closed = False

    events = fetch_economic_calendar()
    candidates = []

    for symbol in SYMBOLS:
        try:
            if signals_sent_today >= MAX_SIGNALS_PER_DAY:
                break

            if not cooldown_ok(symbol):
                log(f"{symbol} cooldown aktif, geçildi.")
                continue

            blocked, reason = news_block_for_symbol(symbol, events)
            if blocked:
                log(reason)
                continue

            signal, info = analyze_symbol(symbol)
            log(info)
            time.sleep(0.5)

            if signal:
                candidates.append(signal)

        except Exception as e:
            log(f"{symbol} analiz hatası: {e}")
            log(traceback.format_exc())

    candidates.sort(key=lambda x: x["score"], reverse=True)

    for signal in candidates:
        if signals_sent_today >= MAX_SIGNALS_PER_DAY:
            break

        send_telegram(build_message(signal))
        last_signal_times[signal["symbol"]] = datetime.now(UTC_TZ)
        signals_sent_today += 1
        log(f"{signal['symbol']} Telegram'a gönderildi. Günlük adet: {signals_sent_today}")


# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    validate_env()
    log("Forex Deep Analyzer PRO başlıyor.")
    send_telegram("✅ Forex Deep Analyzer PRO aktif. Güçlü setup gelirse yazacağım.")

    while True:
        try:
            run_scan()
        except Exception as e:
            log(f"Ana döngü hatası: {e}")
            log(traceback.format_exc())

        log(f"{SCAN_INTERVAL_SEC} saniye bekleniyor.")
        time.sleep(SCAN_INTERVAL_SEC)









import os
import time
import math
import requests
import traceback
from datetime import datetime, timedelta

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
TWELVE_KEY = os.getenv("TWELVE_KEY", "").strip()

SYMBOLS = [s.strip() for s in os.getenv(
    "SYMBOLS",
    "XAU/USD,EUR/USD,GBP/USD,USD/JPY,EUR/JPY,GBP/JPY,AUD/USD,USD/CAD,NZD/USD"
).split(",") if s.strip()]

SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "72"))
COOLDOWN_MIN = int(os.getenv("COOLDOWN_MIN", "90"))
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))

last_signal_times = {}

def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC] {msg}", flush=True)

def send_telegram(text: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log("Telegram bilgileri eksik, mesaj gönderilemedi.")
        return

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text
    }

    try:
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code != 200:
            log(f"Telegram hata: {r.status_code} - {r.text}")
    except Exception as e:
        log(f"Telegram gönderim hatası: {e}")

def fetch_ohlc(symbol: str, interval="15min", outputsize=120):
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
        raise ValueError(f"{symbol} veri alınamadı: {data}")

    values = list(reversed(data["values"]))  # eski -> yeni

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
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

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

def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None, None, None
    macd_line_series = []

    for i in range(slow, len(closes) + 1):
        subset = closes[:i]
        fast_ema = ema(subset, fast)
        slow_ema = ema(subset, slow)
        macd_line_series.append(fast_ema - slow_ema)

    signal_line = ema(macd_line_series, signal)
    macd_line = macd_line_series[-1]
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

def cooldown_ok(symbol: str):
    if symbol not in last_signal_times:
        return True
    return datetime.utcnow() - last_signal_times[symbol] >= timedelta(minutes=COOLDOWN_MIN)

def format_price(p):
    if p >= 100:
        return f"{p:.2f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.6f}"

def analyze_symbol(symbol: str):
    candles = fetch_ohlc(symbol)
    closes = [c["close"] for c in candles]
    last = candles[-1]
    price = last["close"]

    rsi_val = rsi(closes, 14)
    lower, mid, upper = bollinger_bands(closes, 20, 2)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    macd_line, signal_line, histogram = macd(closes)
    atr_val = atr(candles, 14)

    if None in [rsi_val, lower, mid, upper, ema20, ema50, macd_line, signal_line, histogram, atr_val]:
        return None, "Veri yetersiz"

    score_long = 0
    score_short = 0
    reasons_long = []
    reasons_short = []

    bb_pos = (price - lower) / (upper - lower) if upper != lower else 0.5

    # LONG skor
    if rsi_val <= 32:
        score_long += 30
        reasons_long.append("RSI güçlü dip")
    elif rsi_val <= 36:
        score_long += 20
        reasons_long.append("RSI dip bölgesi")

    if price <= lower * 1.003:
        score_long += 25
        reasons_long.append("Alt Bollinger teması")
    elif bb_pos <= 0.20:
        score_long += 15
        reasons_long.append("Band altına yakın")

    if ema20 > ema50:
        score_long += 10
        reasons_long.append("EMA trend desteği")

    if histogram is not None and histogram > 0:
        score_long += 10
        reasons_long.append("MACD pozitif")

    if atr_val / price >= 0.0025:
        score_long += 8
        reasons_long.append("Yeterli volatilite")

    if closes[-1] > closes[-2]:
        score_long += 5
        reasons_long.append("Son mum toparlanıyor")

    # SHORT skor
    if rsi_val >= 68:
        score_short += 30
        reasons_short.append("RSI güçlü tepe")
    elif rsi_val >= 64:
        score_short += 20
        reasons_short.append("RSI tepe bölgesi")

    if price >= upper * 0.997:
        score_short += 25
        reasons_short.append("Üst Bollinger teması")
    elif bb_pos >= 0.80:
        score_short += 15
        reasons_short.append("Band üstüne yakın")

    if ema20 < ema50:
        score_short += 10
        reasons_short.append("EMA trend desteği")

    if histogram is not None and histogram < 0:
        score_short += 10
        reasons_short.append("MACD negatif")

    if atr_val / price >= 0.0025:
        score_short += 8
        reasons_short.append("Yeterli volatilite")

    if closes[-1] < closes[-2]:
        score_short += 5
        reasons_short.append("Son mum zayıflıyor")

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
            f"RSI={rsi_val:.2f} Price={format_price(price)}"
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
        "reasons": reasons
    }

    return signal, f"{symbol} sinyal bulundu"

def build_message(signal: dict):
    reasons = ", ".join(signal["reasons"][:4])

    return (
        f"✅ Güçlü forex setup\n\n"
        f"Parite: {signal['symbol']}\n"
        f"Yön: {signal['direction']}\n"
        f"Entry: {format_price(signal['price'])}\n"
        f"SL: {format_price(signal['sl'])}\n"
        f"TP: {format_price(signal['tp'])}\n"
        f"RSI: {signal['rsi']:.2f}\n"
        f"Skor: {signal['score']}\n"
        f"Neden: {reasons}"
    )

def run_scan():
    log("Tarama başladı.")
    for symbol in SYMBOLS:
        try:
            if not cooldown_ok(symbol):
                log(f"{symbol} cooldown aktif, geçildi.")
                continue

            signal, info = analyze_symbol(symbol)
            log(info)

            if signal:
                msg = build_message(signal)
                send_telegram(msg)
                last_signal_times[symbol] = datetime.utcnow()
                log(f"{symbol} Telegram'a gönderildi.")

        except Exception as e:
            log(f"{symbol} analiz hatası: {e}")
            log(traceback.format_exc())

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

if __name__ == "__main__":
    validate_env()
    log("Forex Deep Analyzer v3 başlıyor.")
    send_telegram("✅ Forex Deep Analyzer v3 aktif. Güçlü setup gelirse yazacağım.")

    while True:
        try:
            run_scan()
        except Exception as e:
            log(f"Ana döngü hatası: {e}")
            log(traceback.format_exc())

        log(f"{SCAN_INTERVAL_SEC} saniye bekleniyor.")
        time.sleep(SCAN_INTERVAL_SEC)

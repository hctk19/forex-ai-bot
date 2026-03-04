import os
import time
import math
import requests
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
TWELVE_KEY = os.getenv("TWELVE_KEY", "").strip()

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "XAU/USD,EUR/USD,GBP/USD,USD/JPY").split(",")]
TF_SIGNAL = os.getenv("TF_SIGNAL", "1h")      # sinyal timeframe
TF_BIAS   = os.getenv("TF_BIAS", "4h")        # bias timeframe
SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "75"))
COOLDOWN_MIN = int(os.getenv("COOLDOWN_MIN", "120"))
LOOP_SEC = int(os.getenv("LOOP_SEC", "30"))

if not (TG_BOT_TOKEN and TG_CHAT_ID and TWELVE_KEY):
    raise RuntimeError("Env eksik: TG_BOT_TOKEN, TG_CHAT_ID, TWELVE_KEY")

_last_alert = {}  # symbol -> epoch

def tg_send(text: str):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=15).raise_for_status()
    except Exception as e:
        print("Telegram error:", e)

def twelve_fetch(symbol: str, interval: str, outputsize: int = 300) -> pd.DataFrame | None:
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_KEY,
        "format": "JSON",
    }
    r = requests.get(url, params=params, timeout=20)
    js = r.json()
    if "values" not in js:
        # rate limit veya sembol hatası olabilir
        print("TwelveData error:", js)
        return None
    df = pd.DataFrame(js["values"])
    for c in ["open","high","low","close"]:
        df[c] = df[c].astype(float)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    return df

def sma(s, n): return s.rolling(n).mean()

def atr(df, n=14):
    h,l,c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def adx(df, n=14):
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([(high-low), (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atrn = tr.rolling(n).mean()
    plus_di = 100 * pd.Series(plus_dm).rolling(n).mean() / atrn
    minus_di = 100 * pd.Series(minus_dm).rolling(n).mean() / atrn
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).replace([np.inf, -np.inf], np.nan)
    return dx.rolling(n).mean()

def bb_width(df, n=20, k=2.0):
    m = df["close"].rolling(n).mean()
    sd = df["close"].rolling(n).std()
    upper = m + k*sd
    lower = m - k*sd
    width = (upper - lower) / m
    return width

def gdelt_shock_score(hours=3) -> tuple[int, list[str], str]:
    """
    Returns (shock_score 0-80, top_titles, tag)
    tag: "RISK_OFF" / "OIL" / "MIXED" / "NONE"
    """
    q = "(attack OR missile OR war OR strike OR bombing OR sanction OR opec OR oil OR pipeline OR invasion OR drone)"
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": q, "mode": "ArtList", "format": "json", "maxrecords": 50, "sort": "HybridRel", "timespan": f"{hours}h"}
    try:
        js = requests.get(url, params=params, timeout=20).json()
        arts = js.get("articles", []) or []
        titles = [a.get("title","")[:120] for a in arts[:8]]
        text = " ".join([a.get("title","") for a in arts]).lower()

        score = 0
        risk = 0
        oil = 0
        if any(k in text for k in ["attack","missile","invasion","war","bombing","strike","drone"]):
            score += 25; risk += 1
        if any(k in text for k in ["sanction","nuclear","terror"]):
            score += 15; risk += 1
        if any(k in text for k in ["pipeline","opec","oil","tanker","refinery"]):
            score += 15; oil += 1

        score += min(20, (len(arts)//3)*5)

        tag = "NONE"
        if score >= 20:
            if risk and oil: tag = "MIXED"
            elif risk: tag = "RISK_OFF"
            elif oil: tag = "OIL"
            else: tag = "MIXED"

        return min(80, score), titles, tag
    except Exception as e:
        print("GDELT error:", e)
        return 0, [], "NONE"

def usd_strength_proxy(tf="1h") -> float:
    """
    -1..+1 arası kaba USD gücü.
    EURUSD down => USD strong
    GBPUSD down => USD strong
    USDJPY up  => USD strong
    """
    pairs = ["EUR/USD", "GBP/USD", "USD/JPY"]
    rets = {}
    for p in pairs:
        df = twelve_fetch(p, tf, 60)
        if df is None or len(df) < 3:
            continue
        last = float(df.iloc[-1]["close"])
        prev = float(df.iloc[-2]["close"])
        rets[p] = (last - prev) / prev

    s = 0.0
    if "EUR/USD" in rets: s += -np.sign(rets["EUR/USD"])
    if "GBP/USD" in rets: s += -np.sign(rets["GBP/USD"])
    if "USD/JPY" in rets: s += +np.sign(rets["USD/JPY"])
    return float(np.clip(s/3.0, -1, 1))

def sweep_displacement(df: pd.DataFrame, lookback=40) -> tuple[bool,bool,str]:
    w = df.iloc[-lookback:]
    hi = float(w["high"].max())
    lo = float(w["low"].min())
    last = df.iloc[-1]
    o,h,l,c = map(float, (last["open"], last["high"], last["low"], last["close"]))
    body = abs(c-o)
    rng = max(1e-9, h-l)
    body_ratio = body / rng

    long_ok  = (l < lo) and (c > lo) and (c > o) and (body_ratio > 0.55)
    short_ok = (h > hi) and (c < hi) and (c < o) and (body_ratio > 0.55)
    why = f"range_hi={hi:.5f} range_lo={lo:.5f} body_ratio={body_ratio:.2f}"
    return long_ok, short_ok, why

def in_session_tr():
    # kaba: TR saatine göre London+NY ağırlık
    hr = time.localtime().tm_hour  # server local; Render UTC olabilir. Sinyal için kritik değil.
    # Yine de tamamen kapatmıyoruz, sadece skor katkısı yapıyoruz.
    return 8 <= hr <= 20

def can_alert(symbol: str) -> bool:
    t = _last_alert.get(symbol, 0)
    return (time.time() - t) >= COOLDOWN_MIN * 60

def mark_alert(symbol: str):
    _last_alert[symbol] = time.time()

def analyze_symbol(sym: str) -> dict | None:
    df1 = twelve_fetch(sym, TF_SIGNAL, 320)
    df4 = twelve_fetch(sym, TF_BIAS,   320)
    if df1 is None or df4 is None or len(df1) < 120 or len(df4) < 120:
        return None

    df1["ma50"] = sma(df1["close"], 50)
    df1["atr14"] = atr(df1, 14)
    df1["adx14"] = adx(df1, 14)
    df1["bbw"] = bb_width(df1, 20, 2.0)

    df4["ma50"] = sma(df4["close"], 50)

    last = df1.iloc[-1]
    prev = df1.iloc[-2]
    close = float(last["close"])

    ma50 = float(last["ma50"])
    atr14 = float(last["atr14"]) if not np.isnan(last["atr14"]) else None
    adx14 = float(last["adx14"]) if not np.isnan(last["adx14"]) else None
    bbw = float(last["bbw"]) if not np.isnan(last["bbw"]) else None
    if atr14 is None or adx14 is None or bbw is None or np.isnan(ma50):
        return None

    # H4 bias
    ma50_4h = float(df4.iloc[-1]["ma50"])
    close_4h = float(df4.iloc[-1]["close"])
    bias_up = close_4h > ma50_4h
    bias_dn = close_4h < ma50_4h

    # MA slope (H1)
    ma_slope = float(df1["ma50"].iloc[-1] - df1["ma50"].iloc[-11]) if not np.isnan(df1["ma50"].iloc[-11]) else 0.0

    long_sweep, short_sweep, sweep_why = sweep_displacement(df1, lookback=40)

    # skor
    score = 0
    reasons = []

    # rejim: adx + bb width
    if adx14 >= 22:
        score += 15; reasons.append(f"ADX trend {adx14:.1f}")
    elif adx14 <= 18:
        score += 6; reasons.append(f"ADX düşük {adx14:.1f} (range riski)")
    else:
        score += 10; reasons.append(f"ADX orta {adx14:.1f}")

    if bbw <= 0.012:
        score += 6; reasons.append("BB dar (sıkışma)")
    else:
        score += 10; reasons.append("BB açılmış (vol var)")

    if abs(ma_slope) > (atr14 * 0.05):
        score += 10; reasons.append("MA50 eğim güçlü")
    else:
        score += 3; reasons.append("MA50 eğim zayıf")

    side = None
    if long_sweep and bias_up and close > ma50:
        side = "LONG"
        score += 35
        reasons.append("Dip sweep + displacement + trend uyum")
    elif short_sweep and bias_dn and close < ma50:
        side = "SHORT"
        score += 35
        reasons.append("Tepe sweep + displacement + trend uyum")
    else:
        return None  # setup yoksa sessizlik

    # SL/TP (ATR bazlı, RR~1:2)
    sl_dist = atr14 * 1.2
    if side == "LONG":
        sl = close - sl_dist
        tp = close + sl_dist * 2.0
    else:
        sl = close + sl_dist
        tp = close - sl_dist * 2.0

    # session bonus (tam kapatma yok)
    if in_session_tr():
        score += 5
        reasons.append("Seans zamanı (+)")

    ret = (close - float(prev["close"])) / float(prev["close"])

    return {
        "symbol": sym,
        "side": side,
        "price": close,
        "sl": sl,
        "tp": tp,
        "score": int(score),
        "reasons": "; ".join(reasons),
        "extra": sweep_why,
        "ret": ret,
        "bias": "UP" if bias_up else "DOWN" if bias_dn else "FLAT"
    }

def main():
    tg_send("✅ Forex Deep Analyzer çalıştı. Setup yakalanınca yazar; yoksa sessiz.")
    while True:
        try:
            shock, titles, tag = gdelt_shock_score(hours=3)
            usd = usd_strength_proxy(tf=TF_SIGNAL)

            for sym in SYMBOLS:
                if not can_alert(sym):
                    continue

                res = analyze_symbol(sym)
                if not res:
                    continue

                score = res["score"]

                # Haber/makro etkisi (kaba ama işe yarar)
                if shock >= 30:
                    score += 10
                if tag == "RISK_OFF":
                    # risk-off: genelde Gold long, EUR/GBP short lehine
                    if res["symbol"] == "XAU/USD" and res["side"] == "LONG":
                        score += 8
                    if res["symbol"] in ["EUR/USD","GBP/USD"] and res["side"] == "SHORT":
                        score += 8

                # USD proxy desteği
                if res["symbol"] in ["EUR/USD","GBP/USD"] and res["side"] == "SHORT" and usd > 0:
                    score += 10
                if res["symbol"] in ["EUR/USD","GBP/USD"] and res["side"] == "LONG" and usd < 0:
                    score += 10

                if score >= SCORE_THRESHOLD:
                    msg = (
                        f"🚨 SETUP YAKALANDI\n"
                        f"Symbol: {res['symbol']} | Bias(H4): {res['bias']}\n"
                        f"Yön: {res['side']}\n"
                        f"Anlık fiyat: {res['price']:.5f}\n"
                        f"SL: {res['sl']:.5f}\n"
                        f"TP: {res['tp']:.5f} (RR≈1:2)\n"
                        f"Skor: {score}/100\n"
                        f"Haber şok: {shock}/80 ({tag}) | USD proxy: {usd:.2f}\n"
                        f"Neden: {res['reasons']}\n"
                        f"Detay: {res['extra']}\n"
                    )
                    if titles:
                        msg += "🗞 Son başlıklar:\n- " + "\n- ".join(titles[:3])

                    tg_send(msg)
                    mark_alert(sym)

            time.sleep(LOOP_SEC)

        except Exception as e:
            print("Loop error:", e)
            time.sleep(10)

if __name__ == "__main__":
    main()
import os, time, threading, math
import requests
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer

load_dotenv()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN","").strip()
TG_CHAT_ID   = os.getenv("TG_CHAT_ID","").strip()
TWELVE_KEY   = os.getenv("TWELVE_KEY","").strip()

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS","XAU/USD,EUR/USD,GBP/USD,USD/JPY").split(",") if s.strip()]
TF_SIGNAL = os.getenv("TF_SIGNAL","1h")   # entry timeframe
TF_BIAS   = os.getenv("TF_BIAS","4h")     # trend timeframe

SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD","78"))  # v2: daha seçici
COOLDOWN_MIN    = int(os.getenv("COOLDOWN_MIN","120"))
LOOP_SEC        = int(os.getenv("LOOP_SEC","45"))

if not (TG_BOT_TOKEN and TG_CHAT_ID and TWELVE_KEY):
    raise RuntimeError("Eksik ENV: TG_BOT_TOKEN, TG_CHAT_ID, TWELVE_KEY")

_last_alert = {}

# ---------- Telegram ----------
def tg_send(text: str):
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=15).raise_for_status()
    except Exception as e:
        print("Telegram error:", e)

# ---------- TwelveData ----------
def twelve_fetch(symbol: str, interval: str, outputsize: int = 400) -> pd.DataFrame | None:
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": symbol, "interval": interval, "outputsize": outputsize, "apikey": TWELVE_KEY, "format":"JSON"}
    try:
        js = requests.get(url, params=params, timeout=20).json()
    except Exception as e:
        print("TwelveData network error:", e)
        return None

    if "values" not in js:
        print("TwelveData error:", js)
        return None

    df = pd.DataFrame(js["values"])
    for c in ["open","high","low","close"]:
        df[c] = df[c].astype(float)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.sort_values("datetime").reset_index(drop=True)

# ---------- Indicators ----------
def sma(s, n): return s.rolling(n).mean()
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    rs = up.rolling(n).mean() / down.rolling(n).mean()
    return 100 - (100/(1+rs))

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
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).replace([np.inf,-np.inf], np.nan)
    return dx.rolling(n).mean()

def bb_width(df, n=20, k=2.0):
    m = df["close"].rolling(n).mean()
    sd = df["close"].rolling(n).std()
    upper = m + k*sd
    lower = m - k*sd
    return (upper - lower) / m

# ---------- News shock (GDELT) ----------
def gdelt_shock_score(hours=3) -> tuple[int, list[str], str]:
    q = "(attack OR missile OR war OR strike OR bombing OR sanction OR opec OR oil OR pipeline OR invasion OR drone OR fed OR inflation OR rates)"
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": q, "mode": "ArtList", "format":"json", "maxrecords": 50, "sort":"HybridRel", "timespan": f"{hours}h"}
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
        # makro kelimeler (FED/rates)
        if any(k in text for k in ["fed","rates","inflation","cpi","powell"]):
            score += 10

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

# ---------- USD strength proxy ----------
def usd_strength_proxy(tf="1h") -> float:
    pairs = ["EUR/USD","GBP/USD","USD/JPY"]
    rets={}
    for p in pairs:
        df=twelve_fetch(p, tf, 80)
        if df is None or len(df)<3: 
            continue
        last=float(df.iloc[-1]["close"]); prev=float(df.iloc[-2]["close"])
        rets[p]=(last-prev)/prev
    s=0.0
    if "EUR/USD" in rets: s += -np.sign(rets["EUR/USD"])
    if "GBP/USD" in rets: s += -np.sign(rets["GBP/USD"])
    if "USD/JPY" in rets: s += +np.sign(rets["USD/JPY"])
    return float(np.clip(s/3.0, -1, 1))

# ---------- Setup: sweep+displacement ----------
def sweep_displacement(df: pd.DataFrame, lookback=40):
    w=df.iloc[-lookback:]
    hi=float(w["high"].max())
    lo=float(w["low"].min())
    last=df.iloc[-1]
    o,h,l,c = map(float,(last["open"],last["high"],last["low"],last["close"]))
    body=abs(c-o); rng=max(1e-9,h-l)
    br=body/rng
    long_ok=(l<lo) and (c>lo) and (c>o) and (br>0.55)
    short_ok=(h>hi) and (c<hi) and (c<o) and (br>0.55)
    return long_ok, short_ok, f"range_hi={hi:.5f} range_lo={lo:.5f} body_ratio={br:.2f}"

def can_alert(sym):
    t=_last_alert.get(sym,0)
    return (time.time()-t) >= COOLDOWN_MIN*60

def mark_alert(sym):
    _last_alert[sym]=time.time()

def session_bonus():
    # küçük bonus; Render UTC olabilir
    hr=time.localtime().tm_hour
    return 5 if 8<=hr<=20 else 0

# ---------- Analysis core ----------
def analyze_symbol(sym: str):
    df1 = twelve_fetch(sym, TF_SIGNAL, 420)
    df4 = twelve_fetch(sym, TF_BIAS,   420)
    if df1 is None or df4 is None or len(df1)<220 or len(df4)<220:
        return None

    # TF_SIGNAL indicators
    df1["MA50"] = sma(df1["close"],50)
    df1["EMA200"] = ema(df1["close"],200)
    df1["RSI14"] = rsi(df1["close"],14)
    df1["ATR14"] = atr(df1,14)
    df1["ADX14"] = adx(df1,14)
    df1["BBW"]   = bb_width(df1,20,2.0)

    # TF_BIAS indicators
    df4["EMA200"] = ema(df4["close"],200)
    df4["MA50"] = sma(df4["close"],50)

    last = df1.iloc[-1]
    close = float(last["close"])

    # NaN guard
    if any(np.isnan(last[x]) for x in ["MA50","EMA200","RSI14","ATR14","ADX14","BBW"]):
        return None

    ma50=float(last["MA50"]); ema200=float(last["EMA200"])
    rsi14=float(last["RSI14"])
    atr14=float(last["ATR14"])
    adx14=float(last["ADX14"])
    bbw=float(last["BBW"])

    # Bias TF (H4)
    close4=float(df4.iloc[-1]["close"])
    ema200_4=float(df4.iloc[-1]["EMA200"])
    ma50_4=float(df4.iloc[-1]["MA50"])
    bias_up = (close4 > ema200_4) and (close4 > ma50_4)
    bias_dn = (close4 < ema200_4) and (close4 < ma50_4)

    # MA slope (H1)
    ma_slope = float(df1["MA50"].iloc[-1] - df1["MA50"].iloc[-11]) if not np.isnan(df1["MA50"].iloc[-11]) else 0.0

    long_sweep, short_sweep, sweep_why = sweep_displacement(df1, 40)

    score=0
    reasons=[]

    # Trend regime
    if adx14 >= 22:
        score += 12; reasons.append(f"ADX trend {adx14:.1f}")
    elif adx14 <= 18:
        score += 5;  reasons.append(f"ADX düşük {adx14:.1f}")
    else:
        score += 8;  reasons.append(f"ADX orta {adx14:.1f}")

    # Volatility filter
    if bbw <= 0.012:
        score += 6; reasons.append("BB dar (sıkışma)")
    else:
        score += 9; reasons.append("BB geniş (vol)")

    # MA slope
    if abs(ma_slope) > (atr14*0.05):
        score += 9; reasons.append("MA50 eğim güçlü")
    else:
        score += 3; reasons.append("MA50 eğim zayıf")

    # Momentum (RSI) — yumuşak
    if rsi14 <= 40:
        score += 6; reasons.append(f"RSI düşük {rsi14:.1f} (long lehine)")
    elif rsi14 >= 60:
        score += 6; reasons.append(f"RSI yüksek {rsi14:.1f} (short lehine)")
    else:
        score += 2; reasons.append(f"RSI nötr {rsi14:.1f}")

    # Primary setup decision
    side=None
    if long_sweep and bias_up and (close > ma50) and (close > ema200):
        side="LONG"
        score += 35; reasons.append("Sweep+displacement + trend uyum (LONG)")
    elif short_sweep and bias_dn and (close < ma50) and (close < ema200):
        side="SHORT"
        score += 35; reasons.append("Sweep+displacement + trend uyum (SHORT)")
    else:
        return None

    # Session bonus
    sb=session_bonus()
    if sb:
        score += sb; reasons.append("Seans bonus (+)")

    # SL/TP ATR based (RR 1:2)
    sl_dist = atr14 * 1.2
    if side=="LONG":
        sl = close - sl_dist
        tp = close + sl_dist*2.0
    else:
        sl = close + sl_dist
        tp = close - sl_dist*2.0

    return {
        "symbol": sym,
        "side": side,
        "price": close,
        "sl": sl,
        "tp": tp,
        "score": int(score),
        "bias": "UP" if bias_up else "DOWN" if bias_dn else "FLAT",
        "why": "; ".join(reasons),
        "extra": sweep_why
    }

# ---------- Loop ----------
def run_loop():
    tg_send("✅ Forex Deep Analyzer v2 aktif. Setup yakalanınca yazar, yoksa susar.")
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

                # News/macro booster
                if shock >= 30: score += 10
                if tag == "RISK_OFF":
                    if res["symbol"] == "XAU/USD" and res["side"] == "LONG": score += 8
                    if res["symbol"] in ["EUR/USD","GBP/USD"] and res["side"] == "SHORT": score += 8

                # USD proxy alignment
                if res["symbol"] in ["EUR/USD","GBP/USD"] and res["side"] == "SHORT" and usd > 0: score += 10
                if res["symbol"] in ["EUR/USD","GBP/USD"] and res["side"] == "LONG"  and usd < 0: score += 10

                if score >= SCORE_THRESHOLD:
                    msg = (
                        f"🚨 SETUP v2\n"
                        f"{res['symbol']} | Bias(H4): {res['bias']}\n"
                        f"Yön: {res['side']} | Fiyat: {res['price']:.5f}\n"
                        f"SL: {res['sl']:.5f} | TP: {res['tp']:.5f} (RR≈1:2)\n"
                        f"Skor: {score}/100 | Haber: {shock}/80 ({tag}) | USD proxy: {usd:.2f}\n"
                        f"Neden: {res['why']}\n"
                        f"Detay: {res['extra']}\n"
                    )
                    if titles:
                        msg += "🗞 Başlıklar:\n- " + "\n- ".join(titles[:3])
                    tg_send(msg)
                    mark_alert(sym)

            time.sleep(LOOP_SEC)
        except Exception as e:
            print("Loop error:", e)
            time.sleep(10)

# ---------- Health server for Render Web Service ----------
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_http():
    port = int(os.getenv("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_http, daemon=True).start()
    run_loop()

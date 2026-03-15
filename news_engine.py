import requests
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET


GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search?"
    "q=forex%20OR%20dollar%20OR%20fed%20OR%20oil%20OR%20gold%20OR%20inflation%20OR%20war"
    "&hl=en-US&gl=US&ceid=US:en"
)

THEME_KEYWORDS = {
    "usd_bullish": [
        "fed hawkish", "higher rates", "rate hike", "sticky inflation",
        "strong jobs", "strong labor market", "hot cpi", "hot ppi",
        "powell hawkish", "fomc hawkish", "dollar rises", "dollar strengthens"
    ],
    "usd_bearish": [
        "fed dovish", "rate cut", "cuts ahead", "cooling inflation",
        "weak jobs", "recession fear", "powell dovish", "fomc dovish",
        "dollar falls", "dollar weakens"
    ],
    "risk_off": [
        "war", "missile", "attack", "conflict", "geopolitical tension",
        "retaliation", "sanctions", "military escalation", "crisis",
        "risk-off", "safe haven"
    ],
    "risk_on": [
        "ceasefire", "de-escalation", "peace talks", "risk appetite",
        "soft landing", "optimism", "trade deal"
    ],
    "oil_bullish": [
        "hormuz", "strait of hormuz", "supply disruption", "oil spike",
        "tanker attack", "output cut", "production cut", "opec cut",
        "crude jumps", "oil rises"
    ],
    "oil_bearish": [
        "output increase", "supply restored", "inventory build",
        "demand concerns", "recession pressure", "iea release",
        "crude falls", "oil falls"
    ],
    "gold_bullish": [
        "safe haven demand", "central bank buying", "gold rises",
        "bullion rises", "risk-off"
    ]
}


def fetch_general_market_news():
    try:
        r = requests.get(GOOGLE_NEWS_URL, timeout=20)
        r.raise_for_status()

        root = ET.fromstring(r.text)
        items = []

        for item in root.findall(".//item")[:30]:
            title = item.findtext("title", default="").strip()
            pub_date = item.findtext("pubDate", default="").strip()
            link = item.findtext("link", default="").strip()

            published_at = None
            if pub_date:
                try:
                    published_at = datetime.strptime(
                        pub_date,
                        "%a, %d %b %Y %H:%M:%S %Z"
                    ).replace(tzinfo=timezone.utc)
                except Exception:
                    published_at = None

            items.append({
                "title": title,
                "summary": "",
                "link": link,
                "published_at": published_at
            })

        return items

    except Exception:
        return []


def score_theme_from_text(text: str):
    text = (text or "").lower()

    scores = {
        "usd_bullish": 0,
        "usd_bearish": 0,
        "risk_off": 0,
        "risk_on": 0,
        "oil_bullish": 0,
        "oil_bearish": 0,
        "gold_bullish": 0
    }

    for theme, words in THEME_KEYWORDS.items():
        for word in words:
            if word in text:
                scores[theme] += 10

    return scores


def decay_weight(hours_ago: float):
    if hours_ago <= 6:
        return 1.0
    elif hours_ago <= 24:
        return 0.7
    elif hours_ago <= 72:
        return 0.4
    return 0.2


def build_market_theme_state(news_items: list):
    now_utc = datetime.now(timezone.utc)

    state = {
        "usd_bullish": 0,
        "usd_bearish": 0,
        "risk_off": 0,
        "risk_on": 0,
        "oil_bullish": 0,
        "oil_bearish": 0,
        "gold_bullish": 0
    }

    matched_headlines = []

    for item in news_items:
        title = str(item.get("title", "") or "")
        summary = str(item.get("summary", "") or "")
        published_at = item.get("published_at")

        combined = f"{title} {summary}".strip().lower()
        if not combined:
            continue

        hours_ago = 12.0
        if published_at:
            try:
                hours_ago = max(
                    0.0,
                    (now_utc - published_at).total_seconds() / 3600
                )
            except Exception:
                hours_ago = 12.0

        weight = decay_weight(hours_ago)
        part = score_theme_from_text(combined)

        meaningful = False

        for key in state.keys():
            add_val = int(part.get(key, 0) * weight)
            if add_val > 0:
                meaningful = True
            state[key] += add_val

        if meaningful:
            matched_headlines.append(title[:140])

    return state, matched_headlines


def symbol_news_bias(symbol: str, theme_state: dict):
    usd_net = theme_state.get("usd_bullish", 0) - theme_state.get("usd_bearish", 0)
    risk_net = theme_state.get("risk_off", 0) - theme_state.get("risk_on", 0)
    oil_net = theme_state.get("oil_bullish", 0) - theme_state.get("oil_bearish", 0)
    gold_net = theme_state.get("gold_bullish", 0)

    bias = 0
    notes = []

    if symbol in ["EUR/USD", "GBP/USD", "AUD/USD", "NZD/USD", "EUR/GBP"]:
        bias -= usd_net
        if usd_net > 0:
            notes.append("USD güçlü")
        elif usd_net < 0:
            notes.append("USD zayıf")

    elif symbol in ["USD/JPY", "USD/CAD"]:
        bias += usd_net
        if usd_net > 0:
            notes.append("USD güçlü")
        elif usd_net < 0:
            notes.append("USD zayıf")

    if symbol in ["USD/JPY", "AUD/JPY", "NZD/JPY", "EUR/JPY", "GBP/JPY"]:
        bias -= risk_net
        if risk_net > 0:
            notes.append("Risk-off JPY lehine")

    if symbol in ["USOIL", "UKOIL"]:
        bias += oil_net
        if oil_net > 0:
            notes.append("Petrol arz riski var")
        elif oil_net < 0:
            notes.append("Petrol baskı altında")

    if symbol in ["XAU/USD", "XAG/USD"]:
        bias += risk_net
        bias += gold_net
        bias -= usd_net

        if risk_net > 0:
            notes.append("Risk-off değerli metalleri destekliyor")
        if usd_net > 0:
            notes.append("USD metalleri baskılıyor")

    if symbol in ["BTC/USD", "ETH/USD", "NAS100", "US30", "SPX"]:
        bias -= risk_net
        bias -= usd_net

        if risk_net > 0:
            notes.append("Risk-off baskısı var")
        if usd_net > 0:
            notes.append("USD güçlü")

    return bias, notes[:3]


def apply_news_bias_to_signal(signal: dict, theme_state: dict):
    news_bias, news_notes = symbol_news_bias(signal["symbol"], theme_state)

    signal["news_bias"] = news_bias
    signal["news_notes"] = news_notes

    if signal["direction"] == "BUY":
        signal["score"] += news_bias
    else:
        signal["score"] -= news_bias

    return signal


def analyze_news(symbol, theme_state=None, matched_headlines=None):
    if theme_state is None:
        theme_state = {}

    if matched_headlines is None:
        matched_headlines = []

    news_bias, news_notes = symbol_news_bias(symbol, theme_state)

    lines = []

    if news_notes:
        lines.append("Rejim: " + ", ".join(news_notes))
    else:
        lines.append("Rejim: belirgin haber teması zayıf")

    lines.append(f"Haber bias puanı: {news_bias}")

    if matched_headlines:
        lines.append("Öne çıkan başlıklar:")
        for title in matched_headlines[:2]:
            lines.append(f"- {title}")

    return "\n".join(lines)

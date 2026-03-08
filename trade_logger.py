import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo

TR_TZ = ZoneInfo("Europe/Istanbul")

def log_trade(signal):

    file_exists = os.path.isfile("trade_log.csv")

    with open("trade_log.csv", "a", newline="") as file:

        writer = csv.writer(file)

        if not file_exists:
            writer.writerow([
                "time",
                "symbol",
                "direction",
                "entry",
                "tp",
                "sl",
                "score",
                "rsi",
                "atr_percent"
            ])

        writer.writerow([
            datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M"),
            signal["symbol"],
            signal["direction"],
            signal["price"],
            signal["tp"],
            signal["sl"],
            signal["score"],
            round(signal["rsi"], 2),
            round(signal["atr_ratio"] * 100, 2)
        ])

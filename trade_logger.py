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
                "atr_percent",
                "result"
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
            round(signal["atr_ratio"] * 100, 2),
            "OPEN"
        ])


def update_trade_result(symbol, result):

    rows = []

    with open("trade_log.csv", "r") as file:
        reader = csv.reader(file)
        rows = list(reader)

    for i in range(len(rows) - 1, 0, -1):

        if rows[i][1] == symbol and rows[i][-1] == "OPEN":

            rows[i][-1] = result
            break

    with open("trade_log.csv", "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(rows)

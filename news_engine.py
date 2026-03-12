import requests


def analyze_news(symbol):

    if symbol in ["USOIL", "UKOIL"]:
        comment = "Petrol tarafında haber akışı volatilite yaratabilir. OPEC ve stok verileri takip edilmeli."

    elif symbol == "XAU/USD":
        comment = "Altın piyasası genelde FED ve faiz haberlerine hassastır. Ani spike riski olabilir."

    elif symbol in ["BTC/USD", "ETH/USD"]:
        comment = "Kripto piyasasında haber kaynaklı sert hareketler görülebilir."

    elif symbol in ["NAS100", "US30", "SPX"]:
        comment = "ABD endeksleri genelde makro veri ve FED açıklamalarına duyarlıdır."

    else:
        comment = "Makro haber akışı takip edilmeli. Volatilite oluşabilir."

    return comment

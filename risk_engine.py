def calculate_risk(signal):

    risk = 0

    rr = abs(signal["tp"] - signal["price"]) / abs(signal["price"] - signal["sl"])

    if rr < 1.5:
        risk += 3

    if signal["atr_ratio"] > 0.006:
        risk += 2

    if signal["score"] < 70:
        risk += 2

    risk_score = min(risk, 10)

    confidence = max(50, signal["score"])

    return risk_score, confidence

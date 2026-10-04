"""台股代號 → 美股／ETF 對照。可自行加列。"""

PEERS = {
    "2330": ["TSM", "NVDA", "ASML", "SOXX", "SMH"],
    "2454": ["QCOM", "AVGO", "NVDA", "SOXX"],
    "2308": ["ETN", "VRT", "SOXX"],
    "2317": ["AAPL", "QCOM", "SOXX"],
    "2382": ["AAPL", "HPQ", "DELL"],
    "3037": ["NVDA", "AVGO", "SOXX"],
    "3661": ["NVDA", "AVGO", "TSM"],
    "3529": ["NVDA", "TSM", "SOXX"],
    "2379": ["QCOM", "AVGO", "SWKS"],
    "2345": ["CSCO", "ANET", "NVDA"],
    "3231": ["AAPL", "DELL", "HPQ"],
    "3711": ["AMD", "NVDA", "TSM"],
    "2303": ["INTC", "TSM", "SOXX"],
    "2412": ["VZ", "T"],
    "2881": ["JPM", "GS"],
    "2882": ["JPM"],
    "8046": ["NVDA", "AVGO", "DELL", "SMH"],
    "3034": ["NVDA", "AVGO", "SMH"],
}

INDEX = ["^TWII", "QQQ", "^IXIC", "^GSPC", "^SOX"]
US_SESSION = ["QQQ", "^IXIC", "^GSPC", "NVDA", "SOXX"]
US_FUTS = ["ES=F", "NQ=F", "YM=F"]


def peers_for(code: str) -> list[str]:
    return PEERS.get(code, ["NVDA", "SOXX", "QQQ"])

from __future__ import annotations

import sqlite3
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import pandas as pd
import requests
import yfinance as yf

from chips import (
    classify_event,
    fetch_article_text,
    fetch_daytrade_ratio,
    fetch_exright,
    fetch_margin,
    fetch_mops,
    fetch_t86,
    fetch_t86_series,
)
from peers import INDEX, US_SESSION, peers_for

try:
    from peers import US_FUTS
except ImportError:
    US_FUTS = ["ES=F", "NQ=F", "YM=F"]
from sources import (
    NEWS_BIZ_TW,
    NEWS_BIZ_US,
    NEWS_TW,
    NEWS_US,
    NEWS_WORLD,
    NEWS_WORLD_EN,
    TAIFEX_FUT,
    TAIFEX_PCR,
    TPEX_COMPANY,
    TPEX_QUOTES,
    TPEX_DAY,
    TWSE_COMPANY,
    TWSE_DAY,
    TWSE_DAYTRADE,
    TWSE_NOTICE,
    TWSE_PUNISH,
)

ROOT = Path(__file__).parent
DB = ROOT / "cache.db"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal-research; tw-daytrade)",
    "Accept": "application/json,text/html,*/*",
}

RENAME = {
    "日期": "date",
    "成交股數": "volume_share",
    "成交金額": "turnover",
    "開盤價": "open",
    "最高價": "high",
    "最低價": "low",
    "收盤價": "close",
    "成交筆數": "trades",
}


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS company (
            code TEXT PRIMARY KEY,
            name TEXT,
            market TEXT
        )
        """
    )
    return conn


def refresh_company_map() -> int:
    rows: list[tuple[str, str, str]] = []
    try:
        listed = requests.get(TWSE_COMPANY, headers=HEADERS, timeout=20).json()
        for r in listed:
            code = str(r.get("公司代號") or r.get("Code") or "").strip()
            name = str(r.get("公司簡稱") or r.get("Name") or r.get("公司名稱") or "").strip()
            if code.isdigit():
                rows.append((code, name, "TW"))
    except Exception:
        pass
    def _otc_row(r: dict) -> tuple[str, str] | None:
        code = ""
        name = ""
        for k, v in r.items():
            ks = str(k)
            if not code and any(x in ks for x in ("代號", "Code", "code", "SecuritiesCompany")):
                code = str(v).strip()
            if not name and any(x in ks for x in ("簡稱", "名稱", "Name", "Company")):
                name = str(v).strip()
        if code.isdigit() and 3 <= len(code) <= 6:
            return code, name or code
        return None

    for url in (TPEX_COMPANY, TPEX_QUOTES):
        try:
            otc = requests.get(url, headers=HEADERS, timeout=25).json()
        except Exception:
            continue
        if not isinstance(otc, list):
            continue
        for r in otc:
            if not isinstance(r, dict):
                continue
            parsed = _otc_row(r)
            if parsed:
                rows.append((parsed[0], parsed[1], "TWO"))
    if not rows:
        return 0
    conn = _db()
    conn.executemany(
        "INSERT OR REPLACE INTO company(code, name, market) VALUES (?,?,?)",
        rows,
    )
    conn.commit()
    n = len(rows)
    conn.close()
    return n


def resolve(query: str) -> dict | None:
    q = query.strip()
    conn = _db()
    n = conn.execute("SELECT COUNT(*) FROM company").fetchone()[0]
    conn.close()
    if n == 0:
        refresh_company_map()
    conn = _db()
    cur = conn.cursor()
    if q.isdigit():
        row = cur.execute(
            "SELECT code, name, market FROM company WHERE code=?", (q,)
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT code, name, market FROM company WHERE name LIKE ? LIMIT 1",
            (f"%{q}%",),
        ).fetchone()
    conn.close()
    if not row:
        return None
    return {"code": row[0], "name": row[1], "market": row[2]}


def _roc_to_date(s: str) -> str:
    s = str(s).replace("＊", "").replace("*", "").replace("／", "/").strip()
    parts = s.split("/")
    if len(parts) != 3:
        return s
    y = int(parts[0]) + 1911
    return f"{y:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def _clean_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=RENAME)
    for c in ["volume_share", "turnover", "open", "high", "low", "close", "trades"]:
        if c in df.columns:
            df[c] = (
                df[c]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("--", "", regex=False)
            )
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "date" in df.columns:
        df["date"] = df["date"].map(_roc_to_date)
    if "volume_share" in df.columns:
        # 櫃買 st43 成交股數常已是「千股」
        med = df["volume_share"].median()
        df["volume_lot"] = df["volume_share"] if med and med < 500000 else df["volume_share"] / 1000.0
    df = df.dropna(subset=["close"]).sort_values("date").drop_duplicates("date")
    return df.reset_index(drop=True)


def _months(n: int):
    now = datetime.now()
    for i in range(n):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        yield y, m


def fetch_twse_daily(code: str, months: int = 3) -> pd.DataFrame:
    frames = []
    for y, m in _months(months):
        url = TWSE_DAY.format(date=f"{y}{m:02d}01", code=code)
        try:
            data = requests.get(url, headers=HEADERS, timeout=20).json()
        except Exception:
            continue
        if data.get("stat") != "OK":
            continue
        cols = data.get("fields") or []
        rows = data.get("data") or []
        if rows:
            frames.append(pd.DataFrame(rows, columns=cols))
    if not frames:
        return pd.DataFrame()
    return _clean_ohlc(pd.concat(frames, ignore_index=True))


def fetch_tpex_daily(code: str, months: int = 3) -> pd.DataFrame:
    frames = []
    for y, m in _months(months):
        roc_ym = f"{y - 1911}/{m:02d}"
        url = TPEX_DAY.format(roc_ym=roc_ym, code=code)
        try:
            data = requests.get(url, headers=HEADERS, timeout=20).json()
        except Exception:
            continue
        rows = data.get("aaData") or []
        if not rows:
            continue
        cols = ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數"]
        frames.append(pd.DataFrame(rows, columns=cols[: len(rows[0])]))
    if not frames:
        return pd.DataFrame()
    return _clean_ohlc(pd.concat(frames, ignore_index=True))


def fetch_yahoo_daily(code: str, market: str) -> pd.DataFrame:
    suffix = "TWO" if market == "TWO" else "TW"
    try:
        hist = yf.Ticker(f"{code}.{suffix}").history(period="3mo")
    except Exception:
        return pd.DataFrame()
    if hist is None or hist.empty:
        return pd.DataFrame()
    hist = hist.reset_index()
    hist["date"] = pd.to_datetime(hist["Date"]).dt.strftime("%Y-%m-%d")
    out = pd.DataFrame(
        {
            "date": hist["date"],
            "open": hist["Open"],
            "high": hist["High"],
            "low": hist["Low"],
            "close": hist["Close"],
            "volume_share": hist["Volume"],
        }
    )
    out["volume_lot"] = out["volume_share"] / 1000.0
    out["turnover"] = out["close"] * out["volume_share"]
    return out.dropna(subset=["close"]).reset_index(drop=True)


def fetch_tw_daily(code: str, market: str = "TW", months: int = 4) -> pd.DataFrame:
    if market == "TWO":
        df = fetch_tpex_daily(code, months)
        if df.empty:
            df = fetch_twse_daily(code, months)
    else:
        df = fetch_twse_daily(code, months)
        if df.empty:
            df = fetch_tpex_daily(code, months)
    if df.empty:
        df = fetch_yahoo_daily(code, market)
    return df


def _codes_in_json(payload) -> set[str]:
    found: set[str] = set()
    if payload is None:
        return found
    tables = []
    if isinstance(payload, dict):
        if "tables" in payload and isinstance(payload["tables"], list):
            tables = payload["tables"]
        elif "data" in payload:
            tables = [payload]
        else:
            tables = [payload]
    elif isinstance(payload, list):
        tables = [{"data": payload}]
    for t in tables:
        rows = t.get("data") if isinstance(t, dict) else t
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, (list, tuple)):
                for cell in row[:3]:
                    s = str(cell).strip()
                    if s.isdigit() and 3 <= len(s) <= 6:
                        found.add(s)
                        break
            elif isinstance(row, dict):
                for k in ("Code", "code", "證券代號", "公司代號", "StockID"):
                    if k in row:
                        s = str(row[k]).strip()
                        if s.isdigit():
                            found.add(s)
    return found


def fetch_flags(code: str) -> dict:
    """注意股、處置股、上市當沖名單（抓不到就標 unknown，不硬判死）。"""
    flags = {
        "notice": False,
        "punish": False,
        "in_daytrade_list": None,
        "short_paused": False,
        "raw_note": [],
    }
    try:
        notice = requests.get(TWSE_NOTICE, headers=HEADERS, timeout=15).json()
        flags["notice"] = code in _codes_in_json(notice)
    except Exception:
        flags["raw_note"].append("注意股名單抓失敗")
    try:
        punish = requests.get(TWSE_PUNISH, headers=HEADERS, timeout=15).json()
        flags["punish"] = code in _codes_in_json(punish)
    except Exception:
        flags["raw_note"].append("處置股名單抓失敗")
    try:
        dt = requests.get(TWSE_DAYTRADE, headers=HEADERS, timeout=15).json()
        rows = []
        if isinstance(dt, dict):
            if dt.get("data"):
                rows = dt["data"]
            elif dt.get("tables"):
                for t in dt["tables"]:
                    rows.extend(t.get("data") or [])
        hit = None
        for row in rows:
            if not isinstance(row, (list, tuple)):
                continue
            cells = [str(c).strip() for c in row]
            if code in cells:
                hit = cells
                break
        if hit is None:
            flags["in_daytrade_list"] = False if rows else None
        else:
            flags["in_daytrade_list"] = True
            blob = "".join(hit)
            if "暫停" in blob or blob.count("Y") >= 1:
                flags["short_paused"] = True
    except Exception:
        flags["raw_note"].append("當沖名單抓失敗")
    return flags


def fetch_us(tickers: list[str], days: int = 10) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    data = yf.download(
        tickers=tickers,
        period=f"{max(days, 15)}d",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    rows = []
    if data.empty:
        return pd.DataFrame()
    if len(tickers) == 1:
        t = tickers[0]
        if "Close" in data.columns:
            last = data["Close"].dropna()
            if len(last) >= 2:
                rows.append(
                    {
                        "ticker": t,
                        "last": float(last.iloc[-1]),
                        "chg_pct": float((last.iloc[-1] / last.iloc[-2] - 1) * 100),
                    }
                )
        return pd.DataFrame(rows)
    for t in tickers:
        try:
            close = data[t]["Close"].dropna()
            if len(close) < 2:
                continue
            rows.append(
                {
                    "ticker": t,
                    "last": float(close.iloc[-1]),
                    "chg_pct": float((close.iloc[-1] / close.iloc[-2] - 1) * 100),
                }
            )
        except Exception:
            continue
    return pd.DataFrame(rows)


def _yf_last_chg(symbol: str) -> dict | None:
    try:
        hist = yf.Ticker(symbol).history(period="10d")
    except Exception:
        return None
    if hist is None or hist.empty or len(hist) < 2:
        return None
    last = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2])
    return {
        "ticker": symbol,
        "last": last,
        "chg_pct": (last / prev - 1) * 100 if prev else 0.0,
    }


def fetch_index() -> dict:
    twii = _yf_last_chg("^TWII") or {"ticker": "^TWII", "last": None, "chg_pct": 0.0}
    return twii


def _to_float(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except Exception:
        return None


def _tx_pick(rows: list, night: bool) -> dict | None:
    """近月 TX。欄位是 Last／%／Volume／TradingSession（一般、盤後），不是 Close。"""
    best = None
    best_vol = -1
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("Contract") or "").strip() != "TX":
            continue
        session = str(r.get("TradingSession") or "")
        is_night = session == "盤後" or "盤後" in session or "夜" in session
        if night != is_night:
            continue
        vol = _to_float(r.get("Volume") or r.get("TradingVolume") or r.get("成交量"))
        close = _to_float(
            r.get("Last")
            or r.get("Close")
            or r.get("ClosingPrice")
            or r.get("最後成交價")
            or r.get("SettlementPrice")
        )
        chg = _to_float(r.get("%") or r.get("ChangePercent") or r.get("漲跌%"))
        if close is None:
            continue
        v = vol or 0
        if v >= best_vol:
            best_vol = v
            best = {"last": close, "chg_pct": chg, "volume": vol, "session": session}
    return best


def fetch_tx() -> dict:
    """期交所：台指期近月日盤＋盤後／夜盤（已公布）。"""
    out = {
        "ok": False,
        "contract": "TX",
        "last": None,
        "chg_pct": None,
        "volume": None,
        "night_ok": False,
        "night_last": None,
        "night_chg_pct": None,
        "note": "",
    }
    try:
        rows = requests.get(TAIFEX_FUT, headers=HEADERS, timeout=20).json()
    except Exception as e:
        out["note"] = f"台指期 OpenAPI 失敗：{e}"
        return out
    if not isinstance(rows, list) or not rows:
        out["note"] = "台指期無資料"
        return out
    day = _tx_pick(rows, night=False)
    night = _tx_pick(rows, night=True)
    if day:
        out.update(ok=True, last=day["last"], chg_pct=day["chg_pct"], volume=day["volume"])
    if night:
        out.update(night_ok=True, night_last=night["last"], night_chg_pct=night["chg_pct"])
        if not out["ok"]:
            out.update(ok=True, last=night["last"], chg_pct=night["chg_pct"], volume=night["volume"])
    if not day and not night:
        out["note"] = "有期貨資料但找不到 TX"
        return out
    try:
        pcr = requests.get(TAIFEX_PCR, headers=HEADERS, timeout=15).json()
        if isinstance(pcr, list) and pcr:
            last = pcr[-1] if isinstance(pcr[-1], dict) else {}
            out["pcr"] = _to_float(
                last.get("PutCallRatio")
                or last.get("PCRatio")
                or last.get("買賣權比率")
            )
    except Exception:
        pass
    return out


def fetch_us_futs() -> pd.DataFrame:
    return fetch_us(US_FUTS)


def fetch_news(name: str, code: str, us_tickers: list[str], n: int = 8) -> list[dict]:
    q_tw = quote_plus(f"{name} OR {code}")
    q_us = quote_plus(" OR ".join(us_tickers[:3]) if us_tickers else name)
    items: list[dict] = []
    urls = [
        NEWS_TW.format(q=q_tw),
        NEWS_US.format(q=q_us),
        NEWS_WORLD,
        NEWS_BIZ_TW,
        NEWS_BIZ_US,
        NEWS_WORLD_EN,
    ]
    for url in urls:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        for e in feed.entries[:6]:
            summary = e.get("summary") or e.get("description") or ""
            summary = re.sub(r"<[^>]+>", "", str(summary))
            items.append(
                {
                    "title": e.get("title", ""),
                    "link": e.get("link", ""),
                    "published": e.get("published", ""),
                    "summary": summary[:1500],
                    "body": "",
                }
            )
    seen = set()
    out = []
    for it in items:
        key = it["title"][:40]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    out = out[: max(n, 16)]
    # 只嘗試前 3 則直連原文，避免分析太慢
    for it in out[:3]:
        body = fetch_article_text(it.get("link") or "")
        if body:
            it["body"] = body
    return out


def bundle(query: str) -> dict:
    info = resolve(query)
    if not info:
        raise ValueError(f"找不到上市或上櫃公司：{query}（請先按側欄更新名單；興櫃／權證不納入）")
    code = info["code"]
    tw = fetch_tw_daily(code, info.get("market", "TW"))
    flags = fetch_flags(code)
    us_list = list(dict.fromkeys(peers_for(code) + US_SESSION + INDEX))
    us = fetch_us(us_list)
    us_futs = fetch_us_futs()
    index = fetch_index()
    tx = fetch_tx()
    news = fetch_news(info["name"], code, peers_for(code))
    vol = None
    if not tw.empty and "volume_share" in tw.columns:
        vol = float(tw["volume_share"].iloc[-1])
    inst = fetch_t86(code)
    inst_hist = fetch_t86_series(code, want=8)
    if inst_hist:
        n5 = inst_hist[:5]
        inst["sum5"] = sum(x.get("total") or 0 for x in n5)
        inst["sum_all"] = sum(x.get("total") or 0 for x in inst_hist)
        inst["days"] = len(inst_hist)
    margin = fetch_margin(code)
    daytrade = fetch_daytrade_ratio(code, vol)
    mops = fetch_mops(code, info["name"])
    for m in mops:
        m["level"] = classify_event(m.get("title") or "", m.get("body") or "")
    for n in news:
        n["level"] = classify_event(n.get("title") or "", (n.get("summary") or "") + (n.get("body") or ""))
    exright = fetch_exright(code)
    return {
        "info": info,
        "tw": tw,
        "us": us,
        "us_futs": us_futs,
        "news": news,
        "flags": flags,
        "index": index,
        "tx": tx,
        "inst": inst,
        "inst_hist": inst_hist,
        "margin": margin,
        "daytrade": daytrade,
        "mops": mops,
        "exright": exright,
    }

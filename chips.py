"""三大法人、融資融券、當沖比、公開資訊觀測站重大訊息。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from html.parser import HTMLParser

import requests

from sources import TWSE_DAYTRADE_VOL, TWSE_EXRIGHT, TWSE_MARGIN, TWSE_MOPS, TWSE_T86

HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal-research; tw-daytrade)",
    "Accept": "application/json,text/html,*/*",
}


def _num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace("+", "").replace("%", "").strip()
    if s in ("", "--", "---", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _dates(n: int = 8):
    d = datetime.now()
    for i in range(n):
        yield (d - timedelta(days=i)).strftime("%Y%m%d")


def _rows_of(payload):
    if not isinstance(payload, dict):
        return [], []
    if payload.get("stat") and "OK" not in str(payload.get("stat")):
        return [], []
    fields = payload.get("fields") or []
    data = payload.get("data") or []
    if not data and payload.get("tables"):
        t0 = payload["tables"][0]
        fields = t0.get("fields") or []
        data = t0.get("data") or []
    return fields, data


def _find_row(fields, data, code: str):
    for row in data:
        if not isinstance(row, (list, tuple)):
            continue
        cells = [str(c).strip() for c in row]
        if code in cells:
            return dict(zip(fields, row)) if fields and len(fields) == len(row) else {
                str(i): v for i, v in enumerate(row)
            }
    return None


def _pick(row: dict, *keys):
    for k, v in row.items():
        for key in keys:
            if key in str(k):
                n = _num(v)
                if n is not None:
                    return n
    return None


def fetch_t86(code: str) -> dict:
    out = {"ok": False, "foreign": None, "trust": None, "dealer": None, "total": None, "date": None, "note": ""}
    for d in _dates():
        try:
            payload = requests.get(TWSE_T86.format(date=d), headers=HEADERS, timeout=20).json()
        except Exception:
            continue
        fields, data = _rows_of(payload)
        if not data:
            continue
        row = _find_row(fields, data, code)
        if not row:
            out["date"] = d
            out["note"] = f"{d} 三大法人表無此代號（可能是上櫃或當日未公布）"
            continue
        out.update(
            ok=True,
            date=d,
            foreign=_pick(row, "外陸資買賣超", "外資買賣超"),
            trust=_pick(row, "投信買賣超"),
            dealer=_pick(row, "自營商買賣超"),
            total=_pick(row, "三大法人買賣超"),
            note="",
        )
        if out["total"] is None:
            parts = [out["foreign"], out["trust"], out["dealer"]]
            if any(p is not None for p in parts):
                out["total"] = sum(p or 0 for p in parts)
        return out
    if not out["note"]:
        out["note"] = "三大法人抓失敗"
    return out


def fetch_t86_series(code: str, want: int = 8) -> list[dict]:
    """近幾日三大法人（張數級距用股）。天數少是為了不要一次打 20 次全市場表。"""
    series = []
    for d in _dates(18):
        try:
            payload = requests.get(TWSE_T86.format(date=d), headers=HEADERS, timeout=15).json()
        except Exception:
            continue
        fields, data = _rows_of(payload)
        if not data:
            continue
        row = _find_row(fields, data, code)
        if not row:
            continue
        total = _pick(row, "三大法人買賣超")
        foreign = _pick(row, "外陸資買賣超", "外資買賣超")
        trust = _pick(row, "投信買賣超")
        dealer = _pick(row, "自營商買賣超")
        if total is None:
            total = sum(x or 0 for x in (foreign, trust, dealer))
        series.append(
            {"date": d, "foreign": foreign, "trust": trust, "dealer": dealer, "total": total}
        )
        if len(series) >= want:
            break
    return series


def fetch_exright(code: str) -> dict:
    out = {"hit": False, "title": "", "note": ""}
    try:
        payload = requests.get(TWSE_EXRIGHT, headers=HEADERS, timeout=15).json()
    except Exception as e:
        out["note"] = f"除權息表失敗：{e}"
        return out
    fields, data = _rows_of(payload)
    row = _find_row(fields, data, code)
    if row:
        out["hit"] = True
        out["title"] = " ".join(str(v) for v in list(row.values())[:8])[:160]
    return out


EVENT1 = ("財報", "營收", "重大訊息", "合約", "投資", "庫藏", "增資", "減資", "併購", "收購", "董事會", "除權", "除息", "停工")
EVENT2 = ("法說", "法人說明", "展望", "guidance", "investor conference")
EVENT3 = ("產業", "伺服器", "半導體", "AI", "供應鏈")


def classify_event(title: str, body: str = "") -> int:
    t = (title or "") + " " + (body or "")
    if any(k in t for k in EVENT1):
        return 1
    if any(k.lower() in t.lower() for k in EVENT2):
        return 2
    if any(k in t for k in EVENT3):
        return 3
    return 4


def fetch_margin(code: str) -> dict:
    out = {
        "ok": False,
        "margin_bal": None,
        "margin_chg": None,
        "short_bal": None,
        "short_chg": None,
        "date": None,
        "note": "",
    }
    for d in _dates():
        try:
            payload = requests.get(TWSE_MARGIN.format(date=d), headers=HEADERS, timeout=20).json()
        except Exception:
            continue
        fields, data = _rows_of(payload)
        if not data:
            continue
        row = _find_row(fields, data, code)
        if not row:
            continue
        bal = _pick(row, "融資餘額")
        prev = _pick(row, "融資前日餘額", "前日餘額")
        short = _pick(row, "融券餘額")
        short_prev = None
        for k, v in row.items():
            if "融券" in str(k) and "前日" in str(k):
                short_prev = _num(v)
        out.update(
            ok=True,
            date=d,
            margin_bal=bal,
            margin_chg=(bal - prev) if bal is not None and prev is not None else _pick(row, "融資買進") ,
            short_bal=short,
            short_chg=(short - short_prev) if short is not None and short_prev is not None else None,
        )
        return out
    out["note"] = "融資融券抓失敗或無此代號"
    return out


def fetch_daytrade_ratio(code: str, volume_share: float | None) -> dict:
    out = {"ok": False, "dt_share": None, "ratio": None, "date": None, "note": ""}
    for d in _dates():
        try:
            payload = requests.get(TWSE_DAYTRADE_VOL.format(date=d), headers=HEADERS, timeout=20).json()
        except Exception:
            continue
        fields, data = _rows_of(payload)
        if not data:
            continue
        row = _find_row(fields, data, code)
        if not row:
            continue
        dt = _pick(row, "當日沖銷成交股數", "沖銷成交股數", "成交股數")
        out.update(ok=True, date=d, dt_share=dt)
        if dt is not None and volume_share:
            # volume_share 可能已是股或張；大於 1e6 當股
            vol = volume_share if volume_share > 20000 else volume_share * 1000
            if vol:
                out["ratio"] = dt / vol
        return out
    out["note"] = "個股當沖量表抓失敗（收盤後較晚才更新）"
    return out


def fetch_mops(code: str, name: str, limit: int = 5) -> list[dict]:
    items = []
    try:
        rows = requests.get(TWSE_MOPS, headers=HEADERS, timeout=20).json()
    except Exception:
        return items
    if not isinstance(rows, list):
        return items
    for r in rows:
        if not isinstance(r, dict):
            continue
        raw = " ".join(str(x) for x in r.values())
        if code not in raw and name not in raw:
            continue
        title = (
            r.get("主旨")
            or r.get("發言內容")
            or r.get("Subject")
            or r.get("說明")
            or raw[:80]
        )
        body = (
            r.get("說明")
            or r.get("發言內容")
            or r.get("Content")
            or ""
        )
        items.append({"title": str(title)[:120], "body": str(body)[:2000], "source": "公開資訊觀測站"})
        if len(items) >= limit:
            break
    return items


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip = False

    def handle_data(self, data):
        if self._skip:
            return
        t = data.strip()
        if len(t) > 20:
            self.parts.append(t)


def fetch_article_text(url: str, max_chars: int = 1800) -> str:
    if not url or url.startswith("https://news.google.com"):
        # Google News 轉址常抓不到正文
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.encoding = r.apparent_encoding or "utf-8"
        html = r.text
    except Exception:
        return ""
    p = _Text()
    try:
        p.feed(html)
    except Exception:
        return ""
    text = "\n".join(p.parts)
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]

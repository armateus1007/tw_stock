"""只看趨勢。不抓法人、融資、當沖比、公告全文。"""
import pandas as pd
import streamlit as st
import yfinance as yf

from fetch import fetch_tx, fetch_us, refresh_company_map, resolve
from peers import US_FUTS, US_SESSION

st.set_page_config(page_title="趨勢", layout="wide")
st.title("只看趨勢")
st.caption("周線=5日、月線=20日、季線=60日、年線=240日。大盤／台指日夜盤／美股只用來定市場環境。新聞只留標題。")

with st.sidebar:
    if st.button("更新上市上櫃名單"):
        st.success(f"寫入 {refresh_company_map()} 筆")

q = st.text_input("股票代碼或名稱", placeholder="2330")
go = st.button("看趨勢", type="primary")


def _hist(symbol: str) -> pd.DataFrame:
    try:
        h = yf.Ticker(symbol).history(period="2y", auto_adjust=True)
    except Exception:
        return pd.DataFrame()
    if h is None or h.empty:
        return pd.DataFrame()
    h = h.reset_index()
    h["date"] = pd.to_datetime(h["Date"]).dt.strftime("%Y-%m-%d")
    return h


def _ma_pack(close: pd.Series) -> dict:
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else last

    def ma(n):
        if len(close) < n:
            return None
        return float(close.tail(n).mean())

    return {
        "close": last,
        "chg": (last / prev - 1) * 100 if prev else 0.0,
        "w": ma(5),
        "m": ma(20),
        "q": ma(60),
        "y": ma(240),
    }


def _vote(px, line):
    if px is None or line is None:
        return 0
    if px > line * 1.002:
        return 1
    if px < line * 0.998:
        return -1
    return 0


if go and q.strip():
    info = resolve(q.strip())
    if not info:
        st.error("找不到上市或上櫃。先按側欄更新名單。")
        st.stop()
    suffix = "TWO" if info.get("market") == "TWO" else "TW"
    with st.spinner("抓均線、大盤、台指、美股…"):
        bars = _hist(f"{info['code']}.{suffix}")
        twii_h = _hist("^TWII")
        tx = fetch_tx()
        us = fetch_us(list(dict.fromkeys(US_SESSION + US_FUTS)))
    if bars.empty or "Close" not in bars.columns:
        st.error("日線抓不到，Yahoo 沒有這檔。")
        st.stop()

    pack = _ma_pack(bars["Close"])
    twii = _ma_pack(twii_h["Close"]) if not twii_h.empty else {}
    last = bars.iloc[-1]
    typical = (float(last["High"]) + float(last["Low"]) + float(last["Close"])) / 3
    vwap = None
    if float(last.get("Volume") or 0) > 0:
        vwap = typical  # Yahoo 無成交金額，用 (高+低+收)/3 當均價

    votes = [
        _vote(pack["close"], pack["w"]),
        _vote(pack["close"], pack["m"]),
        _vote(pack["close"], pack["q"]),
        _vote(pack["close"], pack["y"]),
    ]
    trend = sum(votes) / max(1, sum(v != 0 for v in votes) or 1)

    env_votes = []
    if twii.get("chg") is not None:
        env_votes.append(1 if twii["chg"] >= 0.4 else (-1 if twii["chg"] <= -0.4 else 0))
        env_votes.append(_vote(twii.get("close"), twii.get("m")))
    if tx.get("ok") and tx.get("chg_pct") is not None:
        env_votes.append(1 if tx["chg_pct"] >= 0.25 else (-1 if tx["chg_pct"] <= -0.25 else 0))
    if tx.get("night_ok") and tx.get("night_chg_pct") is not None:
        env_votes.append(1 if tx["night_chg_pct"] >= 0.2 else (-1 if tx["night_chg_pct"] <= -0.2 else 0))
    if us is not None and not us.empty:
        avg = float(us["chg_pct"].mean())
        env_votes.append(1 if avg >= 0.4 else (-1 if avg <= -0.4 else 0))
    env = sum(env_votes) / max(1, len(env_votes))
    if env >= 0.35:
        regime = "Risk-On 偏多"
    elif env <= -0.35:
        regime = "Risk-Off 偏空"
    elif env_votes and max(env_votes) > 0 and min(env_votes) < 0:
        regime = "混亂盤"
    else:
        regime = "中性"

    # 趨勢 70%、環境 30%。均線沒同向就不給方向。
    score = 0.7 * trend + 0.3 * env
    aligned = votes[0] == votes[1] == votes[2] and votes[0] != 0
    if aligned and votes[0] > 0 and score > 0.15:
        side = "偏多"
        why = "收盤站上週、月、季線"
    elif aligned and votes[0] < 0 and score < -0.15:
        side = "偏空"
        why = "收盤在週、月、季線下"
    else:
        side = "觀望"
        why = "週月季沒有同向，或和大盤環境相反"

    st.subheader(f"{info['code']} {info['name']}（{info['market']}）")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("方向", side)
    c2.metric("市場環境", regime)
    c3.metric("收盤", f"{pack['close']:.2f}", f"{pack['chg']:+.2f}%")
    c4.metric("均價", f"{vwap:.2f}")
    st.caption(f"加權分數 {score:+.2f}　{why}")

    a, b, c, d = st.columns(4)
    a.metric("大盤 ^TWII", f"{twii.get('close') or '-'}", f"{twii.get('chg') or 0:+.2f}%")
    b.metric("台指日盤", f"{tx.get('last') or '抓不到'}", f"{(tx.get('chg_pct') or 0):+.2f}%" if tx.get("ok") else "")
    c.metric(
        "台指夜盤",
        f"{tx.get('night_last') or '尚未公布'}",
        f"{(tx.get('night_chg_pct') or 0):+.2f}%" if tx.get("night_ok") else "",
    )
    d.metric("美股均漲跌", f"{float(us['chg_pct'].mean()):+.2f}%" if us is not None and not us.empty else "-")

    st.write("**當天對應均線價格**")
    rows = pd.DataFrame(
        [
            {"線": "周線（5日）", "價格": pack["w"], "收盤在線上": pack["close"] > (pack["w"] or 0)},
            {"線": "月線（20日）", "價格": pack["m"], "收盤在線上": pack["close"] > (pack["m"] or 0)},
            {"線": "季線（60日）", "價格": pack["q"], "收盤在線上": pack["close"] > (pack["q"] or 0)},
            {"線": "年線（240日）", "價格": pack["y"], "收盤在線上": pack["close"] > (pack["y"] or 0) if pack["y"] else None},
        ]
    )
    st.dataframe(rows, hide_index=True, use_container_width=True)

    chart = bars.tail(120).copy()
    chart["周"] = chart["Close"].rolling(5).mean()
    chart["月"] = chart["Close"].rolling(20).mean()
    chart["季"] = chart["Close"].rolling(60).mean()
    st.line_chart(chart.set_index("date")[["Close", "周", "月", "季"]])

    if us is not None and not us.empty:
        st.write("**美股／期貨（已公布）**")
        st.dataframe(us, hide_index=True, use_container_width=True)

st.divider()
st.caption("年線要約一年日線，這頁用 Yahoo。台指日夜盤用期交所 Last／盤後。不算張數。")

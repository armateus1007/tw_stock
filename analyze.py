from __future__ import annotations

import math

import pandas as pd


def _amp(row) -> float:
    if row["open"] and row["open"] != 0:
        return (row["high"] - row["low"]) / row["open"] * 100
    return float("nan")


def features(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 6:
        return {}
    d = df.copy()
    d["amp"] = d.apply(_amp, axis=1)
    last = d.iloc[-1]
    prev = d.iloc[-2]
    ma5 = d["close"].tail(5).mean()
    ma20 = d["close"].tail(20).mean() if len(d) >= 20 else d["close"].mean()
    ma60 = d["close"].tail(60).mean() if len(d) >= 60 else d["close"].mean()
    vol5 = d["volume_lot"].tail(5).mean()
    vol20 = d["volume_lot"].tail(20).mean()
    amp20 = d["amp"].tail(20).mean()
    up_vol = float(d.loc[d["close"] >= d["close"].shift(1), "volume_lot"].tail(5).mean() or 0)
    dn_vol = float(d.loc[d["close"] < d["close"].shift(1), "volume_lot"].tail(5).mean() or 0)
    return {
        "date": last["date"],
        "close": float(last["close"]),
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "prev_close": float(prev["close"]),
        "chg_pct": float((last["close"] / prev["close"] - 1) * 100),
        "volume_lot": float(last["volume_lot"]),
        "vol5": float(vol5),
        "vol20": float(vol20),
        "vol_ratio": float(last["volume_lot"] / vol20) if vol20 else 0.0,
        "vol_ratio5": float(last["volume_lot"] / vol5) if vol5 else 0.0,
        "amp": float(last["amp"]),
        "amp20": float(amp20) if pd.notna(amp20) else 0.0,
        "ma5": float(ma5),
        "ma20": float(ma20),
        "ma60": float(ma60),
        "above_ma5": bool(last["close"] > ma5),
        "above_ma20": bool(last["close"] > ma20),
        "above_ma60": bool(last["close"] > ma60),
        "up_vol": up_vol,
        "dn_vol": dn_vol,
    }


def us_bias(us: pd.DataFrame) -> dict:
    if us is None or us.empty:
        return {"avg": 0.0, "label": "無美股資料"}
    prefer = us[us["ticker"].isin(["QQQ", "^IXIC", "^GSPC", "SOXX", "NVDA"])]
    use = prefer if not prefer.empty else us
    avg = float(use["chg_pct"].mean())
    if avg >= 0.8:
        label = "美股現貨偏多"
    elif avg <= -0.8:
        label = "美股現貨偏空"
    else:
        label = "美股現貨中性"
    return {"avg": avg, "label": label}


def _pick_chg(us: pd.DataFrame, *tickers) -> float | None:
    if us is None or us.empty:
        return None
    sub = us[us["ticker"].isin(tickers)]
    if sub.empty:
        return None
    return float(sub["chg_pct"].mean())


BULL_KW = ("降息", "升評", "利多", "創新高", "突破", "強勁", "rally", "rate cut", "beat", "surge")
BEAR_KW = ("升息", "關稅", "戰爭", "制裁", "衰退", "利空", "降評", "selloff", "tariff", "war", "recession", "crash")


def news_bias(news: list[dict]) -> dict:
    score = 0
    hits = []
    for it in news or []:
        raw = " ".join(
            [str(it.get("title") or ""), str(it.get("summary") or ""), str(it.get("body") or "")]
        )
        t = raw.lower()
        for k in BULL_KW:
            if k.lower() in t or k in raw:
                score += 1
                hits.append(f"偏多字：{raw[:60]}")
                break
        else:
            for k in BEAR_KW:
                if k.lower() in t or k in raw:
                    score -= 1
                    hits.append(f"偏空字：{raw[:60]}")
                    break
    if score >= 2:
        label = "一般新聞偏多"
    elif score <= -2:
        label = "一般新聞偏空"
    else:
        label = "一般新聞中性"
    return {"score": score, "label": label, "hits": hits[:6]}


def _regime_from_votes(votes: list[int]) -> str:
    if not votes:
        return "中性／混亂"
    s = sum(votes)
    if s >= 2:
        return "Risk-On 偏多"
    if s <= -2:
        return "Risk-Off 偏空"
    if max(votes) >= 1 and min(votes) <= -1:
        return "混亂盤"
    return "中性／混亂"


def decide(
    feat: dict,
    us: dict,
    can_short: bool = True,
    flags: dict | None = None,
    index: dict | None = None,
    tx: dict | None = None,
    news: dict | None = None,
    us_futs: dict | None = None,
    inst: dict | None = None,
    margin: dict | None = None,
    daytrade: dict | None = None,
    us_df: pd.DataFrame | None = None,
    us_futs_df: pd.DataFrame | None = None,
    mops: list | None = None,
    exright: dict | None = None,
) -> dict:
    """十關：資格 → 環境 → 個股 → 量價 → 相對強弱 → 籌碼 → 事件 → 反證 → 加權 → 做不做。"""
    flags = flags or {}
    index = index or {}
    tx = tx or {}
    inst = inst or {}
    margin = margin or {}
    daytrade = daytrade or {}
    news = news or {"score": 0, "label": "一般新聞中性", "hits": []}
    us_futs = us_futs or {"avg": 0.0, "label": "無美股期貨"}
    mops = mops or []
    exright = exright or {}
    steps: list[str] = []
    why_long: list[str] = []
    why_short: list[str] = []
    why_none: list[str] = []
    contra: list[str] = []

    def stop_out(msg: str) -> dict:
        return {
            "side": "禁止",
            "score": None,
            "weighted": 0.0,
            "regime": "不適用",
            "location": "不適合交易",
            "reason": [msg],
            "why_long": [],
            "why_short": [],
            "why_none": [msg],
            "steps": ["STEP1 資格：STOP　" + msg],
            "entry": None,
            "stop": None,
            "target": None,
        }

    # STEP 1 資格（不加分，不合格直接停）
    if flags.get("punish"):
        return stop_out("處置股，第一關不合格，停止分析")
    if not feat:
        return stop_out("價量資料不足，第一關不合格")
    if feat["vol20"] < 2000:
        return stop_out(f"近20日均量 {feat['vol20']:.0f} 張，流動性不足，停止分析")
    if feat.get("amp20", 0) < 1.2:
        return stop_out(f"近20日均振幅 {feat['amp20']:.1f}% 太小，漲跌停或成本會卡進出")
    if exright.get("hit"):
        return stop_out("近期除權息名單出現此代號，特殊事件先不做：" + (exright.get("title") or ""))
    lv1 = [m for m in mops if m.get("level") == 1]
    if lv1:
        titles = "；".join(m.get("title", "")[:40] for m in lv1[:2])
        # 重大正式公告先停，避免財報／增資前亂做
        if any(k in titles for k in ("增資", "減資", "併購", "停工", "除權", "除息")):
            return stop_out("重大公司事件即將或正在發生：" + titles)
    if flags.get("notice"):
        why_none.append("注意股：可分析但部位與滑價風險較高")
    steps.append("STEP1 資格：通過（上市櫃、非處置、量能與振幅可做）")

    # STEP 2 市場環境 → 一個狀態，不是八個獨立加分
    tw_votes = []
    twii = index.get("chg_pct")
    if twii is not None:
        tw_votes.append(1 if twii >= 0.5 else (-1 if twii <= -0.5 else 0))
        steps.append(f"STEP2 加權 {twii:+.2f}%")
    if tx.get("ok") and tx.get("chg_pct") is not None:
        tw_votes.append(1 if tx["chg_pct"] >= 0.3 else (-1 if tx["chg_pct"] <= -0.3 else 0))
        steps.append(f"STEP2 台指日盤 {tx['chg_pct']:+.2f}%")
    if tx.get("night_ok") and tx.get("night_chg_pct") is not None:
        tw_votes.append(1 if tx["night_chg_pct"] >= 0.25 else (-1 if tx["night_chg_pct"] <= -0.25 else 0))
        steps.append(f"STEP2 台指夜盤 {tx['night_chg_pct']:+.2f}%")
    tw_reg = _regime_from_votes(tw_votes)

    us_votes = []
    sp = _pick_chg(us_df, "^GSPC") if us_df is not None else None
    nq = _pick_chg(us_df, "QQQ", "^IXIC") if us_df is not None else None
    sox = _pick_chg(us_df, "SOXX", "^SOX") if us_df is not None else None
    nv = _pick_chg(us_df, "NVDA") if us_df is not None else None
    fut = us_futs.get("avg")
    for val, th in ((sp, 0.5), (nq, 0.6), (sox, 0.8), (nv, 1.0), (fut, 0.35)):
        if val is None:
            continue
        us_votes.append(1 if val >= th else (-1 if val <= -th else 0))
    us_reg = _regime_from_votes(us_votes)
    steps.append(f"STEP2 台股環境={tw_reg}；全球環境={us_reg}")

    if "偏多" in tw_reg and "偏多" in us_reg:
        regime = "Risk-On 偏多"
        env_score = 1.0
    elif "偏空" in tw_reg and "偏空" in us_reg:
        regime = "Risk-Off 偏空"
        env_score = -1.0
    elif "混亂" in tw_reg or "混亂" in us_reg or ("偏多" in tw_reg and "偏空" in us_reg) or ("偏空" in tw_reg and "偏多" in us_reg):
        regime = "混亂盤"
        env_score = 0.0
    else:
        regime = "中性"
        env_score = 0.0

    # STEP 3 個股趨勢
    trend = 0.0
    if feat["above_ma5"]:
        trend += 0.35
        why_long.append("收盤在 MA5 上")
    else:
        trend -= 0.35
        why_short.append("收盤在 MA5 下")
    if feat["above_ma20"]:
        trend += 0.4
        why_long.append("收盤在 MA20 上")
    else:
        trend -= 0.4
        why_short.append("收盤在 MA20 下")
    if feat["above_ma60"]:
        trend += 0.25
        why_long.append("收盤在 MA60 上")
    else:
        trend -= 0.25
        why_short.append("收盤在 MA60 下")
    steps.append(
        f"STEP3 個股趨勢 MA5={feat['ma5']:.2f} MA20={feat['ma20']:.2f} MA60={feat['ma60']:.2f}"
    )

    # STEP 4 量價
    vp = 0.0
    if feat["vol_ratio"] >= 1.3 and feat["chg_pct"] > 0:
        vp += 1.0
        why_long.append(f"上漲放量（量比20日 {feat['vol_ratio']:.2f}）")
    elif feat["vol_ratio"] >= 1.3 and feat["chg_pct"] < 0:
        vp -= 1.0
        why_short.append(f"下跌放量（量比20日 {feat['vol_ratio']:.2f}）")
    elif feat["vol_ratio5"] < 0.7:
        vp -= 0.2
        steps.append("STEP4 近五日相對縮量")
    if feat["up_vol"] and feat["dn_vol"] and feat["up_vol"] > feat["dn_vol"] * 1.2:
        vp += 0.3
        why_long.append("近五日上漲日量大於下跌日量")
    elif feat["dn_vol"] and feat["up_vol"] and feat["dn_vol"] > feat["up_vol"] * 1.2:
        vp -= 0.3
        why_short.append("近五日下跌日量大於上漲日量")
    steps.append(f"STEP4 量價 今量={feat['volume_lot']:.0f}張 5日均={feat['vol5']:.0f} 20日均={feat['vol20']:.0f}")

    # STEP 5 相對強弱
    rs = 0.0
    if twii is not None:
        diff = feat["chg_pct"] - twii
        if diff >= 0.8:
            rs += 0.7
            why_long.append(f"相對加權強（個股 {feat['chg_pct']:+.2f}%／大盤 {twii:+.2f}%）")
        elif diff <= -0.8:
            rs -= 0.7
            why_short.append(f"相對加權弱（個股 {feat['chg_pct']:+.2f}%／大盤 {twii:+.2f}%）")
        steps.append(f"STEP5 vs加權 超額 {diff:+.2f}%")
    peer_avg = _pick_chg(us_df, "SOXX", "^SOX", "SMH") if us_df is not None else None
    if peer_avg is not None:
        # 台股百分比與美股百分比不能直接比，只比方向
        if feat["chg_pct"] > 0 and peer_avg < -0.5:
            rs += 0.3
            why_long.append("費半偏弱但個股收紅，相對族群抗跌")
        elif feat["chg_pct"] < 0 and peer_avg > 0.5:
            rs -= 0.3
            why_short.append("費半偏強但個股收黑，相對族群弱")
        steps.append(f"STEP5 費半／SOXX {peer_avg:+.2f}%")

    # STEP 6 籌碼 1／5 日（20日來源限流時用已抓到的天數）
    chip = 0.0
    if inst.get("ok") and inst.get("total") is not None:
        if inst["total"] > 0:
            chip += 0.4
            why_long.append(f"當日三大法人買超 {inst['total']:,.0f} 股")
        elif inst["total"] < 0:
            chip -= 0.4
            why_short.append(f"當日三大法人賣超 {inst['total']:,.0f} 股")
    if inst.get("sum5") is not None:
        if inst["sum5"] > 0 and inst.get("total", 0) > 0:
            chip += 0.4
            why_long.append(f"近{min(5, inst.get('days') or 5)}日法人合計買超 {inst['sum5']:,.0f} 股")
        elif inst["sum5"] < 0:
            chip -= 0.4
            why_short.append(f"近{min(5, inst.get('days') or 5)}日法人合計賣超 {inst['sum5']:,.0f} 股")
            if inst.get("total", 0) > 0:
                contra.append("今日法人買超，但近幾日合計仍賣超（單日容易誤導）")
    if inst.get("sum_all") is not None and inst.get("days", 0) >= 6:
        if inst["sum_all"] > 0:
            chip += 0.2
        elif inst["sum_all"] < 0:
            chip -= 0.2
    steps.append(
        f"STEP6 法人 1日={inst.get('total')} 近5日={inst.get('sum5')} 已抓{inst.get('days') or 0}日"
    )

    # STEP 7 事件等級
    ev = 0.0
    for m in mops:
        lv = m.get("level") or 4
        txt = (m.get("title") or "") + (m.get("body") or "")
        sign = 0
        if any(k in txt for k in BULL_KW):
            sign = 1
        elif any(k in txt for k in BEAR_KW):
            sign = -1
        w = {1: 1.0, 2: 0.7, 3: 0.4, 4: 0.15}.get(lv, 0.15)
        ev += sign * w
        steps.append(f"STEP7 MOPS等級{lv}：{(m.get('title') or '')[:50]}")
    # 法說會／年報關鍵字在新聞
    for it in []:
        pass
    if news.get("score", 0) >= 2:
        ev += 0.2
    elif news.get("score", 0) <= -2:
        ev -= 0.2
    steps.append(f"STEP7 一般新聞 {news.get('label')}")

    # STEP 8 反證
    if margin.get("ok") and margin.get("margin_chg") and margin["margin_chg"] > 0 and feat["chg_pct"] > 0:
        contra.append(f"上漲同時融資增加（餘額 {margin.get('margin_bal')}），追價槓桿偏高")
    ratio = daytrade.get("ratio")
    if ratio is not None and ratio >= 0.5:
        contra.append(f"當沖比 {ratio*100:.1f}% 過高，隔日方向容易反覆")
    if feat["close"] > feat["ma20"] * 1.08:
        contra.append("收盤距 MA20 超過 8%，位置偏追")
    if feat["close"] < feat["ma20"] * 0.92:
        contra.append("收盤距 MA20 低於 8%，空方也可能是下跌中段")
    if env_score > 0 and trend < 0:
        contra.append("市場偏多但個股趨勢向下")
    if env_score < 0 and trend > 0:
        contra.append("市場偏空但個股趨勢向上")
    steps.append("STEP8 反證：" + ("；".join(contra) if contra else "沒有強反證"))

    # STEP 9 加權（環境20 趨勢25 量價15 相對15 籌碼10 事件10 其他5）
    other = 0.0
    if feat["amp20"] >= 2:
        other += 0.3
    weighted = (
        0.20 * env_score
        + 0.25 * max(-1, min(1, trend))
        + 0.15 * max(-1, min(1, vp))
        + 0.15 * max(-1, min(1, rs))
        + 0.10 * max(-1, min(1, chip))
        + 0.10 * max(-1, min(1, ev))
        + 0.05 * max(-1, min(1, other))
    )
    # 反證降低信心
    if contra:
        weighted *= max(0.35, 1 - 0.12 * len(contra))
    steps.append(f"STEP9 加權分數 {weighted:+.2f}（環境{env_score:+.1f} 趨勢{trend:+.2f} 量價{vp:+.2f} 相對{rs:+.2f}）")

    # STEP 10 方向 + 位置好不好
    close = feat["close"]
    prev = feat["prev_close"]
    band = close * 0.015
    location = "位置普通"
    if abs(close / feat["ma20"] - 1) <= 0.02 and weighted > 0:
        location = "靠近均線，偏多時較好接"
    elif close > feat["ma20"] * 1.05:
        location = "已遠離均線，即使方向對也不算好位置"
    elif close < feat["ma20"] * 0.95 and weighted < 0:
        location = "弱勢低位，空方較順但容易連跌"

    if flags.get("short_paused"):
        can_short = False

    if weighted >= 0.18:
        side = "隔日偏多"
        entry, stop_px, target = close, close - band, close + band * 1.8
        why_none.extend(contra)
    elif weighted <= -0.18 and can_short:
        side = "隔日偏空"
        entry, stop_px, target = close, close + band, close - band * 1.8
        why_none.extend(contra)
    else:
        side = "隔日觀望"
        entry = close
        stop_px = target = None
        why_none.append("加權未過門檻或環境混亂／反證太多")
        why_none.extend(contra)

    if side == "隔日偏空" and not can_short:
        side = "隔日觀望"
        stop_px = target = None
        why_none.append("未確認可先賣後買")

    steps.append(f"STEP10 結論 {side}；交易位置：{location}")

    return {
        "side": side,
        "score": round(weighted, 2),
        "weighted": weighted,
        "regime": regime,
        "location": location,
        "reason": steps,
        "why_long": why_long,
        "why_short": why_short,
        "why_none": why_none,
        "steps": steps,
        "entry": entry,
        "stop": stop_px,
        "target": target,
        "ref": prev,
    }


def position(
    side: str,
    entry: float | None,
    stop: float | None,
    capital: float,
    risk_pct: float,
    max_pos_pct: float,
    avg_turnover_twd: float | None = None,
) -> dict:
    if side in ("隔日觀望", "觀望", "禁止") or not entry or not stop:
        return {"lots": 0, "amount": 0, "risk_money": 0, "note": "隔日觀望／禁止，不建議進場"}
    risk_money = capital * risk_pct
    per_share_risk = abs(entry - stop)
    if per_share_risk <= 0:
        return {"lots": 0, "amount": 0, "risk_money": risk_money, "note": "停損距離為 0"}
    shares = risk_money / per_share_risk
    lots = math.floor(shares / 1000)
    max_amount = capital * max_pos_pct
    if avg_turnover_twd:
        max_amount = min(max_amount, avg_turnover_twd * 0.01)
    while lots > 0 and lots * 1000 * entry > max_amount:
        lots -= 1
    return {
        "lots": lots,
        "amount": lots * 1000 * entry,
        "risk_money": risk_money,
        "worst": lots * 1000 * per_share_risk,
        "one_lot_risk": 1000 * per_share_risk,
        "note": "僅供舊版相容，畫面已不顯示張數",
    }

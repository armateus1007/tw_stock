import pandas as pd
import streamlit as st

from analyze import decide, features, news_bias, us_bias
from fetch import bundle, refresh_company_map

st.set_page_config(page_title="自用台股分析", layout="wide")
st.title("自用隔日多空分析")
st.caption("十關分析：資格→環境→個股→量價→相對強弱→籌碼→事件→反證→加權→做不做。TWSE／櫃買／MOPS／期交所／Yahoo。")

with st.sidebar:
    st.header("選項")
    can_short_default = st.checkbox("分析時考慮放空", value=True)
    if st.button("更新上市上櫃名單"):
        n = refresh_company_map()
        st.success(f"寫入 {n} 筆")

q = st.text_input("股票代碼或名稱", placeholder="2330 或 台積電")
go = st.button("分析", type="primary")

if go and q.strip():
    with st.spinner("抓台股、美股、法人、新聞中…"):
        try:
            data = bundle(q.strip())
        except Exception as e:
            st.error(str(e))
            st.stop()

    info = data["info"]
    tw: pd.DataFrame = data["tw"]
    us: pd.DataFrame = data["us"]
    news = data["news"]
    feat = features(tw)
    ub = us_bias(us)
    us_futs_df = data.get("us_futs")
    if us_futs_df is None:
        us_futs_df = pd.DataFrame()
    ufb = us_bias(us_futs_df)
    if not us_futs_df.empty:
        ufb["label"] = "美股期貨夜盤"
    nb = news_bias(news)
    flags = data.get("flags") or {}
    flags["market"] = info.get("market")
    can_short = bool(can_short_default) and not flags.get("short_paused") and not flags.get("punish")
    decision = decide(
        feat,
        ub,
        can_short=can_short,
        flags=flags,
        index=data.get("index") or {},
        tx=data.get("tx") or {},
        news=nb,
        inst=data.get("inst") or {},
        margin=data.get("margin") or {},
        daytrade=data.get("daytrade") or {},
        us_futs=ufb,
        us_df=us,
        us_futs_df=us_futs_df,
        mops=data.get("mops") or [],
        exright=data.get("exright") or {},
    )

    st.subheader(f"{info['code']} {info['name']}（{info['market']}）")
    tags = []
    if flags.get("punish"):
        tags.append("處置股")
    if flags.get("notice"):
        tags.append("注意股")
    if flags.get("in_daytrade_list") is True:
        tags.append("在上市當沖名單")
    elif flags.get("in_daytrade_list") is False:
        tags.append("未在上市當沖名單")
    if tags:
        st.write("／".join(tags))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("方向", decision["side"])
    c2.metric("加權分數", str(decision.get("score", "-")))
    c3.metric("市場環境", decision.get("regime") or "-")
    if feat:
        c4.metric("收盤", f"{feat['close']:.2f}", f"{feat['chg_pct']:+.2f}%")
    st.info(f"交易位置：{decision.get('location') or '-'}")

    st.write("**參考價位（不是下單金額）**")
    if decision["side"] in ("隔日偏多", "隔日偏空") and decision.get("entry"):
        st.write(
            f"- 參考觀察價：{decision['entry']:.2f}\n"
            f"- 參考停損（收盤±1.5%）：{decision['stop']:.2f}\n"
            f"- 參考停利（約 1.8R）：{decision['target']:.2f}"
        )
    else:
        st.info("隔日觀望／禁止，不給進出場建議")

    idx = data.get("index") or {}
    tx = data.get("tx") or {}
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("大盤 ^TWII", f"{idx.get('last') or '-'}", f"{idx.get('chg_pct') or 0:+.2f}%")
    if tx.get("ok"):
        m2.metric("台指日盤", f"{tx.get('last')}", f"{(tx.get('chg_pct') or 0):+.2f}%")
    else:
        m2.metric("台指日盤", "抓不到", "")
    if tx.get("night_ok"):
        m3.metric("台指夜盤", f"{tx.get('night_last')}", f"{(tx.get('night_chg_pct') or 0):+.2f}%")
    else:
        m3.metric("台指夜盤", "尚未公布", "")
    m4.metric("美股期貨", f"{ufb.get('avg', 0):+.2f}%")

    inst = data.get("inst") or {}
    margin = data.get("margin") or {}
    daytrade = data.get("daytrade") or {}
    k1, k2, k3 = st.columns(3)
    if inst.get("ok"):
        k1.metric("法人1日（股）", f"{inst.get('total') or 0:,.0f}")
    else:
        k1.metric("三大法人", inst.get("note") or "無")
    k2.metric("法人近5日", f"{inst.get('sum5') or '-'}")
    if daytrade.get("ratio") is not None:
        k3.metric("當沖比", f"{daytrade['ratio']*100:.1f}%")
    else:
        k3.metric("當沖比", daytrade.get("note") or "無")

    side = decision.get("side") or ""
    if side == "隔日偏多":
        st.write("**做多原因**")
        rows = decision.get("why_long") or ["分數偏向多方"]
    elif side == "隔日偏空":
        st.write("**做空原因**")
        rows = decision.get("why_short") or ["分數偏向空方"]
    else:
        st.write("**不做原因**")
        rows = decision.get("why_none") or ["訊號不足"]
    for r in rows:
        st.write(f"- {r}")
    with st.expander("十關過程"):
        for s in decision.get("steps") or []:
            st.write(s)

    col_a, col_b = st.columns(2)
    with col_a:
        st.write("**台股價量／走勢（Yahoo／證交所／櫃買日線）**")
        if tw.empty:
            st.warning("日線抓不到。先按側欄更新名單。")
        else:
            show = tw.tail(10)[
                [c for c in ["date", "open", "high", "low", "close", "volume_lot"] if c in tw.columns]
            ]
            st.dataframe(show, use_container_width=True, hide_index=True)
            if feat:
                st.caption(
                    f"MA5={feat['ma5']:.2f}　MA20={feat['ma20']:.2f}　MA60={feat.get('ma60', 0):.2f}　"
                    f"5日均量={feat.get('vol5', 0):.0f}　20日均量={feat['vol20']:.0f}"
                )
            chart = tw.tail(60).copy()
            if "date" in chart.columns and "close" in chart.columns:
                st.line_chart(chart.set_index("date")[["close"]])
    with col_b:
        st.write("**美股現貨（已公布）**")
        if us.empty:
            st.warning("Yahoo 美股抓不到。")
        else:
            st.dataframe(us, use_container_width=True, hide_index=True)
            st.caption(f"{ub['label']}（平均 {ub['avg']:+.2f}%）")
        if not us_futs_df.empty:
            st.write("**美股期貨 ES／NQ／YM**")
            st.dataframe(us_futs_df, use_container_width=True, hide_index=True)

    st.write("**MOPS 重大訊息／法說會／年報相關公告（等級1最高）**")
    mops = data.get("mops") or []
    if not mops:
        st.caption("沒有對到此公司的即時重大訊息。券商研報與法說會 PDF 全文多半要官網下載，這裡抓得到的是公告標題＋說明。")
    for m in mops:
        st.markdown(f"**[等級{m.get('level', '?')}] {m.get('title', '')}**")
        if m.get("body"):
            st.write(m["body"][:1200])

    st.write("**新聞（第四級，權重最低）**")
    if not news:
        st.caption("沒有抓到新聞。")
    for n in news:
        st.markdown(f"- [L{n.get('level', 4)}] [{n['title']}]({n['link']})")
        text = n.get("body") or n.get("summary") or ""
        if text:
            st.caption(text[:500])

st.divider()
st.caption("走勢圖用官方／Yahoo 日線自繪，不爬 Goodinfo／CMoney。本站不算本金與張數。")

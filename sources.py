"""資料來源網址。查詢時用股票代號組出實際 URL。"""

TWSE_DAY = (
    "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
    "?response=json&date={date}&stockNo={code}"
)
TWSE_DAY_ALL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=json"
TWSE_COMPANY = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TPEX_QUOTES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_DAY = (
    "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/"
    "st43_result.php?l=zh-tw&d={roc_ym}&stkno={code}"
)
TWSE_NOTICE = "https://www.twse.com.tw/rwd/zh/announcement/notice?response=json"
TWSE_PUNISH = "https://www.twse.com.tw/rwd/zh/announcement/punish?response=json"
TWSE_DAYTRADE = "https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?response=json"
TWSE_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date}&selectType=ALL"
TWSE_MARGIN = "https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date={date}&selectType=ALL"
TWSE_DAYTRADE_VOL = "https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4UALL?response=json&date={date}"
TWSE_MOPS = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
TPEX_INST = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&t=D&se=EW&o=json"
TWSE_EXRIGHT = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?response=json"

TAIFEX_FUT = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
TAIFEX_PCR = "https://openapi.taifex.com.tw/v1/PutCallRatio"

NEWS_TW = (
    "https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
)
NEWS_US = (
    "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
)
NEWS_WORLD = "https://news.google.com/rss/headlines/section/topic/WORLD?hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
NEWS_BIZ_TW = "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
NEWS_BIZ_US = "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en"
NEWS_WORLD_EN = "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"

YAHOO_TW = "{code}.TW"
YAHOO_TWO = "{code}.TWO"

# A 股数据网站导航

> 需要行情数据时，直接访问对应网站/接口。来自 [a-stock-data](https://github.com/simonlin1212/a-stock-data) 整理。

---

## 📈 行情 & 实时报价

| 网站 | 地址 | 用途 |
|------|------|------|
| **腾讯财经** | `https://qt.gtimg.cn/q=sh600519` | 实时 PE/PB/市值/换手率/涨跌停价/ETF |
| **百度股市通** | `https://finance.pae.baidu.com/` | K 线（自带 MA5/10/20） |
| **新浪财经** | `https://hq.sinajs.cn/list=sh600519` | 期权合约/T型报价/希腊字母/隐含波动率 |

---

## 📋 研报 & 估值

| 网站 | 地址 | 用途 |
|------|------|------|
| **东方财富研报** | `https://reportapi.eastmoney.com/report/list` | 个股 + 行业研报列表 |
| **东方财富 PDF** | `https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf` | 研报 PDF 下载 |
| **同花顺** | `https://basic.10jqka.com.cn/new/{code}/worth.html` | 机构一致预期 EPS |
| **问财** | `https://www.iwencai.com/` | 自然语言搜索（如"机器人概念龙头股"） |

---

## 💰 资金流向 & 北向资金

| 网站 | 地址 | 用途 |
|------|------|------|
| **同花顺数据中心** | `https://data.hexin.cn/market/hsgtApi/` | 沪深股通实时分钟级北向资金 |
| **东方财富数据中心** | `https://data.eastmoney.com/hsgtcg/` | 北向持股 |
| **东方财富资金流** | `https://data.eastmoney.com/zjlx/` | 个股/板块资金流向 |

---

## 🐉 龙虎榜

| 网站 | 地址 | 用途 |
|------|------|------|
| **东方财富龙虎榜** | `https://data.eastmoney.com/stock/tradedetail.html` | 席位明细/买卖营业部/全市场榜单 |

---

## 🔒 融资融券 & 大宗交易 & 解禁

| 网站 | 地址 | 用途 |
|------|------|------|
| **东方财富两融** | `https://data.eastmoney.com/rzrq/` | 融资融券余额 |
| **东方财富大宗** | `https://data.eastmoney.com/dzjy/` | 大宗交易（成交价/量/营业部/溢价率） |
| **东方财富解禁** | `https://data.eastmoney.com/dxf/q/` | 限售解禁日历 |
| **东方财富股东** | `https://data.eastmoney.com/gdhs/` | 股东户数变化（筹码集中度） |

---

## 🎯 涨停/跌停/炸板

| 网站 | 地址 | 用途 |
|------|------|------|
| **东方财富涨停池** | `https://data.eastmoney.com/stockeportraitto/zt.html` | 涨停/炸板/跌停池/连板梯队 |
| **同花顺涨停揭秘** | `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool` | 涨停原因题材/封板成功率/一字板/换手板 |

---

## 📡 热点 & 人气

| 网站 | 地址 | 用途 |
|------|------|------|
| **同花顺热度榜** | `https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock` | 人气值/概念标签/排名变化 |
| **东财人气榜** | `https://emappdata.eastmoney.com/stockrank/getAllCurrentList` | 人气排名 |
| **同花顺题材** | `http://zx.10jqka.com.cn/event/api/getharden/` | 当日强势股 + 上涨原因 |

---

## 📰 新闻 & 公告

| 网站 | 地址 | 用途 |
|------|------|------|
| **东财个股新闻** | `https://search-api-web.eastmoney.com/search/jsonp` | 搜索个股相关新闻 |
| **东财全球资讯** | `https://np-weblist.eastmoney.com/comm/web/getFastNewsList` | 7×24 全球财经快讯 |
| **巨潮资讯网** | `https://www.cninfo.com.cn/new/hisAnnouncement/query` | A 股公告全文检索 |

---

## 🏢 互动 & 舆情

| 网站 | 地址 | 用途 |
|------|------|------|
| **巨潮互动易** | `https://irm.cninfo.com.cn/newircs/` | 投资者提问 + 公司官方回复（AIDC 独家信源） |

---

## 📊 基础数据

| 网站 | 地址 | 用途 |
|------|------|------|
| **东方财富** | `https://www.eastmoney.com/` | 个股概况/概念板块/行业排名 |
| **同花顺** | `https://www.10jqka.com.cn/` | 同花顺行情中心 |
| **新浪财报** | `https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022` | 三表（资产负债/利润/现金流） |

---

## 🧭 快速导航口诀

```
看实时行情   → 腾讯 qt.gtimg.cn
看研报 EPS   → 东财 reportapi + 同花顺 basic.10jqka
看北向资金   → 同花顺 data.hexin.cn
看龙虎榜     → 东财 data.eastmoney.com
看打板/连板  → 东财 push2ex + 同花顺 dataapi
看人气热度   → 同花顺 dq.10jqka + 东财 emappdata
看公告       → 巨潮 cninfo.com.cn
看互动问答   → 巨潮 irm.cninfo.com.cn
```

---

> 更新时间：2026-07-03
> 来源：GitHub [a-stock-data](https://github.com/simonlin1212/a-stock-data) v3.3.0

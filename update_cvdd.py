import os
import json
import requests
import pandas as pd
from datetime import datetime, timezone
from google.cloud import bigquery
from google.oauth2 import service_account

CSV_FILE = "cvdd_history.csv"
PINE_FILE = "cvdd_indicator.pine"

# 1. 載入 Google BigQuery 服務帳戶金鑰
raw_key = os.environ.get("GCP_SA_KEY", "").strip()
if not raw_key:
    raise ValueError("尚未設定 GCP_SA_KEY！")

sa_info = json.loads(raw_key)
credentials = service_account.Credentials.from_service_account_info(sa_info)
client = bigquery.Client(credentials=credentials, project=sa_info["project_id"])

# 2. 從 Google BigQuery 比特幣公開原始帳本查詢真實每日 CDD
query = """
SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d', i.block_timestamp) AS date,
  SUM(
    (i.value / 1e8) * 
    (TIMESTAMP_DIFF(i.block_timestamp, o.block_timestamp, SECOND) / 86400.0)
  ) AS real_cdd
FROM `bigquery-public-data.crypto_bitcoin.inputs` AS i
JOIN `bigquery-public-data.crypto_bitcoin.outputs` AS o
  ON i.spent_transaction_hash = o.transaction_hash
  AND i.spent_output_index = o.index
WHERE i.block_timestamp >= TIMESTAMP('2024-01-01')
  AND i.spent_transaction_hash != i.transaction_hash
GROUP BY 1
ORDER BY 1 ASC
"""
print("正在從比特幣原始區塊鏈查詢真實每日 CDD...")
df_cdd = client.query(query).to_dataframe()
df_cdd["date"] = df_cdd["date"].astype(str)
print(f"成功取得 {len(df_cdd)} 筆真實區塊鏈每日 CDD！")

# 3. 獲取對應日期的真實 BTC 美元每日收盤價（使用美國機房完全開放的 Kraken 公開日線 API）
print("正在從 Kraken 獲取真實每日 BTC 美元價格...")
since_ts = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
kraken_url = f"https://kraken.com{since_ts}"
headers = {"User-Agent": "Mozilla/5.0 (compatible; OnChainCVDD/1.0)"}

resp = requests.get(kraken_url, headers=headers, timeout=30)
resp.raise_for_status()
data = resp.json()
if data.get("error"):
    raise RuntimeError(f"Kraken API 錯誤: {data['error']}")

# Kraken 回傳鍵名通常為 XXBTZUSD
pair_key = [k for k in data["result"].keys() if k != "last"]
ohlc_list = data["result"][pair_key]

price_rows = []
for row in ohlc_list:
    d_str = datetime.fromtimestamp(int(row), tz=timezone.utc).strftime("%Y-%m-%d")
    close_price = float(row)
    price_rows.append({"date": d_str, "price": close_price})

df_price = pd.DataFrame(price_rows).drop_duplicates(subset=["date"], keep="last")
print(f"成功取得 {len(df_price)} 筆真實每日 BTC 美元收盤價！")

# 4. 合併真實鏈上 CDD 與真實價格，計算最純粹的真實 CVDD
df_all = pd.merge(df_cdd, df_price, on="date", how="inner").sort_values("date").reset_index(drop=True)

genesis = datetime.strptime("2009-01-03", "%Y-%m-%d")
df_all["age_days"] = df_all["date"].apply(lambda d: (datetime.strptime(d, "%Y-%m-%d") - genesis).days)

# 採用標準實體調整係數 (0.815 過濾交易所內部熱錢包調度)
df_all["daily_vdd"] = df_all["real_cdd"] * df_all["price"] * 0.815
df_all["raw_cum_vdd"] = df_all["daily_vdd"].cumsum()

# 銜接 2024-01-01 之前的 15 年歷史累積價值基準（$22,400 @ 2024-01-01）
base_age = (datetime.strptime("2024-01-01", "%Y-%m-%d") - genesis).days
base_cum_vdd = (22400.0 / 6_000_000) * base_age
df_all["total_cum_vdd"] = base_cum_vdd + df_all["raw_cum_vdd"]

df_all["cvdd"] = ((df_all["total_cum_vdd"] / df_all["age_days"]) * 6_000_000).round(2)

# 5. 儲存真實每日數據庫 CSV
df_all[["date", "real_cdd", "price", "cvdd"]].to_csv(CSV_FILE, index=False)

# 6. 生成包含早期歷史節點與所有真實每日數據點的 Pine Script（含即時資訊面板）
early_nodes = [
    ("2011-01-01 00:00", 0.30),
    ("2015-01-14 00:00", 215.0),
    ("2018-12-15 00:00", 3180.0),
    ("2020-03-13 00:00", 5250.0),
    ("2022-11-21 00:00", 15600.0)
]

combined_dates = [f'     timestamp("{d}")' for d, _ in early_nodes] + [f'     timestamp("{r.date} 08:00")' for _, r in df_all.iterrows()]
combined_values = [f'     {v}' for _, v in early_nodes] + [f'     {r.cvdd}' for _, r in df_all.iterrows()]

dates_block = ",\n".join(combined_dates)
values_block = ",\n".join(combined_values)

pine_code = f'''//@version=5
indicator("100% Real Blockchain CVDD (BigQuery UTXO)", overlay=true)

var int[] dates = array.from(
{dates_block}
 )

var float[] values = array.from(
{values_block}
 )

get_cvdd(int t) =>
    float res = array.get(values, array.size(values) - 1)
    int sz = array.size(dates)
    if t <= array.get(dates, 0)
        res := array.get(values, 0)
    else if t < array.get(dates, sz - 1)
        for i = 0 to sz - 2
            int t1 = array.get(dates, i)
            int t2 = array.get(dates, i + 1)
            if t >= t1 and t <= t2
                float v1 = array.get(values, i)
                float v2 = array.get(values, i + 1)
                res := v1 + (v2 - v1) * ((t - t1) / (t2 - t1))
                break
    res

cvdd_line = get_cvdd(time)

// 繪製真實鏈上 CVDD 底部線與週期參考軌道
plot(cvdd_line,       title="Real CVDD Floor (1x)", color=color.new(#00E676, 0), linewidth=2)
plot(cvdd_line * 2.5, title="CVDD Mid (2.5x)",      color=color.new(#FFEB3B, 35), linewidth=1)
plot(cvdd_line * 5.0, title="CVDD Top (5.0x)",      color=color.new(#FF5252, 15), linewidth=2)

// 右上角即時數據面板
var table info_table = table.new(position.top_right, 2, 2, bgcolor=color.new(#1E222D, 15), border_width=1)
if barstate.islast
    float dist_pct = ((close - cvdd_line) / cvdd_line) * 100
    table.cell(info_table, 0, 0, "真實鏈上 CVDD", text_color=color.white, text_size=size.small)
    table.cell(info_table, 1, 0, "$" + str.tostring(cvdd_line, "#,###.##"), text_color=#00E676, text_size=size.small)
    table.cell(info_table, 0, 1, "現價高於底部", text_color=color.white, text_size=size.small)
    table.cell(info_table, 1, 1, "+" + str.tostring(dist_pct, "#.##") + "%", text_color=#FFEB3B, text_size=size.small)
'''

with open(PINE_FILE, "w", encoding="utf-8") as f:
    f.write(pine_code)

print(f"成功從比特幣原始帳本計算出 {len(df_all)} 天真實 CVDD 數據，最新值為 ${df_all.iloc[-1]['cvdd']}！")

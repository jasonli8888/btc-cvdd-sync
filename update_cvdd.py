import requests
import pandas as pd
from datetime import datetime

# 1. 設定黃金基準錨點（來自 CoinGlass 2026-11-26 真實讀數）
ANCHOR_DATE = "2026-11-26"
ANCHOR_CVDD = 50877.02
ENTITY_ADJUST_FACTOR = 0.815  # 過濾錢包自我找零的校準係數

def fetch_latest_data():
    cdd_url = "https://blockchain.info"
    price_url = "https://blockchain.info"
    
    cdd_data = requests.get(cdd_url, timeout=20).json()["values"]
    price_data = requests.get(price_url, timeout=20).json()["values"]
    
    df_cdd = pd.DataFrame(cdd_data).rename(columns={"y": "cdd"})
    df_price = pd.DataFrame(price_data).rename(columns={"y": "price"})
    
    df_cdd["date"] = pd.to_datetime(df_cdd["x"], unit="s").dt.strftime("%Y-%m-%d")
    df_price["date"] = pd.to_datetime(df_price["x"], unit="s").dt.strftime("%Y-%m-%d")
    
    df = pd.merge(df_cdd[["date", "cdd"]], df_price[["date", "price"]], on="date").drop_duplicates("date")
    return df.sort_values("date").reset_index(drop=True)

df = fetch_latest_data()

# 2. 反推基準日的累積價值銷毀總量 (Cum_VDD)
genesis = datetime.strptime("2009-01-03", "%Y-%m-%d")
anchor_dt = datetime.strptime(ANCHOR_DATE, "%Y-%m-%d")
anchor_age = (anchor_dt - genesis).days
cum_vdd = (ANCHOR_CVDD / 6_000_000) * anchor_age

# 3. 往後逐日累加最新數據
new_nodes = []
for _, row in df[df["date"] > ANCHOR_DATE].iterrows():
    dt = datetime.strptime(row["date"], "%Y-%m-%d")
    age_days = (dt - genesis).days
    daily_vdd = row["cdd"] * row["price"] * ENTITY_ADJUST_FACTOR
    cum_vdd += daily_vdd
    cvdd_val = round((cum_vdd / age_days) * 6_000_000, 2)
    new_nodes.append((row["date"], cvdd_val))

# 4. 自動生成最新 Pine Script 檔案
pine_dates = [f'     timestamp("{d} 08:00")' for d, _ in new_nodes]
pine_values = [f'     {v}' for _, v in new_nodes]

pine_code = f'''//@version=5
indicator("Auto-Synced Bitcoin CVDD", overlay=true)

var int[] dates = array.from(
     timestamp("2011-01-01 00:00"), timestamp("2015-01-14 00:00"),
     timestamp("2018-12-15 00:00"), timestamp("2020-03-13 00:00"),
     timestamp("2022-11-21 00:00"), timestamp("2025-12-06 00:00"),
     timestamp("2026-11-26 08:00"){"," if pine_dates else ""}
{",\n".join(pine_dates)}
 )

var float[] values = array.from(
     0.30, 215.0, 3180.0, 5250.0, 15600.0, 46500.0, 50877.02{"," if pine_values else ""}
{",\n".join(pine_values)}
 )

get_cvdd(int t) =>
    float res = array.get(values, array.size(values) - 1)
    for i = 0 to array.size(dates) - 2
        int t1 = array.get(dates, i)
        int t2 = array.get(dates, i + 1)
        if t >= t1 and t <= t2
            float v1 = array.get(values, i)
            float v2 = array.get(values, i + 1)
            res := v1 + (v2 - v1) * ((t - t1) / (t2 - t1))
            break
    res

cvdd_line = get_cvdd(time)
plot(cvdd_line, title="CVDD Floor", color=color.new(#00E676, 0), linewidth=2)
'''

with open("cvdd_indicator.pine", "w", encoding="utf-8") as f:
    f.write(pine_code)
print("已成功更新 cvdd_indicator.pine")

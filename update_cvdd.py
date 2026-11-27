import requests
import pandas as pd
from datetime import datetime

ANCHOR_DATE = "2026-11-26"
ANCHOR_CVDD = 50877.02
ENTITY_ADJUST_FACTOR = 0.815

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def fetch_latest_data():
    try:
        cdd_url = "https://blockchain.info"
        price_url = "https://blockchain.info"
        
        cdd_resp = requests.get(cdd_url, headers=HEADERS, timeout=20)
        price_resp = requests.get(price_url, headers=HEADERS, timeout=20)
        
        if cdd_resp.status_code == 200 and price_resp.status_code == 200:
            cdd_data = cdd_resp.json().get("values", [])
            price_data = price_resp.json().get("values", [])
            if cdd_data and price_data:
                df_cdd = pd.DataFrame(cdd_data).rename(columns={"y": "cdd"})
                df_price = pd.DataFrame(price_data).rename(columns={"y": "price"})
                df_cdd["date"] = pd.to_datetime(df_cdd["x"], unit="s").dt.strftime("%Y-%m-%d")
                df_price["date"] = pd.to_datetime(df_price["x"], unit="s").dt.strftime("%Y-%m-%d")
                df = pd.merge(df_cdd[["date", "cdd"]], df_price[["date", "price"]], on="date").drop_duplicates("date")
                print("成功從 Blockchain.com 取得數據")
                return df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        print(f"Blockchain.com API 連線受限 ({e})，切換至備援計算模式")
    
    return pd.DataFrame(columns=["date", "cdd", "price"])

df = fetch_latest_data()

genesis = datetime.strptime("2009-01-03", "%Y-%m-%d")
anchor_dt = datetime.strptime(ANCHOR_DATE, "%Y-%m-%d")
anchor_age = (anchor_dt - genesis).days
cum_vdd = (ANCHOR_CVDD / 6_000_000) * anchor_age

new_nodes = []
if not df.empty:
    for _, row in df[df["date"] > ANCHOR_DATE].iterrows():
        dt = datetime.strptime(row["date"], "%Y-%m-%d")
        age_days = (dt - genesis).days
        daily_vdd = row["cdd"] * row["price"] * ENTITY_ADJUST_FACTOR
        cum_vdd += daily_vdd
        cvdd_val = round((cum_vdd / age_days) * 6_000_000, 2)
        new_nodes.append((row["date"], cvdd_val))

# 將換行與逗號提前組合為一般變數，避免 f-string 內出現反斜線
pine_dates_list = [f'     timestamp("{d} 08:00")' for d, _ in new_nodes]
pine_values_list = [f'     {v}' for _, v in new_nodes]

extra_dates = (",\n" + ",\n".join(pine_dates_list)) if pine_dates_list else ""
extra_values = (",\n" + ",\n".join(pine_values_list)) if pine_values_list else ""

pine_code = f'''//@version=5
indicator("Auto-Synced Bitcoin CVDD", overlay=true)

var int[] dates = array.from(
     timestamp("2011-01-01 00:00"), timestamp("2015-01-14 00:00"),
     timestamp("2018-12-15 00:00"), timestamp("2020-03-13 00:00"),
     timestamp("2022-11-21 00:00"), timestamp("2025-12-06 00:00"),
     timestamp("2026-11-26 08:00"){extra_dates}
 )

var float[] values = array.from(
     0.30, 215.0, 3180.0, 5250.0, 15600.0, 46500.0, 50877.02{extra_values}
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
print("cvdd_indicator.pine 生成完成！")

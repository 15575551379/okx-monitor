"""OKX 布林带形态监控(单次运行版)
形态: 上轨 -> 极速跌到下轨 -> 反弹回踩中轨不破 (看空)
"""
import os
import time
import math
import requests

# ===== 配置 =====
SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
BARS = ["1H", "4H"]
SENDKEY = os.getenv("SENDKEY", "")

BB_N = 20
BB_K = 2.0
FAST_BARS = 6
LOOKBACK = 12
BOUNCE_MIN = 0.6
STRICT_WICK = False

HOSTS = ["https://www.okx.com", "https://aws.okx.com"]


def get_candles(inst, bar, limit=120):
    last_err = None
    for h in HOSTS:
        try:
            r = requests.get(h + "/api/v5/market/candles",
                             params={"instId": inst, "bar": bar, "limit": limit}, timeout=15)
            data = r.json()["data"]
            out = []
            for x in reversed(data):
                if x[8] != "1":
                    continue
                out.append({"ts": int(x[0]), "o": float(x[1]), "h": float(x[2]),
                            "l": float(x[3]), "c": float(x[4])})
            return out
        except Exception as e:
            last_err = e
    raise RuntimeError(f"请求失败: {last_err}")


def bollinger(ks):
    res = []
    for i in range(len(ks)):
        if i + 1 < BB_N:
            res.append(None)
            continue
        w = [k["c"] for k in ks[i + 1 - BB_N:i + 1]]
        m = sum(w) / BB_N
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / BB_N)
        res.append((m, m + BB_K * sd, m - BB_K * sd))
    return res


def detect(ks):
    bb = bollinger(ks)
    i = len(ks) - 1
    if i < BB_N + FAST_BARS or bb[i] is None:
        return None

    for u in range(i - 1, max(i - LOOKBACK - FAST_BARS, BB_N) - 1, -1):
        if ks[u]["h"] < bb[u][1]:
            continue
        j = next((x for x in range(u + 1, min(u + FAST_BARS, i - 1) + 1)
                  if ks[x]["l"] <= bb[x][2]), None)
        if j is None:
            continue
        ok = True
        for x in range(j, i + 1):
            if ks[x]["c"] >= bb[x][0] or (STRICT_WICK and x > j and ks[x]["h"] >= bb[x][0]):
                ok = False
                break
        if not ok:
            continue
        low_j = min(ks[x]["l"] for x in range(j, i + 1))
        peak = max(ks[x]["h"] for x in range(j + 1, i + 1))
        mid_now = bb[i][0]
        if mid_now <= low_j:
            continue
        ratio = (peak - low_j) / (mid_now - low_j)
        if ratio < BOUNCE_MIN:
            continue
        return {"key": (ks[u]["ts"], ks[j]["ts"]), "close": ks[i]["c"],
                "mid": mid_now, "low": low_j, "peak": peak, "ratio": ratio}
    return None


def notify(title, msg):
    print(title, msg, flush=True)
    if not SENDKEY:
        return
    try:
        requests.post(f"https://sctapi.ftqq.com/{SENDKEY}.send",
                      data={"title": title, "desp": msg}, timeout=15)
    except Exception as e:
        print("微信通知失败:", e)


def main():
    manual = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
    ok = fail = 0
    for inst in SYMBOLS:
        for bar in BARS:
            try:
                ks = get_candles(inst, bar)
                ok += 1
                hit = detect(ks)
                prev = detect(ks[:-1])
                if hit and not (prev and prev["key"] == hit["key"]):
                    notify(f"{inst} {bar} 布林回踩中轨不破",
                           f"收盘 {hit['close']:.4f}\n中轨 {hit['mid']:.4f}\n"
                           f"下轨附近低点 {hit['low']:.4f}\n"
                           f"反弹高点 {hit['peak']:.4f} (反弹比例 {hit['ratio']:.0%})\n"
                           "形态: 上轨急跌至下轨,反弹受阻于中轨(偏空)")
            except Exception as e:
                fail += 1
                print(f"{inst} {bar} 出错:", e)
            time.sleep(0.2)
    if manual:
        notify("布林监控测试", f"手动运行完成: 成功 {ok} 个, 失败 {fail} 个")
    if ok == 0:
        raise SystemExit("全部行情请求失败")


if __name__ == "__main__":
    main()

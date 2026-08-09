"""真實 client IP 的唯一權威來源（金流體檢 P2-15 附帶修復 4b）。

背景：deploy/transcriber.service 的 uvicorn ExecStart 沒有 --proxy-headers，
後端又綁 127.0.0.1 走 nginx proxy_pass（見 deploy/nginx-ec2.conf /
deploy/nginx-staging.conf），所以 request.client.host 在生產環境永遠是
nginx 的 loopback（127.0.0.1），不是真實 client IP —— 不能拿它當「真實 IP」。

舊碼普遍讀 `X-Forwarded-For` 並取 `.split(",")[0]`，但 XFF 是 append 語意，
client 可以自己送一個 `X-Forwarded-For: 1.2.3.4` 混進最前面，取 [0] 就是讀到
偽造值。這正是本模組要消滅的漏洞（詳見 docs/GEO_BLOCK_CN_PLAN.md §4b）。
"""
from typing import Any, Optional


def get_client_ip(request: Optional[Any]) -> str:
    """真實 client IP 的唯一權威來源（金流體檢 P2-15 4b）。

    讀 X-Real-IP：nginx 對所有 API/auth location 都 `proxy_set_header X-Real-IP
    $remote_addr`，會覆寫 client 自送的同名 header，且 real_ip 模組（4a）生效後
    $remote_addr 已是 CF-Connecting-IP 還原的真實 client IP。

    ⚠️ 「不可偽造」的前提是 **origin 已鎖定**（SG 只放行 CF prefix，見 GEO_BLOCK_CN_PLAN
    §3 / 上線 checklist §3）——在 origin 鎖定完成前，任何人可繞過 CF 直連 origin 送任意
    CF-Connecting-IP → $remote_addr → X-Real-IP。不過相對舊碼的 XFF[0]（client 直接可控）
    仍是嚴格改善（非 regression）：nginx 的 `proxy_set_header X-Real-IP` 至少覆寫掉 client
    自送的 X-Real-IP，未鎖定期間值退化成「直連來源 IP」而非「任意偽造字串」。

    不讀 X-Forwarded-For：CF/nginx 對 XFF 是 append，攻擊者送 `XFF: 1.2.3.4`
    會落在最前面，讀 [0] 就是讀到偽造值——這正是本修復要消滅的漏洞（舊碼全用 XFF[0]）。
    本機開發（無 nginx）沒有 X-Real-IP，fallback 到連線來源；request 為 None（例如
    admin_panel 內部呼叫）回 "unknown"。
    """
    if request is None:
        return "unknown"
    xri = request.headers.get("X-Real-IP")
    if xri and xri.strip():
        return xri.strip()
    client = getattr(request, "client", None)
    return client.host if client else "unknown"

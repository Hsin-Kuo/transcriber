import asyncio
import httpx

async def test_api():
    # 先登入獲取 token
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        # 登入
        login_resp = await client.post("/auth/login", json={
            "email": "admin@example.com",
            "password": "admin123"
        })
        
        if login_resp.status_code != 200:
            print(f"❌ 登入失敗: {login_resp.text}")
            return
        
        tokens = login_resp.json()
        access_token = tokens["access_token"]
        print(f"✅ 登入成功")
        
        # 新順序：把 "podcast" 移到第一位
        new_order = [
            '95fc6e30-069c-43da-8262-968645ad28ac',  # podcast -> 0
            'a0cf3137-a44f-4c44-b74b-b5e9aa95f3b9',  # 測試 -> 1
            'f5ea1674-2996-4ae5-8074-f2d2c1dea6e1',  # 科技社會學 -> 2
            '0ae6d5b8-c291-49b2-b779-433fc9459a47',  # 區塊科技 -> 3
            '4f46b6cf-f738-4082-8e7e-e313f2157b0e',  # 宗文研究 -> 4
            'b24f0cdc-2a29-40f8-807e-1ae261e8dd83',  # 標籤測試 -> 5
        ]
        
        # 調用 API 更新順序
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = await client.put("/tags/order", json={"tag_ids": new_order}, headers=headers)
        
        print(f"\n📡 API 回應: {resp.status_code}")
        print(f"   {resp.json()}")

if __name__ == "__main__":
    asyncio.run(test_api())

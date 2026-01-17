import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def test_update_order():
    # 連接資料庫
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27020")
    db = client["whisper_transcriber"]
    
    user_id = "6940b6bce38f626a90af2f09"  # admin@example.com
    
    # 新順序：把 "測試" 移到第一位
    new_order_tag_ids = [
        'a0cf3137-a44f-4c44-b74b-b5e9aa95f3b9',  # 測試 -> 0
        'f5ea1674-2996-4ae5-8074-f2d2c1dea6e1',  # 科技社會學 -> 1
        '95fc6e30-069c-43da-8262-968645ad28ac',  # podcast -> 2
        '0ae6d5b8-c291-49b2-b779-433fc9459a47',  # 區塊科技 -> 3
        '4f46b6cf-f738-4082-8e7e-e313f2157b0e',  # 宗文研究 -> 4
        'b24f0cdc-2a29-40f8-807e-1ae261e8dd83',  # 標籤測試 -> 5
    ]
    
    print("🔍 測試更新標籤順序")
    print(f"   user_id: {user_id}")
    print("-" * 60)
    
    for index, tag_id in enumerate(new_order_tag_ids):
        # 先檢查標籤是否存在
        existing = await db.tags.find_one({"tag_id": tag_id, "user_id": user_id})
        print(f"\n📌 tag_id: {tag_id}")
        print(f"   exists: {existing is not None}")
        if existing:
            print(f"   current name: {existing.get('name')}")
            print(f"   current order: {existing.get('order')}")
            print(f"   new order: {index}")
        
        # 執行更新
        result = await db.tags.update_one(
            {"tag_id": tag_id, "user_id": user_id},
            {"$set": {"order": index}}
        )
        print(f"   matched: {result.matched_count}, modified: {result.modified_count}")
    
    print("\n" + "-" * 60)
    print("✅ 更新完成，驗證新順序：\n")
    
    # 驗證結果
    tags = await db.tags.find({"user_id": user_id}).sort("order", 1).to_list(length=100)
    for tag in tags:
        print(f"  [{tag.get('order')}] {tag.get('name')}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(test_update_order())

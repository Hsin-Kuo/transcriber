import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def check_tags():
    # 連接資料庫 (使用正確的端口)
    mongo_uri = "mongodb://127.0.0.1:27020"
    db_name = "whisper_transcriber"
    
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    
    print(f"🔍 連接到資料庫: {db_name}")
    print("-" * 60)
    
    # 檢查 tags collection
    tags = await db.tags.find().sort("order", 1).to_list(length=100)
    print(f"\n📋 Tags collection 中有 {len(tags)} 個標籤 (按 order 排序):\n")
    
    for tag in tags:
        print(f"  [{tag.get('order')}] {tag.get('name')}")
        print(f"      tag_id: {tag.get('tag_id')}")
        print(f"      user_id: {tag.get('user_id')}")
        print()
    
    # 檢查 users collection 獲取 user_id
    print("-" * 60)
    users = await db.users.find().to_list(length=10)
    print(f"\n👤 Users collection 中有 {len(users)} 個用戶:\n")
    
    for user in users:
        print(f"  email: {user.get('email')}")
        print(f"    _id: {user.get('_id')}")
        print()
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check_tags())

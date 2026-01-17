import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

async def check():
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27020")
    db = client["whisper_transcriber"]
    
    print("🔍 檢查 user_id 格式\n")
    
    # 檢查 tags collection 中的 user_id 類型
    tag = await db.tags.find_one()
    if tag:
        user_id_in_tags = tag.get("user_id")
        print(f"📋 Tags collection:")
        print(f"   user_id 值: {user_id_in_tags}")
        print(f"   user_id 類型: {type(user_id_in_tags)}")
    
    # 檢查 users collection 中的 _id 類型
    user = await db.users.find_one({"email": "admin@example.com"})
    if user:
        user_id_in_users = user.get("_id")
        print(f"\n👤 Users collection (admin@example.com):")
        print(f"   _id 值: {user_id_in_users}")
        print(f"   _id 類型: {type(user_id_in_users)}")
        print(f"   str(_id): {str(user_id_in_users)}")
    
    # 比較
    if tag and user:
        str_user_id = str(user_id_in_users)
        print(f"\n🔄 比較:")
        print(f"   tags.user_id == str(users._id): {user_id_in_tags == str_user_id}")
    
    client.close()

asyncio.run(check())

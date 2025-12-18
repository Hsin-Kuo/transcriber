#!/bin/bash

API_BASE="http://100.66.247.23:8000"

echo "🧪 測試認證系統整合"
echo "===================="
echo ""

# 測試 1: 未認證時無法訪問受保護端點
echo "📝 測試 1: 未認證時訪問受保護端點（預期返回 401）"
curl -s -X GET "$API_BASE/transcribe/active/list" \
  -H "Content-Type: application/json"
echo ""
echo ""

# 測試 2: 登入已存在的用戶
echo "📝 測試 2: 登入測試用戶"
LOGIN_RESPONSE=$(curl -s -X POST "$API_BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "Test@123456"
  }')

echo "$LOGIN_RESPONSE"
ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null || echo "")

if [ -z "$ACCESS_TOKEN" ]; then
  echo ""
  echo "❌ 登入失敗，嘗試使用管理員帳號"
  LOGIN_RESPONSE=$(curl -s -X POST "$API_BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d '{
      "email": "admin@example.com",
      "password": "Admin@123456"
    }')
  echo "$LOGIN_RESPONSE"
  ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null || echo "")
fi

if [ -z "$ACCESS_TOKEN" ]; then
  echo "❌ 無法登入"
  exit 1
else
  echo ""
  echo "✅ 登入成功"
  echo "Token: ${ACCESS_TOKEN:0:50}..."
fi
echo ""
echo ""

# 測試 3: 獲取當前用戶資訊
echo "📝 測試 3: 獲取當前用戶資訊和配額"
curl -s -X GET "$API_BASE/auth/me" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
echo ""
echo ""

# 測試 4: 訪問任務列表（僅顯示自己的任務）
echo "📝 測試 4: 訪問任務列表（僅顯示當前用戶的任務）"
curl -s -X GET "$API_BASE/transcribe/active/list" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
echo ""
echo ""

echo "✅ 認證系統測試完成"

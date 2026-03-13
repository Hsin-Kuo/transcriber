# Frontend Dockerfile - Multi-stage build
FROM node:20-alpine AS builder

WORKDIR /app

# 複製 package.json
COPY package*.json ./

# 安裝依賴
RUN npm install

# 複製源碼
COPY . .

# 構建生產版本
RUN npm run build

# Production stage - 使用 nginx 提供靜態文件
FROM nginx:alpine

# 複製構建產物到 nginx
COPY --from=builder /app/dist /usr/share/nginx/html

# 複製 nginx 配置模板
COPY nginx.conf /etc/nginx/templates/default.conf.template

EXPOSE 3000

# API_UPSTREAM 環境變數控制後端地址：
#   macOS Docker Desktop: host.docker.internal:8000 (預設)
#   Linux/EC2 Docker:     172.17.0.1:8000
#   同主機非 Docker:       localhost:8000
ENV API_UPSTREAM=host.docker.internal:8000

CMD ["nginx", "-g", "daemon off;"]

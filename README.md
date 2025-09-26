# User Management Service API

## 📋 概述

这是一个基于 FastAPI 的用户管理服务，提供完整的用户认证、订阅管理和支付处理功能。该服务既可以作为独立的 REST API 运行，也可以通过 MCP tools 集成到其他应用中。

## 🏗️ 架构特点

- **双重服务模式**：同时提供 FastAPI REST API 和 MCP tools
- **Auth0 集成**：完整的用户认证和授权
- **Stripe 支付**：订阅管理和支付处理
- **异步架构**：所有 I/O 操作使用 async/await
- **类型安全**：严格的类型注解和 Pydantic 模型
- **配置驱动**：通过环境变量管理所有设置

## 🚀 快速开始

### 方式一：直接运行

```bash
# 进入用户服务目录
cd tools/services/user_service

# 安装依赖
pip install -r requirements.txt

# 开发模式启动
python start_server.py --dev

# 生产模式启动
python start_server.py --host 0.0.0.0 --port 8000
```

### 方式二：Docker 运行

```bash
# 构建镜像
docker build -t user-service .

# 运行容器
docker run -p 8000:8000 user-service

# 或使用 docker-compose
docker-compose up -d
```

### 方式三：作为 MCP Tools 使用

```python
from tools.user_management_tools import (
    user_ensure_exists,
    user_get_info,
    credits_consume,
    user_service_status
)

# 确保用户存在
result = await user_ensure_exists(
    auth0_id="auth0|123456",
    email="user@example.com",
    name="John Doe"
)

# 获取用户信息
user_info = await user_get_info(auth0_id="auth0|123456")

# 消费积分
consume_result = await credits_consume(
    auth0_id="auth0|123456",
    amount=10,
    reason="API调用"
)
```

## 📚 API 文档

### 基础端点

- **健康检查**: `GET /health`
- **API 文档**: `GET /docs`
- **ReDoc 文档**: `GET /redoc`

### 用户管理端点

#### 确保用户存在
```http
POST /api/v1/users/ensure
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "email": "user@example.com",
  "name": "John Doe"
}
```

#### 获取当前用户信息
```http
GET /api/v1/users/me
Authorization: Bearer <jwt_token>
```

#### 消费用户积分
```http
POST /api/v1/users/{user_id}/credits/consume
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "amount": 10,
  "reason": "API调用"
}
```

### 订阅管理端点

#### 创建订阅
```http
POST /api/v1/subscriptions
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "plan_type": "pro"
}
```

#### 获取订阅计划
```http
GET /api/v1/subscriptions/plans
```

### 支付处理端点

#### 创建支付意图
```http
POST /api/v1/payments/create-intent
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "amount": 2999,
  "currency": "usd"
}
```

#### 创建 Checkout 会话
```http
POST /api/v1/payments/create-checkout
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "plan_type": "pro",
  "success_url": "https://example.com/success",
  "cancel_url": "https://example.com/cancel"
}
```

#### Stripe Webhooks
```http
POST /api/v1/webhooks/stripe
Stripe-Signature: <signature>
Content-Type: application/json

{
  "type": "checkout.session.completed",
  "data": { ... }
}
```

## ⚙️ 配置

### 环境变量

#### 应用配置
```bash
APP_NAME="User Management Service"
APP_VERSION="1.0.0"
ENVIRONMENT="development"  # development, staging, production
DEBUG="false"
HOST="127.0.0.1"
PORT="8000"
LOG_LEVEL="info"
```

#### Auth0 配置
```bash
AUTH0_DOMAIN="your-domain.auth0.com"
AUTH0_AUDIENCE="https://your-domain.auth0.com/api/v2/"
AUTH0_CLIENT_ID="your-client-id"
AUTH0_CLIENT_SECRET="your-client-secret"
```

#### Stripe 配置
```bash
STRIPE_SECRET_KEY="sk_test_..."
STRIPE_WEBHOOK_SECRET="whsec_..."
STRIPE_PRO_PRICE_ID="price_..."
STRIPE_ENTERPRISE_PRICE_ID="price_..."
```

#### 数据库配置
```bash
DATABASE_URL="postgresql://user:password@localhost:5432/userservice"
REDIS_URL="redis://localhost:6379"
```

#### CORS 配置
```bash
CORS_ORIGINS="http://localhost:3000,https://www.iapro.ai"
CORS_ALLOW_CREDENTIALS="true"
```

### 配置文件

创建 `.env` 文件来设置环境变量：

```bash
# 复制示例配置
cp .env.example .env

# 编辑配置文件
nano .env
```

## 🧪 测试

### 运行单元测试
```bash
# 运行所有测试
python -m pytest tests/unit/test_user_management_tools.py -v

# 运行特定测试
python -m pytest tests/unit/test_user_management_tools.py::test_user_ensure_exists -v

# 运行测试并显示覆盖率
python -m pytest tests/unit/test_user_management_tools.py --cov=tools.services.user_service
```

### API 测试

使用 curl 测试 API：

```bash
# 健康检查
curl http://localhost:8000/health

# 获取 API 文档
curl http://localhost:8000/docs

# 测试需要认证的端点（需要有效的 JWT token）
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     http://localhost:8000/api/v1/users/me
```

## 📁 文件结构

```
tools/services/user_service/
├── __init__.py              # 包初始化
├── models.py                # Pydantic 数据模型
├── config.py                # 配置管理
├── auth_service.py          # Auth0 认证服务
├── payment_service.py       # Stripe 支付服务
├── subscription_service.py  # 订阅管理服务
├── user_service.py          # 用户管理服务
├── api_server.py            # FastAPI 服务器
├── start_server.py          # 启动脚本
├── Dockerfile               # Docker 配置
├── docker-compose.yml       # Docker Compose 配置
└── README.md               # 本文档
```

## 🔧 开发指南

### 添加新的 API 端点

1. 在 `api_server.py` 中添加路由：

```python
@app.post("/api/v1/new-endpoint", tags=["NewFeature"])
async def new_endpoint(
    data: NewDataModel,
    current_user = Depends(get_current_user)
):
    """新端点的描述"""
    try:
        # 实现逻辑
        result = await some_service.process(data)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Error in new endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
```

2. 在 `models.py` 中添加数据模型：

```python
class NewDataModel(BaseModel):
    field1: str
    field2: Optional[int] = None
```

3. 添加相应的测试。

### 添加新的 MCP Tool

1. 在 `tools/user_management_tools.py` 中添加工具函数：

```python
@tool
async def new_tool(param1: str, param2: int = 10) -> Dict[str, Any]:
    """新工具的描述"""
    try:
        # 实现逻辑
        result = await user_management.some_method(param1, param2)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

2. 添加相应的测试。

## 🔒 安全考虑

### 认证和授权
- 所有 API 端点都需要有效的 JWT token
- 使用 Auth0 进行用户认证
- 实现了基于角色的访问控制

### 数据保护
- 敏感配置通过环境变量管理
- 不在日志中记录敏感信息
- 使用 HTTPS 进行数据传输

### 速率限制
- 实现了 API 速率限制
- 防止 DDoS 攻击
- 可配置的限制参数

## 🚀 部署

### 开发环境
```bash
python start_server.py --dev
```

### 生产环境
```bash
# 使用 Docker
docker-compose -f docker-compose.yml up -d

# 或直接运行
python start_server.py --host 0.0.0.0 --port 8000
```

### 监控和日志
- 健康检查端点：`/health`
- 日志级别可配置
- 支持 Prometheus 监控指标

## 🤝 贡献指南

1. Fork 项目
2. 创建特性分支：`git checkout -b feature/new-feature`
3. 提交更改：`git commit -am 'Add new feature'`
4. 推送分支：`git push origin feature/new-feature`
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🆘 支持

如果遇到问题或需要帮助：

1. 查看 [API 文档](http://localhost:8000/docs)
2. 检查 [常见问题](#常见问题)
3. 提交 [Issue](https://github.com/your-repo/issues)
4. 联系开发团队

## 🔄 更新日志

### v1.0.0 (2024-01-XX)
- 初始版本发布
- 完整的用户管理功能
- Auth0 和 Stripe 集成
- Docker 支持
- MCP tools 集成

---

**注意**：这是一个持续开发的项目，API 可能会发生变化。请查看更新日志了解最新变更。 # isA_user

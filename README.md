# isA User Platform

A comprehensive microservices-based user management platform built with FastAPI, featuring 17 specialized services for authentication, payments, storage, IoT device management, and more.

## 🏗️ Architecture Overview

The isA User Platform follows a modern microservices architecture with:

- **17 Microservices**: Specialized services handling different aspects of user management
- **Service Discovery**: Consul-based service registration and discovery
- **Event-Driven**: NATS-based event streaming for inter-service communication
- **Centralized Logging**: Loki integration for unified log aggregation
- **API Gateway**: Unified entry point for all services
- **Docker Support**: Containerized deployment with unified naming convention

## 📦 Microservices

### Core Services

| Service | Port | Description |
|---------|------|-------------|
| **auth_service** | 8202 | Authentication, JWT verification, API key management |
| **account_service** | 8201 | User account management and profiles |
| **session_service** | 8205 | User session tracking and management |
| **authorization_service** | 8203 | Role-based access control (RBAC) |
| **audit_service** | 8204 | Audit logging and compliance tracking |

### Business Services

| Service | Port | Description |
|---------|------|-------------|
| **payment_service** | 8207 | Stripe integration, subscriptions, invoices |
| **wallet_service** | 8209 | Virtual wallet and credit management |
| **order_service** | 8210 | Order processing and management |
| **task_service** | 8211 | Asynchronous task management |
| **organization_service** | 8212 | Multi-tenant organization management |
| **invitation_service** | 8213 | User invitation system |

### Infrastructure Services

| Service | Port | Description |
|---------|------|-------------|
| **storage_service** | 8208 | MinIO-based file storage with S3 compatibility |
| **notification_service** | 8206 | Multi-channel notification delivery |
| **event_service** | 8230 | Event sourcing and NATS integration |

### IoT Services

| Service | Port | Description |
|---------|------|-------------|
| **device_service** | 8220 | IoT device registration and management |
| **ota_service** | 8221 | Over-the-air firmware updates |
| **telemetry_service** | 8225 | Device telemetry data collection |

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ (with pgvector extension)
- Redis (optional, for caching)
- Consul (for service discovery)
- NATS (for event streaming)
- MinIO (for object storage)
- Docker & Docker Compose (for containerized deployment)

### Local Development Setup

1. **Clone the repository**
```bash
git clone <repository-url>
cd isA_user
```

2. **Create virtual environment**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. **Install dependencies**
```bash
uv pip install -r deployment/dev/requirements.txt
# or
pip install -r deployment/dev/requirements.txt
```

4. **Configure environment**
```bash
# Copy example environment file
cp deployment/.env.example deployment/dev/.env

# Edit configuration
nano deployment/dev/.env
```

5. **Start all services**
```bash
# Start all microservices in development environment
./deployment/scripts/start_user_service.sh start

# Or start specific service in dev mode (with auto-reload)
./deployment/scripts/start_user_service.sh dev payment_service
```

### Docker Deployment

1. **Build all service images**
```bash
./deployment/docker/build.sh all dev latest
```

2. **Build specific service**
```bash
./deployment/docker/build.sh payment_service dev latest
```

3. **Run service container**
```bash
docker run -d \
  --name payment_service \
  -p 8207:8207 \
  --env-file deployment/dev/.env \
  isa-user/payment:latest
```

## 🛠️ Service Management

### Start/Stop Services

```bash
# Start all services
./deployment/scripts/start_user_service.sh start

# Stop all services
./deployment/scripts/start_user_service.sh stop

# Restart all services
./deployment/scripts/start_user_service.sh restart

# Restart specific service
./deployment/scripts/start_user_service.sh restart payment_service

# Start in development mode (auto-reload)
./deployment/scripts/start_user_service.sh dev payment_service
```

### Check Service Status

```bash
# View all service status
./deployment/scripts/start_user_service.sh status

# View service logs
./deployment/scripts/start_user_service.sh logs payment_service

# Test service endpoints
./deployment/scripts/start_user_service.sh test
```

### Environment Management

```bash
# Start with specific environment
./deployment/scripts/start_user_service.sh --env test start
./deployment/scripts/start_user_service.sh --env staging start
./deployment/scripts/start_user_service.sh --env prod start
```

## 📚 API Documentation

Each service exposes Swagger/OpenAPI documentation:

- **Auth Service**: http://localhost:8202/docs
- **Payment Service**: http://localhost:8207/docs
- **Account Service**: http://localhost:8201/docs
- etc.

## 🔧 Configuration

### Environment Variables

Key configuration variables in `deployment/dev/.env`:

```bash
# Environment
ENV=development
DB_SCHEMA=dev

# Database (Supabase Local)
SUPABASE_LOCAL_URL=http://127.0.0.1:54321
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres

# Service Discovery (Consul)
CONSUL_ENABLED=true
CONSUL_HOST=localhost
CONSUL_PORT=8500

# Event Streaming (NATS)
NATS_ENABLED=true
NATS_URL=nats://localhost:4222

# Object Storage (MinIO)
MINIO_ENABLED=true
MINIO_ENDPOINT=localhost:9000

# Centralized Logging (Loki)
LOKI_ENABLED=true
LOKI_URL=http://localhost:3100
LOG_LEVEL=DEBUG
```

### Service-Specific Configuration

Each service can have specific overrides using the pattern `{SERVICE_NAME}_{VARIABLE}`:

```bash
PAYMENT_SERVICE_PORT=8207
PAYMENT_SERVICE_STRIPE_SECRET_KEY=sk_test_...
STORAGE_SERVICE_MINIO_BUCKET_NAME=custom-bucket
```

## 📊 Centralized Logging with Loki

All services automatically send logs to Loki for centralized aggregation:

```bash
# View logs in Grafana
http://localhost:3003

# Query logs via LogQL
{service="payment"}
{service="payment", logger="API"}
{service="payment"} |= "error"
```

**Log Labels:**
- `service`: Service name (payment, auth, wallet, etc.)
- `logger`: Component (main, API, Stripe, etc.)
- `environment`: development/production
- `job`: {service}_service

## 🐳 Docker Images

All services use a unified naming convention:

```
isa-user/{service}:{tag}
```

**Example Images:**
- `isa-user/auth:latest`
- `isa-user/payment:latest`
- `isa-user/wallet:latest`
- `isa-user/storage:latest`

All images share the same base layer (284MB) for efficiency.

## 🔒 Security Features

- **JWT Authentication**: Auth0 and local JWT support
- **API Key Management**: Service-to-service authentication
- **Role-Based Access Control**: Fine-grained permissions
- **Rate Limiting**: Configurable request throttling
- **Audit Logging**: Complete audit trail for compliance
- **Encryption**: Data encryption at rest and in transit

## 🧪 Testing

```bash
# Run tests for specific service
pytest tests/test_payments.py

# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=microservices
```

## 📁 Project Structure

```
isA_user/
├── core/                      # Shared core modules
│   ├── config_manager.py      # Configuration management
│   ├── consul_registry.py     # Service discovery
│   ├── logger.py              # Centralized logging setup
│   ├── logging_config.py      # Loki integration
│   ├── nats_client.py         # Event streaming
│   └── database/              # Database utilities
├── microservices/             # Individual microservices
│   ├── auth_service/
│   ├── payment_service/
│   ├── wallet_service/
│   └── ...
├── deployment/                # Deployment configurations
│   ├── dev/                   # Development environment
│   │   ├── .env
│   │   └── requirements.txt
│   ├── docker/                # Docker configurations
│   │   ├── Dockerfile.user
│   │   └── build.sh
│   └── scripts/               # Management scripts
│       └── start_user_service.sh
├── tests/                     # Test suites
└── docs/                      # Documentation
```

## 🔄 Service Dependencies

```
┌─────────────────┐
│  API Gateway    │
└────────┬────────┘
         │
    ┌────▼─────────────────────────────┐
    │     Service Discovery (Consul)    │
    └────┬─────────────────────────────┘
         │
    ┌────▼────────────────────────────┐
    │  Event Bus (NATS)               │
    └────┬────────────────────────────┘
         │
    ┌────▼────────────────────────────┐
    │  17 Microservices               │
    │  - Auth, Payment, Wallet, etc.  │
    └────┬────────────────────────────┘
         │
    ┌────▼────────────────────────────┐
    │  Infrastructure                 │
    │  - PostgreSQL + pgvector        │
    │  - Redis (optional)             │
    │  - MinIO (object storage)       │
    │  - Loki (centralized logging)   │
    └─────────────────────────────────┘
```

## 🚢 Deployment Environments

### Development
```bash
./deployment/scripts/start_user_service.sh --env dev start
```

### Testing
```bash
./deployment/scripts/start_user_service.sh --env test start
```

### Staging
```bash
./deployment/scripts/start_user_service.sh --env staging start
```

### Production
```bash
./deployment/scripts/start_user_service.sh --env prod start
```

## 📈 Monitoring & Observability

- **Health Checks**: `/health` endpoint on each service
- **Service Status**: Consul UI at http://localhost:8500
- **Logs**: Grafana + Loki at http://localhost:3003
- **Metrics**: Prometheus-compatible metrics (optional)

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/new-feature`
3. Commit changes: `git commit -am 'Add new feature'`
4. Push branch: `git push origin feature/new-feature`
5. Create Pull Request

## 📝 Development Workflow

1. **Add new service**:
   - Create service directory in `microservices/`
   - Implement service logic
   - Add to service list in `start_user_service.sh`
   - Build Docker image

2. **Update existing service**:
   - Modify service code
   - Run tests
   - Rebuild Docker image
   - Restart service

3. **Deploy changes**:
   - Build images: `./deployment/docker/build.sh all dev latest`
   - Push to registry (if needed)
   - Update deployment configuration

## 🆘 Troubleshooting

### Service won't start
```bash
# Check logs
./deployment/scripts/start_user_service.sh logs <service_name>

# Check port availability
lsof -i :8207

# Verify environment variables
cat deployment/dev/.env
```

### Database connection issues
```bash
# Check database is running
psql -h localhost -U postgres -d isa_platform

# Verify DATABASE_URL in .env
echo $DATABASE_URL
```

### Consul registration failed
```bash
# Check Consul is running
curl http://localhost:8500/v1/status/leader

# Restart Consul
consul agent -dev
```

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details

## 📞 Support

- **Documentation**: Check service-specific `/docs` endpoints
- **Issues**: Submit via GitHub Issues
- **Community**: Join our discussion forum

---

**Version**: 2.0.0
**Last Updated**: 2025-10-02
**Status**: ✅ Production Ready with Loki Integration

**Key Features**:
- 17 Microservices
- Centralized Loki Logging
- Docker Support
- Service Discovery (Consul)
- Event Streaming (NATS)
- Unified Management Scripts

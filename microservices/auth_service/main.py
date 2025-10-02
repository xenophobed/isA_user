"""
Authentication Microservice

Responsibilities:
- JWT Token verification (Auth0, Supabase, Local)
- API Key verification and management
- Token generation
- Identity authentication

Note: Authorization/permission control is handled by separate Authorization microservice
"""

from fastapi import FastAPI, HTTPException, Depends, status, Query
import uvicorn
import logging
from contextlib import asynccontextmanager
import sys
import os
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta

# 添加父目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# 导入新实现的服务
from .auth_service import AuthenticationService
from .api_key_service import ApiKeyService
from .api_key_repository import ApiKeyRepository
from .auth_repository import AuthRepository
from .device_auth_service import DeviceAuthService
from .device_auth_repository import DeviceAuthRepository
# Database connection now handled by repositories directly
from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager
from core.logger import setup_service_logger

# 初始化配置
config_manager = ConfigManager("auth_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("auth_service")
api_logger = setup_service_logger("auth_service", "API")
logger = app_logger  # for backward compatibility

# Request/Response Models

class TokenVerificationRequest(BaseModel):
    """Token verification request"""
    token: str = Field(..., description="JWT token")
    provider: Optional[str] = Field(None, description="Provider: auth0, supabase, local")

class TokenVerificationResponse(BaseModel):
    """Token verification response"""
    valid: bool
    provider: Optional[str] = None
    user_id: Optional[str] = None
    email: Optional[str] = None
    expires_at: Optional[datetime] = None
    error: Optional[str] = None

class ApiKeyVerificationRequest(BaseModel):
    """API key verification request"""
    api_key: str = Field(..., description="API key")

class ApiKeyVerificationResponse(BaseModel):
    """API key verification response"""
    valid: bool
    key_id: Optional[str] = None
    organization_id: Optional[str] = None
    name: Optional[str] = None
    permissions: Optional[List[str]] = []
    error: Optional[str] = None

class DevTokenRequest(BaseModel):
    """Development token generation request"""
    user_id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    expires_in: int = Field(3600, description="Expiration time in seconds")

class ApiKeyCreateRequest(BaseModel):
    """API key creation request"""
    organization_id: str = Field(..., description="Organization ID")
    name: str = Field(..., description="Key name")
    permissions: List[str] = Field(default=[], description="Permission list")
    expires_days: Optional[int] = Field(None, description="Expiration days")

class DeviceRegistrationRequest(BaseModel):
    """Device registration request"""
    device_id: str = Field(..., description="Device ID")
    organization_id: str = Field(..., description="Organization ID")
    device_name: Optional[str] = Field(None, description="Device name")
    device_type: Optional[str] = Field(None, description="Device type")
    metadata: Optional[Dict[str, Any]] = Field(default={}, description="Device metadata")
    expires_days: Optional[int] = Field(None, description="Credential expiration days")

class DeviceAuthRequest(BaseModel):
    """Device authentication request"""
    device_id: str = Field(..., description="Device ID")
    device_secret: str = Field(..., description="Device secret")

class DeviceTokenVerificationRequest(BaseModel):
    """Device token verification request"""
    token: str = Field(..., description="Device JWT token")

# ================================
# 服务核心类
# ================================

class AuthMicroservice:
    """认证微服务核心类"""
    
    def __init__(self):
        self.auth_service = None
        self.api_key_service = None
        self.api_key_repository = None
        self.auth_repository = None
        self.device_auth_service = None
        self.device_auth_repository = None
    
    async def initialize(self):
        """初始化服务"""
        try:
            logger.info("Initializing authentication microservice...")

            # 初始化repository (they now handle their own connections)
            self.api_key_repository = ApiKeyRepository()
            self.auth_repository = AuthRepository()
            self.device_auth_repository = DeviceAuthRepository()

            # 初始化services with config
            self.auth_service = AuthenticationService(config)
            self.api_key_service = ApiKeyService(self.api_key_repository)
            self.device_auth_service = DeviceAuthService(self.device_auth_repository)

            logger.info("Authentication microservice initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize authentication microservice: {e}")
            raise
    
    async def shutdown(self):
        """关闭服务"""
        if self.auth_service:
            await self.auth_service.close()
        logger.info("Authentication microservice shutdown completed")

# 全局服务实例
auth_microservice = AuthMicroservice()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    # Initialize microservice
    await auth_microservice.initialize()
    
    # Register with Consul
    consul_registry = ConsulRegistry(
        service_name="auth",
        service_port=config.service_port,
        consul_host=config.consul_host,
        consul_port=config.consul_port,
        service_host=config.service_host,
        tags=["microservice", "auth", "api"]
    )
    
    if consul_registry.register():
        consul_registry.start_maintenance()
        app.state.consul_registry = consul_registry
        logger.info("Auth service registered with Consul")
    else:
        logger.warning("Failed to register with Consul, continuing without service discovery")
    
    yield
    
    # Cleanup
    if hasattr(app.state, 'consul_registry'):
        app.state.consul_registry.stop_maintenance()
        app.state.consul_registry.deregister()
    
    await auth_microservice.shutdown()

# Create FastAPI application
app = FastAPI(
    title="Authentication Microservice",
    description="Pure authentication microservice - JWT verification, API key management",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware is handled by the Gateway
# Remove local CORS to avoid duplicate headers

# Dependency Injection

def get_auth_service() -> AuthenticationService:
    return auth_microservice.auth_service

def get_api_key_service() -> ApiKeyService:
    return auth_microservice.api_key_service

def get_auth_repository() -> AuthRepository:
    return auth_microservice.auth_repository

def get_device_auth_service() -> DeviceAuthService:
    return auth_microservice.device_auth_service

# Health Check Endpoints

@app.get("/")
async def root():
    """Root health check"""
    return {
        "service": "auth_microservice",
        "status": "healthy",
        "version": "2.0.0",
        "timestamp": datetime.now(tz=timezone.utc).isoformat()
    }

@app.get("/health")
async def health_check():
    """Service health check"""
    return {
        "status": "healthy",
        "service": "auth_microservice",
        "port": config.service_port,
        "version": "2.0.0",
        "capabilities": [
            "jwt_verification",
            "api_key_management",
            "token_generation"
        ],
        "providers": ["auth0", "supabase", "local"]
    }

@app.get("/api/v1/auth/info")
async def get_auth_info():
    """Authentication service information"""
    return {
        "service": "auth_microservice",
        "version": "2.0.0",
        "description": "Pure authentication microservice",
        "capabilities": {
            "jwt_verification": ["auth0", "supabase", "local"],
            "api_key_management": True,
            "token_generation": True
        },
        "endpoints": {
            "verify_token": "/api/v1/auth/verify-token",
            "verify_api_key": "/api/v1/auth/verify-api-key",
            "generate_dev_token": "/api/v1/auth/dev-token",
            "manage_api_keys": "/api/v1/auth/api-keys"
        }
    }

# JWT Token Authentication Endpoints

@app.post("/api/v1/auth/verify-token", response_model=TokenVerificationResponse)
async def verify_token(
    request: TokenVerificationRequest,
    auth_service: AuthenticationService = Depends(get_auth_service)
):
    """Verify JWT Token"""
    try:
        result = await auth_service.verify_token(
            token=request.token,
            provider=request.provider
        )
        
        return TokenVerificationResponse(
            valid=result.get("valid", False),
            provider=result.get("provider"),
            user_id=result.get("user_id"),
            email=result.get("email"),
            expires_at=result.get("expires_at"),
            error=result.get("error") if not result.get("valid") else None
        )
        
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        return TokenVerificationResponse(
            valid=False,
            error=f"Verification failed: {str(e)}"
        )

@app.post("/api/v1/auth/dev-token")
async def generate_dev_token(
    request: DevTokenRequest,
    auth_service: AuthenticationService = Depends(get_auth_service)
):
    """Generate development token"""
    try:
        result = await auth_service.generate_dev_token(
            user_id=request.user_id,
            email=request.email,
            expires_in=request.expires_in
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Token generation failed")
            )
        
        return {
            "success": True,
            "token": result["token"],
            "expires_in": result["expires_in"],
            "token_type": "Bearer",
            "user_id": result["user_id"],
            "email": result["email"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dev token generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token generation failed"
        )

@app.get("/api/v1/auth/user-info")
async def get_user_info_from_token(
    token: str = Query(..., description="JWT token to extract user info from"),
    auth_service: AuthenticationService = Depends(get_auth_service)
):
    """Extract user information from token"""
    try:
        result = await auth_service.get_user_info_from_token(token)
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=result.get("error", "Invalid token")
            )
        
        return {
            "user_id": result["user_id"],
            "email": result["email"],
            "provider": result["provider"],
            "expires_at": result["expires_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User info extraction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User info extraction failed"
        )

# API Key Management Endpoints

@app.post("/api/v1/auth/verify-api-key", response_model=ApiKeyVerificationResponse)
async def verify_api_key(
    request: ApiKeyVerificationRequest,
    api_key_service: ApiKeyService = Depends(get_api_key_service)
):
    """Verify API key"""
    try:
        result = await api_key_service.verify_api_key(request.api_key)
        
        return ApiKeyVerificationResponse(
            valid=result.get("valid", False),
            key_id=result.get("key_id"),
            organization_id=result.get("organization_id"),
            name=result.get("name"),
            permissions=result.get("permissions", []),
            error=result.get("error") if not result.get("valid") else None
        )
        
    except Exception as e:
        logger.error(f"API key verification failed: {e}")
        return ApiKeyVerificationResponse(
            valid=False,
            error=f"Verification failed: {str(e)}"
        )

@app.post("/api/v1/auth/api-keys")
async def create_api_key(
    request: ApiKeyCreateRequest,
    api_key_service: ApiKeyService = Depends(get_api_key_service)
):
    """Create API key"""
    try:
        result = await api_key_service.create_api_key(
            organization_id=request.organization_id,
            name=request.name,
            permissions=request.permissions,
            expires_days=request.expires_days
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to create API key")
            )
        
        return {
            "success": True,
            "api_key": result["api_key"],
            "key_id": result["key_id"],
            "name": result["name"],
            "expires_at": result["expires_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API key creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key creation failed"
        )

@app.get("/api/v1/auth/api-keys/{organization_id}")
async def list_api_keys(
    organization_id: str,
    api_key_service: ApiKeyService = Depends(get_api_key_service)
):
    """List organization API keys"""
    try:
        result = await api_key_service.list_api_keys(organization_id)
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to list API keys")
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API keys listing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API keys listing failed"
        )

@app.delete("/api/v1/auth/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    organization_id: str,
    api_key_service: ApiKeyService = Depends(get_api_key_service)
):
    """Revoke API key"""
    try:
        result = await api_key_service.revoke_api_key(key_id, organization_id)
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to revoke API key")
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API key revocation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key revocation failed"
        )

# Device Authentication Endpoints

@app.post("/api/v1/auth/device/register")
async def register_device(
    request: DeviceRegistrationRequest,
    device_auth_service: DeviceAuthService = Depends(get_device_auth_service)
):
    """Register a new device and get credentials"""
    try:
        # 准备设备数据
        device_data = request.model_dump()
        
        # 如果指定了过期天数，计算过期时间
        if device_data.get('expires_days'):
            from datetime import datetime, timezone, timedelta
            device_data['expires_at'] = datetime.now(timezone.utc) + timedelta(days=device_data['expires_days'])
            del device_data['expires_days']
        
        result = await device_auth_service.register_device(device_data)
        
        if not result.get('success'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get('error', 'Failed to register device')
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Device registration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Device registration failed"
        )

@app.post("/api/v1/auth/device/authenticate")
async def authenticate_device(
    request: DeviceAuthRequest,
    device_auth_service: DeviceAuthService = Depends(get_device_auth_service)
):
    """Authenticate a device and get access token"""
    try:
        result = await device_auth_service.authenticate_device(
            device_id=request.device_id,
            device_secret=request.device_secret
        )
        
        if not result.get('authenticated'):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=result.get('error', 'Authentication failed')
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Device authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Device authentication failed"
        )

@app.post("/api/v1/auth/device/verify-token")
async def verify_device_token(
    request: DeviceTokenVerificationRequest,
    device_auth_service: DeviceAuthService = Depends(get_device_auth_service)
):
    """Verify a device JWT token"""
    try:
        result = await device_auth_service.verify_device_token(request.token)
        return result
        
    except Exception as e:
        logger.error(f"Device token verification failed: {e}")
        return {
            'valid': False,
            'error': str(e)
        }

@app.post("/api/v1/auth/device/{device_id}/refresh-secret")
async def refresh_device_secret(
    device_id: str,
    organization_id: str = Query(..., description="Organization ID"),
    device_auth_service: DeviceAuthService = Depends(get_device_auth_service)
):
    """Refresh device secret"""
    try:
        result = await device_auth_service.refresh_device_secret(
            device_id, organization_id
        )
        
        if not result.get('success'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get('error', 'Failed to refresh secret')
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Device secret refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Device secret refresh failed"
        )

@app.delete("/api/v1/auth/device/{device_id}")
async def revoke_device(
    device_id: str,
    organization_id: str = Query(..., description="Organization ID"),
    device_auth_service: DeviceAuthService = Depends(get_device_auth_service)
):
    """Revoke device credentials"""
    try:
        result = await device_auth_service.revoke_device(
            device_id, organization_id
        )
        
        if not result.get('success'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get('error', 'Failed to revoke device')
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Device revocation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Device revocation failed"
        )

@app.get("/api/v1/auth/device/list")
async def list_devices(
    organization_id: str = Query(..., description="Organization ID"),
    device_auth_service: DeviceAuthService = Depends(get_device_auth_service)
):
    """List all devices for an organization"""
    try:
        result = await device_auth_service.list_devices(organization_id)
        
        if not result.get('success'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get('error', 'Failed to list devices')
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Device listing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Device listing failed"
        )

# Service Statistics

@app.get("/api/v1/auth/stats")
async def get_auth_stats():
    """Get authentication service statistics"""
    return {
        "service": "auth_microservice",
        "version": "2.0.0",
        "status": "operational",
        "capabilities": {
            "jwt_providers": ["auth0", "supabase", "local"],
            "api_key_management": True,
            "token_generation": True
        },
        "stats": {
            "uptime": "running",
            "endpoints_count": 8
        }
    }

# Startup Configuration

if __name__ == "__main__":
    uvicorn.run(
        "microservices.auth_service.main:app",
        host=config.service_host,
        port=config.service_port,
        reload=config.debug,
        log_level=config.log_level.lower()
    )
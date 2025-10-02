"""
Organization Microservice

组织管理微服务主应用
Port: 8212
"""

from fastapi import FastAPI, HTTPException, Depends, status, Query, Path, Header
import uvicorn
import logging
from contextlib import asynccontextmanager
import sys
import os
from typing import Optional, List
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Import local components
from .organization_service import (
    OrganizationService, OrganizationServiceError,
    OrganizationNotFoundError, OrganizationAccessDeniedError,
    OrganizationValidationError
)
from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager
from core.logger import setup_service_logger
from .models import (
    OrganizationCreateRequest, OrganizationUpdateRequest,
    OrganizationMemberAddRequest, OrganizationMemberUpdateRequest,
    OrganizationSwitchRequest, OrganizationResponse,
    OrganizationMemberResponse, OrganizationListResponse,
    OrganizationMemberListResponse, OrganizationContextResponse,
    OrganizationStatsResponse, OrganizationUsageResponse,
    OrganizationRole, HealthResponse, ServiceInfo, ServiceStats
)

# Initialize configuration
config_manager = ConfigManager("organization_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("organization_service")
api_logger = setup_service_logger("organization_service", "API")
logger = app_logger  # for backward compatibility


class OrganizationMicroservice:
    """组织微服务核心类"""
    
    def __init__(self):
        self.organization_service = None
    
    async def initialize(self):
        """初始化微服务"""
        try:
            self.organization_service = OrganizationService()
            logger.info("Organization microservice initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize organization microservice: {e}")
            raise
    
    async def shutdown(self):
        """关闭微服务"""
        try:
            logger.info("Organization microservice shutdown completed")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


# Global microservice instance
organization_microservice = OrganizationMicroservice()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Initialize microservice
    await organization_microservice.initialize()
    
    # Register with Consul
    if config.consul_enabled:
        consul_registry = ConsulRegistry(
            service_name=config.service_name,
            service_port=config.service_port,
            consul_host=config.consul_host,
            consul_port=config.consul_port,
            service_host=config.service_host,
            tags=["microservice", "organization", "api"]
        )
        
        if consul_registry.register():
            consul_registry.start_maintenance()
            app.state.consul_registry = consul_registry
            logger.info(f"{config.service_name} registered with Consul")
        else:
            logger.warning("Failed to register with Consul, continuing without service discovery")
    
    yield
    
    # Cleanup
    if config.consul_enabled and hasattr(app.state, 'consul_registry'):
        app.state.consul_registry.stop_maintenance()
        app.state.consul_registry.deregister()
    
    await organization_microservice.shutdown()


# Create FastAPI application
app = FastAPI(
    title="Organization Service",
    description="Organization management microservice",
    version="1.0.0",
    lifespan=lifespan
)

# CORS handled by Gateway


# Dependency injection
def get_organization_service() -> OrganizationService:
    """获取组织服务实例"""
    if not organization_microservice.organization_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Organization service not initialized"
        )
    return organization_microservice.organization_service


def get_current_user_id(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None)
) -> str:
    """从请求头获取当前用户ID"""
    # 优先使用X-User-Id头
    if x_user_id:
        return x_user_id
    
    # TODO: 从JWT token中提取user_id
    if authorization:
        # 这里应该验证JWT并提取user_id
        # 暂时返回测试用户ID
        return "test-user"
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User authentication required"
    )


# ============ Health Check Endpoints ============

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="healthy",
        service=config.service_name,
        port=config.service_port,
        version="1.0.0"
    )


@app.get("/info", response_model=ServiceInfo)
async def service_info():
    """服务信息"""
    return ServiceInfo()


@app.get("/api/v1/organizations/stats", response_model=ServiceStats)
async def get_service_stats(
    service: OrganizationService = Depends(get_organization_service)
):
    """获取服务统计"""
    # TODO: 实现实际的统计逻辑
    return ServiceStats()


# ============ Organization Management Endpoints ============

@app.post("/api/v1/organizations", response_model=OrganizationResponse)
async def create_organization(
    request: OrganizationCreateRequest,
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """创建组织"""
    try:
        return await service.create_organization(request, user_id)
    except OrganizationValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/organizations/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: str = Path(..., description="组织ID"),
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """获取组织信息"""
    try:
        return await service.get_organization(organization_id, user_id)
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.put("/api/v1/organizations/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: str = Path(..., description="组织ID"),
    request: OrganizationUpdateRequest = ...,
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """更新组织信息"""
    try:
        return await service.update_organization(organization_id, request, user_id)
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.delete("/api/v1/organizations/{organization_id}")
async def delete_organization(
    organization_id: str = Path(..., description="组织ID"),
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """删除组织"""
    try:
        success = await service.delete_organization(organization_id, user_id)
        if success:
            return {"message": "Organization deleted successfully"}
        else:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete organization")
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/users/organizations", response_model=OrganizationListResponse)
async def get_user_organizations(
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """获取用户所属的所有组织"""
    try:
        return await service.get_user_organizations(user_id)
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============ Member Management Endpoints ============

@app.post("/api/v1/organizations/{organization_id}/members", response_model=OrganizationMemberResponse)
async def add_organization_member(
    organization_id: str = Path(..., description="组织ID"),
    request: OrganizationMemberAddRequest = ...,
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """添加组织成员"""
    try:
        return await service.add_organization_member(organization_id, request, user_id)
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/organizations/{organization_id}/members", response_model=OrganizationMemberListResponse)
async def get_organization_members(
    organization_id: str = Path(..., description="组织ID"),
    limit: int = Query(100, ge=1, le=1000, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
    role: Optional[OrganizationRole] = Query(None, description="角色过滤"),
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """获取组织成员列表"""
    try:
        return await service.get_organization_members(organization_id, user_id, limit, offset, role)
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.put("/api/v1/organizations/{organization_id}/members/{member_user_id}", response_model=OrganizationMemberResponse)
async def update_organization_member(
    organization_id: str = Path(..., description="组织ID"),
    member_user_id: str = Path(..., description="成员用户ID"),
    request: OrganizationMemberUpdateRequest = ...,
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """更新组织成员"""
    try:
        return await service.update_organization_member(organization_id, member_user_id, request, user_id)
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.delete("/api/v1/organizations/{organization_id}/members/{member_user_id}")
async def remove_organization_member(
    organization_id: str = Path(..., description="组织ID"),
    member_user_id: str = Path(..., description="成员用户ID"),
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """移除组织成员"""
    try:
        success = await service.remove_organization_member(organization_id, member_user_id, user_id)
        if success:
            return {"message": "Member removed successfully"}
        else:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to remove member")
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============ Context Switching Endpoints ============

@app.post("/api/v1/organizations/context", response_model=OrganizationContextResponse)
async def switch_organization_context(
    request: OrganizationSwitchRequest,
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """切换用户上下文（组织或个人）"""
    try:
        return await service.switch_user_context(user_id, request.organization_id)
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============ Statistics and Analytics Endpoints ============

@app.get("/api/v1/organizations/{organization_id}/stats", response_model=OrganizationStatsResponse)
async def get_organization_stats(
    organization_id: str = Path(..., description="组织ID"),
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """获取组织统计信息"""
    try:
        return await service.get_organization_stats(organization_id, user_id)
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/organizations/{organization_id}/usage", response_model=OrganizationUsageResponse)
async def get_organization_usage(
    organization_id: str = Path(..., description="组织ID"),
    start_date: Optional[datetime] = Query(None, description="开始日期"),
    end_date: Optional[datetime] = Query(None, description="结束日期"),
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """获取组织使用量"""
    try:
        return await service.get_organization_usage(organization_id, user_id, start_date, end_date)
    except OrganizationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OrganizationAccessDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============ Platform Admin Endpoints ============

@app.get("/api/v1/admin/organizations", response_model=OrganizationListResponse)
async def list_all_organizations(
    limit: int = Query(100, ge=1, le=1000, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    plan: Optional[str] = Query(None, description="计划过滤"),
    status: Optional[str] = Query(None, description="状态过滤"),
    user_id: str = Depends(get_current_user_id),
    service: OrganizationService = Depends(get_organization_service)
):
    """获取所有组织列表（平台管理员）"""
    try:
        # TODO: 验证用户是否是平台管理员
        return await service.list_all_organizations(limit, offset, search, plan, status)
    except OrganizationServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


if __name__ == "__main__":
    # Print configuration summary for debugging
    config_manager.print_config_summary()
    
    uvicorn.run(
        "microservices.organization_service.main:app",
        host=config.service_host,
        port=config.service_port,
        reload=config.debug,
        log_level=config.log_level.lower()
    )
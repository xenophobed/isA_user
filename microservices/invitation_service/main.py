"""
Invitation Microservice

邀请管理微服务主入口
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, status, Query, Request

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager
from core.logger import setup_service_logger
from .invitation_service import InvitationService
from .models import (
    HealthResponse, ServiceInfo,
    InvitationCreateRequest, AcceptInvitationRequest,
    InvitationDetailResponse, InvitationListResponse, AcceptInvitationResponse,
    OrganizationRole
)

# Initialize configuration
config_manager = ConfigManager("invitation_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("invitation_service")
api_logger = setup_service_logger("invitation_service", "API")
logger = app_logger  # for backward compatibility

# 全局服务实例
invitation_service = None
consul_registry = None


def get_user_id(request: Request) -> str:
    """从请求头获取用户ID"""
    x_user_id = request.headers.get("X-User-Id")
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication required"
        )
    return x_user_id


def get_invitation_service() -> InvitationService:
    """获取邀请服务实例"""
    global invitation_service
    if invitation_service is None:
        invitation_service = InvitationService()
    return invitation_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global consul_registry, invitation_service
    
    try:
        # 初始化服务
        invitation_service = InvitationService()
        logger.info("Invitation microservice initialized successfully")
        
        # 注册到Consul
        if config.consul_enabled:
            consul_registry = ConsulRegistry(
                service_name=config.service_name,
                service_port=config.service_port,
                consul_host=config.consul_host,
                consul_port=config.consul_port,
                service_host=config.service_host,
                tags=["microservice", "invitation", "api"]
            )
            
            if consul_registry.register():
                consul_registry.start_maintenance()
                logger.info(f"{config.service_name} registered with Consul")
            else:
                logger.warning("Failed to register with Consul, continuing without service discovery")
        
        yield
        
    except Exception as e:
        logger.error(f"Error during service startup: {e}")
        raise
    finally:
        # 清理资源
        if config.consul_enabled and consul_registry:
            try:
                consul_registry.deregister()
                logger.info("Service deregistered from Consul")
            except Exception as e:
                logger.error(f"Error deregistering from Consul: {e}")
        
        logger.info("Invitation microservice shutdown completed")


# 创建FastAPI应用
app = FastAPI(
    title="Invitation Service",
    description="Organization invitation management microservice",
    version="1.0.0",
    lifespan=lifespan
)

# 添加CORS中间件
# CORS handled by Gateway


# ============ Health & Info Endpoints ============

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


# ============ Invitation Management Endpoints ============

@app.post("/api/v1/organizations/{organization_id}/invitations", response_model=dict)
async def create_invitation(
    organization_id: str,
    request_data: InvitationCreateRequest,
    request: Request,
    invitation_service: InvitationService = Depends(get_invitation_service)
):
    """创建邀请"""
    try:
        user_id = get_user_id(request)
        success, invitation, message = await invitation_service.create_invitation(
            organization_id=organization_id,
            inviter_user_id=user_id,
            email=request_data.email,
            role=request_data.role,
            message=request_data.message
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        return {
            "invitation_id": invitation.invitation_id,
            "email": invitation.email,
            "role": invitation.role.value,
            "status": invitation.status.value,
            "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
            "message": message
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating invitation: {e}")
        raise HTTPException(status_code=500, detail="Failed to create invitation")


@app.get("/api/v1/invitations/{invitation_token}", response_model=InvitationDetailResponse)
async def get_invitation(
    invitation_token: str,
    invitation_service: InvitationService = Depends(get_invitation_service)
):
    """根据令牌获取邀请信息"""
    try:
        success, invitation_detail, message = await invitation_service.get_invitation_by_token(invitation_token)
        
        if not success:
            if "not found" in message.lower():
                raise HTTPException(status_code=404, detail=message)
            else:
                raise HTTPException(status_code=400, detail=message)
        
        return invitation_detail
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting invitation: {e}")
        raise HTTPException(status_code=500, detail="Failed to get invitation")


@app.post("/api/v1/invitations/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(
    request_data: AcceptInvitationRequest,
    request: Request,
    invitation_service: InvitationService = Depends(get_invitation_service)
):
    """接受邀请"""
    try:
        user_id = get_user_id(request)
        # 如果请求中有user_id，使用它，否则使用header中的
        actual_user_id = request_data.user_id if request_data.user_id else user_id
        
        success, accept_response, message = await invitation_service.accept_invitation(
            invitation_token=request_data.invitation_token,
            user_id=actual_user_id
        )
        
        if not success:
            if "not found" in message.lower():
                raise HTTPException(status_code=404, detail=message)
            else:
                raise HTTPException(status_code=400, detail=message)
        
        return accept_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error accepting invitation: {e}")
        raise HTTPException(status_code=500, detail="Failed to accept invitation")


@app.get("/api/v1/organizations/{organization_id}/invitations", response_model=InvitationListResponse)
async def get_organization_invitations(
    organization_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    invitation_service: InvitationService = Depends(get_invitation_service)
):
    """获取组织邀请列表"""
    try:
        user_id = get_user_id(request)
        success, invitation_list, message = await invitation_service.get_organization_invitations(
            organization_id=organization_id,
            user_id=user_id,
            limit=limit,
            offset=offset
        )
        
        if not success:
            if "permission" in message.lower():
                raise HTTPException(status_code=403, detail=message)
            else:
                raise HTTPException(status_code=400, detail=message)
        
        return invitation_list
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting organization invitations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get invitations")


@app.delete("/api/v1/invitations/{invitation_id}")
async def cancel_invitation(
    invitation_id: str,
    request: Request,
    invitation_service: InvitationService = Depends(get_invitation_service)
):
    """取消邀请"""
    try:
        user_id = get_user_id(request)
        success, message = await invitation_service.cancel_invitation(
            invitation_id=invitation_id,
            user_id=user_id
        )
        
        if not success:
            if "not found" in message.lower():
                raise HTTPException(status_code=404, detail=message)
            elif "permission" in message.lower():
                raise HTTPException(status_code=403, detail=message)
            else:
                raise HTTPException(status_code=400, detail=message)
        
        return {"message": message}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling invitation: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel invitation")


@app.post("/api/v1/invitations/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: str,
    request: Request,
    invitation_service: InvitationService = Depends(get_invitation_service)
):
    """重发邀请"""
    try:
        user_id = get_user_id(request)
        success, message = await invitation_service.resend_invitation(
            invitation_id=invitation_id,
            user_id=user_id
        )
        
        if not success:
            if "not found" in message.lower():
                raise HTTPException(status_code=404, detail=message)
            elif "permission" in message.lower():
                raise HTTPException(status_code=403, detail=message)
            else:
                raise HTTPException(status_code=400, detail=message)
        
        return {"message": message}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resending invitation: {e}")
        raise HTTPException(status_code=500, detail="Failed to resend invitation")


# ============ Admin Endpoints ============

@app.post("/api/v1/admin/expire-invitations")
async def expire_old_invitations(
    invitation_service: InvitationService = Depends(get_invitation_service)
):
    """过期旧邀请（管理员端点）"""
    try:
        success, expired_count, message = await invitation_service.expire_old_invitations()
        
        if not success:
            raise HTTPException(status_code=500, detail=message)
        
        return {
            "expired_count": expired_count,
            "message": message
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error expiring invitations: {e}")
        raise HTTPException(status_code=500, detail="Failed to expire invitations")


if __name__ == "__main__":
    import uvicorn
    # Print configuration summary for debugging
    config_manager.print_config_summary()
    
    uvicorn.run(
        app, 
        host=config.service_host, 
        port=config.service_port,
        log_level=config.log_level.lower()
    )
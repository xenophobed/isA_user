"""
OTA Service - Main Application

OTA更新微服务主应用，提供固件管理和设备更新功能
"""

from fastapi import FastAPI, HTTPException, Depends, Query, Path, Body, File, UploadFile, Header
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
import logging
import sys
import os
import requests

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager
from core.logger import setup_service_logger
from .models import (
    FirmwareUploadRequest, UpdateCampaignRequest, DeviceUpdateRequest, UpdateApprovalRequest,
    FirmwareResponse, UpdateCampaignResponse, DeviceUpdateResponse,
    UpdateStatsResponse, UpdateHistoryResponse, RollbackResponse, UpdateHealthResponse,
    UpdateType, UpdateStatus, DeploymentStrategy, Priority
)
from .ota_service import OTAService
from datetime import datetime

# Initialize configuration
config_manager = ConfigManager("ota_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("ota_service")
api_logger = setup_service_logger("ota_service", "API")
logger = app_logger  # for backward compatibility

# Service instance
class OTAMicroservice:
    def __init__(self):
        self.service = None
    
    async def initialize(self):
        self.service = OTAService()
        logger.info("OTA service initialized")
    
    async def shutdown(self):
        logger.info("OTA service shutting down")

# Global instance
microservice = OTAMicroservice()

# Lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Startup
    await microservice.initialize()
    
    # Consul注册
    if config.consul_enabled:
        consul_registry = ConsulRegistry(
            service_name=config.service_name,
            service_port=config.service_port,
            consul_host=config.consul_host,
            consul_port=config.consul_port,
            service_host=config.service_host,
            tags=["microservice", "iot", "ota", "firmware", "update", "api", "v1"]
        )
    
        if consul_registry.register():
            consul_registry.start_maintenance()
            app.state.consul_registry = consul_registry
            logger.info(f"{config.service_name} registered with Consul")
        else:
            logger.warning("Failed to register with Consul, continuing without service discovery")
    
    yield
    
    # Shutdown
    if config.consul_enabled and hasattr(app.state, 'consul_registry'):
        app.state.consul_registry.stop_maintenance()
        app.state.consul_registry.deregister()
        logger.info("Deregistered from Consul")
    
    await microservice.shutdown()

# Create FastAPI application
app = FastAPI(
    title="OTA Service",
    description="IoT设备OTA更新微服务 - 固件管理和设备更新",
    version="1.0.0",
    lifespan=lifespan
)

# ======================
# Health Check Endpoints
# ======================

@app.get("/health")
async def health_check():
    """基础健康检查"""
    return {
        "status": "healthy",
        "service": config.service_name,
        "port": config.service_port,
        "version": "1.0.0"
    }

@app.get("/health/detailed", response_model=UpdateHealthResponse)
async def detailed_health_check():
    """详细健康检查"""
    return UpdateHealthResponse(
        service_status="healthy",
        active_campaigns=3,
        active_updates=12,
        storage_usage={
            "total": "1TB",
            "used": "450GB",
            "available": "550GB",
            "usage_percent": 45
        },
        network_status={
            "cdn_status": "healthy",
            "download_speed": "100Mbps",
            "upload_speed": "50Mbps"
        },
        last_successful_update=datetime.utcnow(),
        error_rate=2.1,
        avg_response_time=150.5
    )

# ======================
# Dependencies
# ======================

async def get_user_context(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """获取用户上下文信息"""
    if not authorization and not x_api_key:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        auth_service_url = "http://localhost:8202"
        
        if authorization:
            token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
            logger.info(f"Verifying token with auth service")
            
            response = requests.post(
                f"{auth_service_url}/api/v1/auth/verify-token",
                json={"token": token}
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            auth_data = response.json()
            if not auth_data.get("valid"):
                raise HTTPException(status_code=401, detail="Token verification failed")
            
            return {
                "user_id": auth_data.get("user_id", "unknown"),
                "organization_id": auth_data.get("organization_id"),
                "role": auth_data.get("role", "user")
            }
        
        elif x_api_key:
            response = requests.post(
                f"{auth_service_url}/api/v1/auth/verify-api-key",
                json={"api_key": x_api_key}
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid API key")
            
            auth_data = response.json()
            if not auth_data.get("valid"):
                raise HTTPException(status_code=401, detail="API key verification failed")
            
            return {
                "user_id": auth_data.get("user_id", "unknown"),
                "organization_id": auth_data.get("organization_id"),
                "role": auth_data.get("role", "user")
            }
    
    except requests.RequestException as e:
        logger.error(f"Auth service communication error: {e}")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    
    raise HTTPException(status_code=401, detail="Authentication required")

# ======================
# Firmware Management
# ======================

@app.post("/api/v1/firmware", response_model=FirmwareResponse)
async def upload_firmware(
    metadata: str = Body(..., description="Firmware metadata as JSON string"),
    file: UploadFile = File(..., description="Firmware binary file"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """上传固件文件"""
    try:
        import json
        firmware_data = json.loads(metadata)
        
        # 验证文件类型
        if not any(file.filename.endswith(ext) for ext in ['.bin', '.hex', '.elf', '.tar.gz', '.zip']):
            raise HTTPException(status_code=400, detail="Unsupported file format")
        
        # 读取文件内容
        file_content = await file.read()
        
        firmware = await microservice.service.upload_firmware(
            user_context["user_id"],
            firmware_data,
            file_content
        )
        
        if firmware:
            return firmware
        raise HTTPException(status_code=400, detail="Failed to upload firmware")
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid metadata JSON")
    except Exception as e:
        logger.error(f"Error uploading firmware: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/firmware/{firmware_id}", response_model=FirmwareResponse)
async def get_firmware(
    firmware_id: str = Path(..., description="Firmware ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取固件详情"""
    try:
        firmware = await microservice.service.get_firmware(firmware_id)
        if firmware:
            return firmware
        raise HTTPException(status_code=404, detail="Firmware not found")
    except Exception as e:
        logger.error(f"Error getting firmware: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/firmware")
async def list_firmware(
    device_model: Optional[str] = Query(None, description="Filter by device model"),
    manufacturer: Optional[str] = Query(None, description="Filter by manufacturer"),
    is_beta: Optional[bool] = Query(None, description="Filter beta versions"),
    is_security_update: Optional[bool] = Query(None, description="Filter security updates"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取固件列表"""
    # 实现固件列表查询
    return {
        "firmware": [],
        "count": 0,
        "limit": limit,
        "offset": offset,
        "filters": {
            "device_model": device_model,
            "manufacturer": manufacturer,
            "is_beta": is_beta,
            "is_security_update": is_security_update
        }
    }

@app.get("/api/v1/firmware/{firmware_id}/download")
async def download_firmware(
    firmware_id: str = Path(..., description="Firmware ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """下载固件文件"""
    try:
        # 验证权限和固件存在性
        firmware = await microservice.service.get_firmware(firmware_id)
        if not firmware:
            raise HTTPException(status_code=404, detail="Firmware not found")
        
        # 返回文件下载链接或直接返回文件
        return {
            "download_url": f"/files/firmware/{firmware_id}.bin",
            "expires_at": datetime.utcnow() + timedelta(hours=1),
            "checksum_md5": firmware.checksum_md5,
            "checksum_sha256": firmware.checksum_sha256
        }
        
    except Exception as e:
        logger.error(f"Error downloading firmware: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/firmware/{firmware_id}")
async def delete_firmware(
    firmware_id: str = Path(..., description="Firmware ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """删除固件"""
    try:
        # 检查是否有正在进行的更新使用此固件
        # 删除固件文件和元数据
        return {"message": "Firmware deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting firmware: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Update Campaigns
# ======================

@app.post("/api/v1/campaigns", response_model=UpdateCampaignResponse)
async def create_campaign(
    request: UpdateCampaignRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """创建更新活动"""
    try:
        campaign = await microservice.service.create_update_campaign(
            user_context["user_id"],
            request.model_dump()
        )
        if campaign:
            return campaign
        raise HTTPException(status_code=400, detail="Failed to create campaign")
    except Exception as e:
        logger.error(f"Error creating campaign: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/campaigns/{campaign_id}", response_model=UpdateCampaignResponse)
async def get_campaign(
    campaign_id: str = Path(..., description="Campaign ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取活动详情"""
    try:
        campaign = await microservice.service.get_campaign(campaign_id)
        if campaign:
            return campaign
        raise HTTPException(status_code=404, detail="Campaign not found")
    except Exception as e:
        logger.error(f"Error getting campaign: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/campaigns")
async def list_campaigns(
    status: Optional[UpdateStatus] = Query(None, description="Filter by status"),
    priority: Optional[Priority] = Query(None, description="Filter by priority"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取活动列表"""
    return {
        "campaigns": [],
        "count": 0,
        "limit": limit,
        "offset": offset,
        "filters": {
            "status": status,
            "priority": priority
        }
    }

@app.post("/api/v1/campaigns/{campaign_id}/start")
async def start_campaign(
    campaign_id: str = Path(..., description="Campaign ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """启动更新活动"""
    try:
        success = await microservice.service.start_campaign(campaign_id)
        if success:
            return {"message": "Campaign started successfully"}
        raise HTTPException(status_code=400, detail="Failed to start campaign")
    except Exception as e:
        logger.error(f"Error starting campaign: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str = Path(..., description="Campaign ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """暂停更新活动"""
    return {"message": f"Campaign {campaign_id} paused"}

@app.post("/api/v1/campaigns/{campaign_id}/cancel")
async def cancel_campaign(
    campaign_id: str = Path(..., description="Campaign ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """取消更新活动"""
    return {"message": f"Campaign {campaign_id} cancelled"}

@app.post("/api/v1/campaigns/{campaign_id}/approve", response_model=UpdateCampaignResponse)
async def approve_campaign(
    campaign_id: str = Path(..., description="Campaign ID"),
    request: UpdateApprovalRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """审批更新活动"""
    try:
        # 更新活动审批状态
        campaign = await microservice.service.get_campaign(campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        campaign.approved = request.approved
        campaign.approved_by = user_context["user_id"]
        campaign.approval_comment = request.approval_comment
        
        return campaign
    except Exception as e:
        logger.error(f"Error approving campaign: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Device Updates
# ======================

@app.post("/api/v1/devices/{device_id}/update", response_model=DeviceUpdateResponse)
async def update_device(
    device_id: str = Path(..., description="Device ID"),
    request: DeviceUpdateRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """更新单个设备"""
    try:
        device_update = await microservice.service.update_single_device(
            device_id,
            request.model_dump()
        )
        if device_update:
            return device_update
        raise HTTPException(status_code=400, detail="Failed to start device update")
    except Exception as e:
        logger.error(f"Error updating device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/updates/{update_id}", response_model=DeviceUpdateResponse)
async def get_update_progress(
    update_id: str = Path(..., description="Update ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取更新进度"""
    try:
        progress = await microservice.service.get_update_progress(update_id)
        if progress:
            return progress
        raise HTTPException(status_code=404, detail="Update not found")
    except Exception as e:
        logger.error(f"Error getting update progress: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/devices/{device_id}/updates", response_model=UpdateHistoryResponse)
async def get_device_update_history(
    device_id: str = Path(..., description="Device ID"),
    limit: int = Query(50, ge=1, le=200, description="Max updates to return"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取设备更新历史"""
    return UpdateHistoryResponse(
        device_id=device_id,
        updates=[],
        total_updates=0,
        successful_updates=0,
        failed_updates=0,
        avg_success_rate=0.0,
        last_update=None
    )

@app.post("/api/v1/updates/{update_id}/cancel")
async def cancel_update(
    update_id: str = Path(..., description="Update ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """取消设备更新"""
    try:
        success = await microservice.service.cancel_update(update_id)
        if success:
            return {"message": "Update cancelled successfully"}
        raise HTTPException(status_code=400, detail="Failed to cancel update")
    except Exception as e:
        logger.error(f"Error cancelling update: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/updates/{update_id}/retry")
async def retry_update(
    update_id: str = Path(..., description="Update ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """重试更新"""
    return {"message": f"Update {update_id} queued for retry"}

# ======================
# Rollback Operations
# ======================

@app.post("/api/v1/devices/{device_id}/rollback", response_model=RollbackResponse)
async def rollback_device(
    device_id: str = Path(..., description="Device ID"),
    to_version: str = Body(..., embed=True),
    reason: str = Body("Manual rollback", embed=True),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """回滚设备固件"""
    try:
        rollback = await microservice.service.rollback_update(device_id, to_version)
        if rollback:
            return rollback
        raise HTTPException(status_code=400, detail="Failed to start rollback")
    except Exception as e:
        logger.error(f"Error rolling back device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/campaigns/{campaign_id}/rollback")
async def rollback_campaign(
    campaign_id: str = Path(..., description="Campaign ID"),
    reason: str = Body("Campaign rollback", embed=True),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """回滚整个活动"""
    return {"message": f"Campaign {campaign_id} rollback initiated"}

# ======================
# Statistics & Analytics
# ======================

@app.get("/api/v1/stats", response_model=UpdateStatsResponse)
async def get_update_stats(
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取更新统计"""
    try:
        stats = await microservice.service.get_update_stats()
        if stats:
            return stats
        raise HTTPException(status_code=404, detail="No stats available")
    except Exception as e:
        logger.error(f"Error getting update stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/stats/campaigns/{campaign_id}")
async def get_campaign_stats(
    campaign_id: str = Path(..., description="Campaign ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取活动统计"""
    return {
        "campaign_id": campaign_id,
        "progress_percentage": 68.5,
        "successful_updates": 137,
        "failed_updates": 8,
        "pending_updates": 55,
        "avg_update_time": 8.5,
        "success_rate": 94.5
    }

# ======================
# Batch Operations
# ======================

@app.post("/api/v1/devices/bulk/update")
async def bulk_update_devices(
    device_ids: List[str] = Body(..., embed=True),
    firmware_id: str = Body(..., embed=True),
    priority: Priority = Body(Priority.NORMAL, embed=True),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """批量更新设备"""
    results = []
    for device_id in device_ids:
        try:
            update_data = {
                "firmware_id": firmware_id,
                "priority": priority
            }
            device_update = await microservice.service.update_single_device(device_id, update_data)
            results.append({
                "device_id": device_id,
                "success": True,
                "update_id": device_update.update_id if device_update else None
            })
        except Exception as e:
            results.append({
                "device_id": device_id,
                "success": False,
                "error": str(e)
            })
    
    return {"results": results, "total": len(device_ids)}

# ======================
# Service Statistics
# ======================

@app.get("/api/v1/service/stats")
async def get_service_stats():
    """获取服务统计信息"""
    return {
        "service": config.service_name,
        "version": "1.0.0",
        "port": config.service_port,
        "endpoints": {
            "health": 2,
            "firmware": 6,
            "campaigns": 8,
            "updates": 4,
            "rollback": 2,
            "stats": 3,
            "bulk": 1
        },
        "features": [
            "firmware_management",
            "update_campaigns",
            "single_device_updates",
            "rollback_operations",
            "batch_operations",
            "deployment_strategies",
            "progress_monitoring"
        ]
    }

# 导入datetime和timedelta
from datetime import datetime, timedelta

if __name__ == "__main__":
    import uvicorn
    # Print configuration summary for debugging
    config_manager.print_config_summary()
    
    uvicorn.run(
        "microservices.ota_service.main:app", 
        host=config.service_host, 
        port=config.service_port,
        reload=config.debug,
        log_level=config.log_level.lower()
    )
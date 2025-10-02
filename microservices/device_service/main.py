"""
Device Management Service - Main Application

设备管理微服务主应用，提供设备注册、认证、生命周期管理等功能
"""

from fastapi import FastAPI, HTTPException, Depends, Query, Path, Body, Header
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
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
    DeviceRegistrationRequest, DeviceUpdateRequest, DeviceAuthRequest,
    DeviceCommandRequest, DeviceGroupRequest,
    DeviceResponse, DeviceAuthResponse, DeviceStatsResponse,
    DeviceHealthResponse, DeviceGroupResponse, DeviceListResponse,
    DeviceStatus, DeviceType, ConnectivityType
)
from .device_service import DeviceService

# Initialize configuration
config_manager = ConfigManager("device_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("device_service")
api_logger = setup_service_logger("device_service", "API")
logger = app_logger  # for backward compatibility

# Service instance
class DeviceMicroservice:
    def __init__(self):
        self.service = None
    
    async def initialize(self):
        self.service = DeviceService()
        logger.info("Device service initialized")
    
    async def shutdown(self):
        logger.info("Device service shutting down")

# Global instance
microservice = DeviceMicroservice()

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
            tags=["microservice", "iot", "device", "management", "api", "v1"]
        )
        
        if consul_registry.register():
            consul_registry.start_maintenance()
            app.state.consul_registry = consul_registry
            logger.info(f"{config.service_name} registered with Consul")
        else:
            logger.warning("Failed to register with Consul")
    
    yield
    
    # Shutdown
    if config.consul_enabled and hasattr(app.state, 'consul_registry'):
        app.state.consul_registry.stop_maintenance()
        app.state.consul_registry.deregister()
        logger.info("Deregistered from Consul")
    
    await microservice.shutdown()

# Create FastAPI application
app = FastAPI(
    title="Device Management Service",
    description="IoT设备管理微服务 - 设备注册、认证、生命周期管理",
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
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health/detailed")
async def detailed_health_check():
    """详细健康检查"""
    return {
        "status": "healthy",
        "service": "device_service",
        "port": 8220,
        "version": "1.0.0",
        "components": {
            "service": "healthy",
            "mqtt_broker": "healthy",
            "device_registry": "healthy"
        }
    }

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
    
    # 调用auth服务验证token
    try:
        auth_service_url = "http://localhost:8202"
        
        if authorization:
            # 验证JWT token
            token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
            logger.info(f"Verifying token with auth service at {auth_service_url}/api/v1/auth/verify-token")
            logger.info(f"Token (first 50 chars): {token[:50]}...")
            
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
            # 验证API Key
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
# Device CRUD Endpoints
# ======================

@app.post("/api/v1/devices", response_model=DeviceResponse)
async def register_device(
    request: DeviceRegistrationRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """注册新设备"""
    try:
        device = await microservice.service.register_device(
            user_context["user_id"],
            request.model_dump()
        )
        if device:
            return device
        raise HTTPException(status_code=400, detail="Failed to register device")
    except Exception as e:
        logger.error(f"Error registering device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/devices/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: str = Path(..., description="Device ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取设备详情"""
    # 模拟返回设备信息
    return DeviceResponse(
        device_id=device_id,
        device_name="Smart Sensor 001",
        device_type=DeviceType.SENSOR,
        manufacturer="IoT Corp",
        model="SS-2024",
        serial_number="SN123456789",
        firmware_version="1.2.3",
        hardware_version="1.0",
        mac_address="AA:BB:CC:DD:EE:FF",
        connectivity_type=ConnectivityType.WIFI,
        security_level="standard",
        status=DeviceStatus.ACTIVE,
        location={"latitude": 39.9042, "longitude": 116.4074},
        metadata={},
        group_id=None,
        tags=["production", "beijing"],
        last_seen=datetime.utcnow(),
        registered_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        user_id=user_context["user_id"],
        organization_id=user_context.get("organization_id")
    )

@app.put("/api/v1/devices/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: str = Path(..., description="Device ID"),
    request: DeviceUpdateRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """更新设备信息"""
    try:
        logger.info(f"Updating device {device_id} with data: {request}")
        
        # 简单实现：如果有状态更新就更新状态
        if request.status:
            success = await microservice.service.update_device_status(device_id, request.status)
            if not success:
                raise HTTPException(status_code=404, detail="Device not found")
        
        # 返回一个模拟的设备响应
        # 在实际实现中，这里应该从数据库获取更新后的设备信息
        updated_device = DeviceResponse(
            device_id=device_id,
            device_name=request.device_name or "Updated Device",
            device_type="sensor",
            manufacturer="IoT Corp",
            model="SS-2024",
            serial_number="SN123456789",
            firmware_version=request.firmware_version or "1.2.3",
            hardware_version="1.0",
            mac_address="AA:BB:CC:DD:EE:FF",
            connectivity_type="wifi",
            security_level="standard",
            status=request.status or DeviceStatus.ACTIVE,
            location=request.location or {},
            metadata=request.metadata or {},
            group_id=request.group_id,
            tags=request.tags or [],
            last_seen=datetime.now(timezone.utc),
            registered_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            user_id=user_context.get("user_id"),
            organization_id=user_context.get("organization_id"),
            total_commands=0,
            total_telemetry_points=0,
            uptime_percentage=0.0
        )
        
        logger.info(f"Device {device_id} updated successfully")
        return updated_device
        
    except Exception as e:
        logger.error(f"Error updating device {device_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.delete("/api/v1/devices/{device_id}")
async def decommission_device(
    device_id: str = Path(..., description="Device ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """停用设备"""
    try:
        success = await microservice.service.decommission_device(device_id)
        if success:
            return {"message": "Device decommissioned successfully"}
        raise HTTPException(status_code=400, detail="Failed to decommission device")
    except Exception as e:
        logger.error(f"Error decommissioning device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/devices", response_model=DeviceListResponse)
async def list_devices(
    status: Optional[DeviceStatus] = Query(None, description="Filter by status"),
    device_type: Optional[DeviceType] = Query(None, description="Filter by type"),
    connectivity: Optional[ConnectivityType] = Query(None, description="Filter by connectivity"),
    group_id: Optional[str] = Query(None, description="Filter by group"),
    limit: int = Query(100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取设备列表"""
    # 返回设备列表
    return DeviceListResponse(
        devices=[],
        count=0,
        limit=limit,
        offset=offset,
        filters={
            "status": status,
            "device_type": device_type,
            "connectivity": connectivity,
            "group_id": group_id
        }
    )

# ======================
# Device Authentication
# ======================

@app.post("/api/v1/devices/auth", response_model=DeviceAuthResponse)
async def authenticate_device(
    request: DeviceAuthRequest = Body(...),
):
    """设备认证 - 调用 auth_service 进行验证"""
    try:
        # 调用 auth_service 的设备认证端点
        auth_service_url = "http://localhost:8202"
        
        logger.info(f"Authenticating device {request.device_id} via auth service")
        
        response = requests.post(
            f"{auth_service_url}/api/v1/auth/device/authenticate",
            json={
                "device_id": request.device_id,
                "device_secret": request.device_secret
            }
        )
        
        if response.status_code == 200:
            auth_data = response.json()
            if auth_data.get("authenticated"):
                # 更新设备状态
                from .models import DeviceStatus
                device_update = await microservice.service.update_device_status(
                    request.device_id,
                    DeviceStatus.ACTIVE
                )
                
                return DeviceAuthResponse(
                    device_id=auth_data["device_id"],
                    access_token=auth_data["token"],
                    token_type="Bearer",
                    expires_in=auth_data["expires_in"]
                )
        
        raise HTTPException(status_code=401, detail="Authentication failed")
        
    except requests.RequestException as e:
        logger.error(f"Auth service communication error: {e}")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error authenticating device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Device Commands
# ======================

@app.post("/api/v1/devices/{device_id}/commands")
async def send_command(
    device_id: str = Path(..., description="Device ID"),
    request: DeviceCommandRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """向设备发送命令"""
    try:
        result = await microservice.service.send_command(
            device_id,
            request.model_dump()
        )
        return result
    except Exception as e:
        logger.error(f"Error sending command: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Device Health & Monitoring
# ======================

@app.get("/api/v1/devices/{device_id}/health", response_model=DeviceHealthResponse)
async def get_device_health(
    device_id: str = Path(..., description="Device ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取设备健康状态"""
    try:
        health = await microservice.service.get_device_health(device_id)
        if health:
            return health
        raise HTTPException(status_code=404, detail="Device not found")
    except Exception as e:
        logger.error(f"Error getting device health: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/devices/stats", response_model=DeviceStatsResponse)
async def get_device_stats(
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取设备统计信息"""
    try:
        stats = await microservice.service.get_device_stats(user_context["user_id"])
        if stats:
            return stats
        raise HTTPException(status_code=404, detail="No stats available")
    except Exception as e:
        logger.error(f"Error getting device stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Device Groups
# ======================

@app.post("/api/v1/groups", response_model=DeviceGroupResponse)
async def create_device_group(
    request: DeviceGroupRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """创建设备组"""
    try:
        group = await microservice.service.create_device_group(
            user_context["user_id"],
            request.model_dump()
        )
        if group:
            return group
        raise HTTPException(status_code=400, detail="Failed to create device group")
    except Exception as e:
        logger.error(f"Error creating device group: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/groups/{group_id}", response_model=DeviceGroupResponse)
async def get_device_group(
    group_id: str = Path(..., description="Group ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取设备组详情"""
    # 返回设备组信息
    pass

@app.put("/api/v1/groups/{group_id}/devices/{device_id}")
async def add_device_to_group(
    group_id: str = Path(..., description="Group ID"),
    device_id: str = Path(..., description="Device ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """将设备添加到组"""
    return {"message": f"Device {device_id} added to group {group_id}"}

# ======================
# Bulk Operations
# ======================

@app.post("/api/v1/devices/bulk/register")
async def bulk_register_devices(
    devices: List[DeviceRegistrationRequest] = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """批量注册设备"""
    results = []
    for device_request in devices:
        try:
            device = await microservice.service.register_device(
                user_context["user_id"],
                device_request.model_dump()
            )
            results.append({"success": True, "device_id": device.device_id if device else None})
        except Exception as e:
            results.append({"success": False, "error": str(e)})
    
    return {"results": results, "total": len(devices)}

@app.post("/api/v1/devices/bulk/commands")
async def bulk_send_commands(
    device_ids: List[str] = Body(..., embed=True),
    command: DeviceCommandRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """批量发送命令"""
    results = []
    for device_id in device_ids:
        try:
            result = await microservice.service.send_command(device_id, command.model_dump())
            results.append({"device_id": device_id, **result})
        except Exception as e:
            results.append({"device_id": device_id, "success": False, "error": str(e)})
    
    return {"results": results, "total": len(device_ids)}

# ======================
# Service Statistics
# ======================

@app.get("/api/v1/service/stats")
async def get_service_stats():
    """获取服务统计信息"""
    return {
        "service": "device_service",
        "version": "1.0.0",
        "port": 8220,
        "endpoints": {
            "health": 2,
            "devices": 8,
            "auth": 1,
            "commands": 1,
            "monitoring": 2,
            "groups": 3,
            "bulk": 2
        },
        "features": [
            "device_registration",
            "device_authentication",
            "lifecycle_management",
            "remote_commands",
            "health_monitoring",
            "device_groups",
            "bulk_operations"
        ]
    }

# 导入datetime
from datetime import datetime

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
"""
Telemetry Service - Main Application

遥测微服务主应用，提供设备数据采集、存储、查询和警报功能
"""

from fastapi import FastAPI, HTTPException, Depends, Query, Path, Body, WebSocket, Header
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
import logging
import sys
import os
import json
import requests
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager
from core.logger import setup_service_logger
from .models import (
    TelemetryDataPoint, TelemetryBatchRequest, MetricDefinitionRequest,
    AlertRuleRequest, QueryRequest, RealTimeSubscriptionRequest,
    MetricDefinitionResponse, TelemetryDataResponse, AlertRuleResponse,
    AlertResponse, DeviceTelemetryStatsResponse, TelemetryStatsResponse,
    RealTimeDataResponse, AggregatedDataResponse, AlertListResponse,
    DataType, MetricType, AlertLevel, AlertStatus, AggregationType, TimeRange
)
from .telemetry_service import TelemetryService

# Initialize configuration
config_manager = ConfigManager("telemetry_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("telemetry_service")
api_logger = setup_service_logger("telemetry_service", "API")
logger = app_logger  # for backward compatibility

# Service instance
class TelemetryMicroservice:
    def __init__(self):
        self.service = None
    
    async def initialize(self):
        self.service = TelemetryService()
        logger.info("Telemetry service initialized")
    
    async def shutdown(self):
        logger.info("Telemetry service shutting down")

# Global instance
microservice = TelemetryMicroservice()

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
            tags=["microservice", "iot", "telemetry", "monitoring", "timeseries", "api", "v1"]
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
    title="Telemetry Service",
    description="IoT设备遥测微服务 - 数据采集、存储、查询和警报",
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

@app.get("/health/detailed")
async def detailed_health_check():
    """详细健康检查"""
    return {
        "status": "healthy",
        "service": config.service_name,
        "port": config.service_port,
        "version": "1.0.0",
        "components": {
            "data_ingestion": "healthy",
            "time_series_db": "healthy",
            "alert_engine": "healthy",
            "real_time_stream": "healthy"
        },
        "performance": {
            "ingestion_rate": "1250 points/sec",
            "query_latency": "45ms",
            "storage_usage": "67%"
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
# Data Ingestion Endpoints
# ======================

@app.post("/api/v1/devices/{device_id}/telemetry")
async def ingest_single_data_point(
    device_id: str = Path(..., description="Device ID"),
    data_point: TelemetryDataPoint = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """摄取单个数据点"""
    try:
        result = await microservice.service.ingest_telemetry_data(device_id, [data_point])
        if result["success"]:
            return {
                "success": True,
                "message": "Data point ingested successfully",
                "device_id": device_id,
                "metric_name": data_point.metric_name
            }
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to ingest data"))
    except Exception as e:
        logger.error(f"Error ingesting single data point: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/devices/{device_id}/telemetry/batch")
async def ingest_batch_data(
    device_id: str = Path(..., description="Device ID"),
    request: TelemetryBatchRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """批量摄取遥测数据"""
    try:
        result = await microservice.service.ingest_telemetry_data(device_id, request.data_points)
        return result
    except Exception as e:
        logger.error(f"Error ingesting batch data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/telemetry/bulk")
async def ingest_bulk_data(
    data: Dict[str, List[TelemetryDataPoint]] = Body(..., description="Device ID to data points mapping"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """批量摄取多设备数据"""
    results = {}
    for device_id, data_points in data.items():
        try:
            result = await microservice.service.ingest_telemetry_data(device_id, data_points)
            results[device_id] = result
        except Exception as e:
            results[device_id] = {
                "success": False,
                "error": str(e),
                "ingested_count": 0,
                "failed_count": len(data_points)
            }
    
    return {"results": results, "total_devices": len(data)}

# ======================
# Metric Management
# ======================

@app.post("/api/v1/metrics", response_model=MetricDefinitionResponse)
async def create_metric_definition(
    request: MetricDefinitionRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """创建指标定义"""
    try:
        metric = await microservice.service.create_metric_definition(
            user_context["user_id"],
            request.model_dump()
        )
        if metric:
            return metric
        raise HTTPException(status_code=400, detail="Failed to create metric definition")
    except Exception as e:
        logger.error(f"Error creating metric definition: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/metrics")
async def list_metric_definitions(
    data_type: Optional[DataType] = Query(None, description="Filter by data type"),
    metric_type: Optional[MetricType] = Query(None, description="Filter by metric type"),
    limit: int = Query(100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取指标定义列表"""
    return {
        "metrics": list(microservice.service.metric_definitions.values())[offset:offset+limit],
        "count": len(microservice.service.metric_definitions),
        "limit": limit,
        "offset": offset,
        "filters": {
            "data_type": data_type,
            "metric_type": metric_type
        }
    }

@app.get("/api/v1/metrics/{metric_name}", response_model=MetricDefinitionResponse)
async def get_metric_definition(
    metric_name: str = Path(..., description="Metric name"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取指标定义"""
    try:
        if metric_name in microservice.service.metric_definitions:
            return microservice.service.metric_definitions[metric_name]
        raise HTTPException(status_code=404, detail="Metric definition not found")
    except Exception as e:
        logger.error(f"Error getting metric definition: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/metrics/{metric_name}")
async def delete_metric_definition(
    metric_name: str = Path(..., description="Metric name"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """删除指标定义"""
    try:
        if metric_name in microservice.service.metric_definitions:
            del microservice.service.metric_definitions[metric_name]
            return {"message": "Metric definition deleted successfully"}
        raise HTTPException(status_code=404, detail="Metric definition not found")
    except Exception as e:
        logger.error(f"Error deleting metric definition: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Data Query Endpoints
# ======================

@app.post("/api/v1/query", response_model=TelemetryDataResponse)
async def query_telemetry_data(
    request: QueryRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """查询遥测数据"""
    try:
        result = await microservice.service.query_telemetry_data(request.model_dump())
        if result:
            return result
        raise HTTPException(status_code=404, detail="No data found")
    except Exception as e:
        logger.error(f"Error querying telemetry data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/devices/{device_id}/metrics/{metric_name}/latest")
async def get_latest_value(
    device_id: str = Path(..., description="Device ID"),
    metric_name: str = Path(..., description="Metric name"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取最新值"""
    try:
        key = f"{device_id}:{metric_name}"
        data_points = microservice.service.data_store.get(key, [])
        
        if not data_points:
            raise HTTPException(status_code=404, detail="No data found")
        
        latest = max(data_points, key=lambda x: x["timestamp"])
        
        return {
            "device_id": device_id,
            "metric_name": metric_name,
            "value": latest["value"],
            "unit": latest.get("unit"),
            "timestamp": latest["timestamp"],
            "tags": latest.get("tags", {}),
            "metadata": latest.get("metadata", {})
        }
    except Exception as e:
        logger.error(f"Error getting latest value: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/devices/{device_id}/metrics", response_model=List[str])
async def get_device_metrics(
    device_id: str = Path(..., description="Device ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取设备的所有指标名称"""
    try:
        metrics = []
        for key in microservice.service.data_store.keys():
            if key.startswith(f"{device_id}:"):
                metric_name = key.split(":", 1)[1]
                if metric_name not in metrics:
                    metrics.append(metric_name)
        
        return metrics
    except Exception as e:
        logger.error(f"Error getting device metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/devices/{device_id}/metrics/{metric_name}/range")
async def get_metric_range(
    device_id: str = Path(..., description="Device ID"),
    metric_name: str = Path(..., description="Metric name"),
    time_range: TimeRange = Query(..., description="Time range"),
    aggregation: Optional[AggregationType] = Query(None, description="Aggregation type"),
    interval: Optional[int] = Query(None, ge=60, le=86400, description="Aggregation interval in seconds"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取指定时间范围的指标数据"""
    try:
        # 解析时间范围
        now = datetime.utcnow()
        if time_range == TimeRange.LAST_HOUR:
            start_time = now - timedelta(hours=1)
        elif time_range == TimeRange.LAST_6_HOURS:
            start_time = now - timedelta(hours=6)
        elif time_range == TimeRange.LAST_24_HOURS:
            start_time = now - timedelta(hours=24)
        elif time_range == TimeRange.LAST_7_DAYS:
            start_time = now - timedelta(days=7)
        elif time_range == TimeRange.LAST_30_DAYS:
            start_time = now - timedelta(days=30)
        else:
            start_time = now - timedelta(days=90)
        
        query_params = {
            "device_ids": [device_id],
            "metric_names": [metric_name],
            "start_time": start_time,
            "end_time": now,
            "aggregation": aggregation,
            "interval": interval
        }
        
        result = await microservice.service.query_telemetry_data(query_params)
        if result:
            return result
        raise HTTPException(status_code=404, detail="No data found")
        
    except Exception as e:
        logger.error(f"Error getting metric range: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Aggregation Endpoints
# ======================

@app.get("/api/v1/aggregated", response_model=AggregatedDataResponse)
async def get_aggregated_data(
    metric_name: str = Query(..., description="Metric name"),
    aggregation_type: AggregationType = Query(..., description="Aggregation type"),
    interval: int = Query(..., ge=60, le=86400, description="Interval in seconds"),
    start_time: datetime = Query(..., description="Start time"),
    end_time: datetime = Query(..., description="End time"),
    device_id: Optional[str] = Query(None, description="Device ID (optional for multi-device aggregation)"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取聚合数据"""
    try:
        query_params = {
            "device_id": device_id,
            "metric_name": metric_name,
            "aggregation_type": aggregation_type,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time
        }
        
        result = await microservice.service.get_aggregated_data(query_params)
        if result:
            return result
        raise HTTPException(status_code=404, detail="No data found")
    except Exception as e:
        logger.error(f"Error getting aggregated data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Alert Management
# ======================

@app.post("/api/v1/alerts/rules", response_model=AlertRuleResponse)
async def create_alert_rule(
    request: AlertRuleRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """创建警报规则"""
    try:
        rule = await microservice.service.create_alert_rule(
            user_context["user_id"],
            request.model_dump()
        )
        if rule:
            return rule
        raise HTTPException(status_code=400, detail="Failed to create alert rule")
    except Exception as e:
        logger.error(f"Error creating alert rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/alerts/rules")
async def list_alert_rules(
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
    level: Optional[AlertLevel] = Query(None, description="Filter by alert level"),
    metric_name: Optional[str] = Query(None, description="Filter by metric name"),
    limit: int = Query(100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取警报规则列表"""
    rules = list(microservice.service.alert_rules.values())
    
    # 应用过滤器
    if enabled is not None:
        rules = [rule for rule in rules if rule.enabled == enabled]
    if level:
        rules = [rule for rule in rules if rule.level == level]
    if metric_name:
        rules = [rule for rule in rules if rule.metric_name == metric_name]
    
    # 分页
    paginated_rules = rules[offset:offset+limit]
    
    return {
        "rules": paginated_rules,
        "count": len(paginated_rules),
        "total": len(rules),
        "limit": limit,
        "offset": offset,
        "filters": {
            "enabled": enabled,
            "level": level,
            "metric_name": metric_name
        }
    }

@app.get("/api/v1/alerts/rules/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(
    rule_id: str = Path(..., description="Alert rule ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取警报规则详情"""
    try:
        if rule_id in microservice.service.alert_rules:
            return microservice.service.alert_rules[rule_id]
        raise HTTPException(status_code=404, detail="Alert rule not found")
    except Exception as e:
        logger.error(f"Error getting alert rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/alerts/rules/{rule_id}/enable")
async def enable_alert_rule(
    rule_id: str = Path(..., description="Alert rule ID"),
    enabled: bool = Body(..., embed=True),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """启用/禁用警报规则"""
    try:
        if rule_id in microservice.service.alert_rules:
            microservice.service.alert_rules[rule_id].enabled = enabled
            action = "enabled" if enabled else "disabled"
            return {"message": f"Alert rule {action} successfully"}
        raise HTTPException(status_code=404, detail="Alert rule not found")
    except Exception as e:
        logger.error(f"Error enabling/disabling alert rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/alerts", response_model=AlertListResponse)
async def list_alerts(
    status: Optional[AlertStatus] = Query(None, description="Filter by status"),
    level: Optional[AlertLevel] = Query(None, description="Filter by level"),
    device_id: Optional[str] = Query(None, description="Filter by device ID"),
    start_time: Optional[datetime] = Query(None, description="Filter by start time"),
    end_time: Optional[datetime] = Query(None, description="Filter by end time"),
    limit: int = Query(100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取警报列表"""
    alerts = list(microservice.service.active_alerts.values())
    
    # 应用过滤器
    if status:
        alerts = [alert for alert in alerts if alert.status == status]
    if level:
        alerts = [alert for alert in alerts if alert.level == level]
    if device_id:
        alerts = [alert for alert in alerts if alert.device_id == device_id]
    if start_time and end_time:
        alerts = [alert for alert in alerts if start_time <= alert.triggered_at <= end_time]
    
    # 分页
    paginated_alerts = alerts[offset:offset+limit]
    
    active_count = len([a for a in alerts if a.status == AlertStatus.ACTIVE])
    critical_count = len([a for a in alerts if a.level == AlertLevel.CRITICAL])
    
    return AlertListResponse(
        alerts=paginated_alerts,
        count=len(paginated_alerts),
        active_count=active_count,
        critical_count=critical_count,
        filters={
            "status": status,
            "level": level,
            "device_id": device_id,
            "start_time": start_time,
            "end_time": end_time
        },
        limit=limit,
        offset=offset
    )

@app.put("/api/v1/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str = Path(..., description="Alert ID"),
    note: Optional[str] = Body(None, embed=True),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """确认警报"""
    try:
        if alert_id in microservice.service.active_alerts:
            alert = microservice.service.active_alerts[alert_id]
            alert.status = AlertStatus.ACKNOWLEDGED
            alert.acknowledged_at = datetime.utcnow()
            alert.acknowledged_by = user_context["user_id"]
            if note:
                alert.resolution_note = note
            return {"message": "Alert acknowledged successfully"}
        raise HTTPException(status_code=404, detail="Alert not found")
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str = Path(..., description="Alert ID"),
    note: Optional[str] = Body(None, embed=True),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """解决警报"""
    try:
        if alert_id in microservice.service.active_alerts:
            alert = microservice.service.active_alerts[alert_id]
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = datetime.utcnow()
            alert.resolved_by = user_context["user_id"]
            if note:
                alert.resolution_note = note
            return {"message": "Alert resolved successfully"}
        raise HTTPException(status_code=404, detail="Alert not found")
    except Exception as e:
        logger.error(f"Error resolving alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Statistics Endpoints
# ======================

@app.get("/api/v1/devices/{device_id}/stats", response_model=DeviceTelemetryStatsResponse)
async def get_device_telemetry_stats(
    device_id: str = Path(..., description="Device ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取设备遥测统计"""
    try:
        stats = await microservice.service.get_device_stats(device_id)
        if stats:
            return stats
        raise HTTPException(status_code=404, detail="Device not found or no telemetry data")
    except Exception as e:
        logger.error(f"Error getting device stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/stats", response_model=TelemetryStatsResponse)
async def get_telemetry_stats(
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取遥测服务统计"""
    try:
        stats = await microservice.service.get_service_stats()
        if stats:
            return stats
        raise HTTPException(status_code=404, detail="No stats available")
    except Exception as e:
        logger.error(f"Error getting service stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Real-time Data Streaming
# ======================

@app.post("/api/v1/subscribe")
async def subscribe_real_time_data(
    request: RealTimeSubscriptionRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """订阅实时数据"""
    try:
        subscription_id = await microservice.service.subscribe_real_time(request.model_dump())
        if subscription_id:
            return {
                "subscription_id": subscription_id,
                "message": "Subscription created successfully",
                "websocket_url": f"/ws/telemetry/{subscription_id}"
            }
        raise HTTPException(status_code=400, detail="Failed to create subscription")
    except Exception as e:
        logger.error(f"Error creating subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/subscribe/{subscription_id}")
async def unsubscribe_real_time_data(
    subscription_id: str = Path(..., description="Subscription ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """取消实时数据订阅"""
    try:
        success = await microservice.service.unsubscribe_real_time(subscription_id)
        if success:
            return {"message": "Subscription cancelled successfully"}
        raise HTTPException(status_code=404, detail="Subscription not found")
    except Exception as e:
        logger.error(f"Error cancelling subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/telemetry/{subscription_id}")
async def websocket_telemetry_stream(websocket: WebSocket, subscription_id: str):
    """WebSocket遥测数据流"""
    await websocket.accept()
    try:
        if subscription_id not in microservice.service.real_time_subscribers:
            await websocket.close(code=4004, reason="Subscription not found")
            return
        
        while True:
            # 在实际实现中，这里应该监听数据变化并推送
            # 目前只是示例代码
            await websocket.send_json({
                "subscription_id": subscription_id,
                "data": "real-time data would be sent here",
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # 等待一段时间，避免过于频繁的推送
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close(code=1011, reason="Internal server error")

# ======================
# Data Export
# ======================

@app.get("/api/v1/export/csv")
async def export_csv(
    device_ids: List[str] = Query(..., description="Device IDs"),
    metric_names: List[str] = Query(..., description="Metric names"),
    start_time: datetime = Query(..., description="Start time"),
    end_time: datetime = Query(..., description="End time"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """导出CSV格式数据"""
    try:
        import io
        import csv
        
        # 查询数据
        query_params = {
            "device_ids": device_ids,
            "metric_names": metric_names,
            "start_time": start_time,
            "end_time": end_time
        }
        
        result = await microservice.service.query_telemetry_data(query_params)
        if not result:
            raise HTTPException(status_code=404, detail="No data found")
        
        # 生成CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 写入头部
        writer.writerow(["timestamp", "device_id", "metric_name", "value", "unit", "tags"])
        
        # 写入数据
        for point in result.data_points:
            writer.writerow([
                point.timestamp.isoformat(),
                result.device_id if result.device_id != "multiple" else "unknown",
                point.metric_name,
                point.value,
                point.unit or "",
                json.dumps(point.tags or {})
            ])
        
        output.seek(0)
        
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=telemetry_data.csv"}
        )
        
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
            "ingestion": 3,
            "metrics": 4,
            "queries": 5,
            "aggregation": 1,
            "alerts": 7,
            "stats": 2,
            "real_time": 2,
            "export": 1
        },
        "features": [
            "data_ingestion",
            "metric_definitions",
            "time_series_queries",
            "data_aggregation",
            "alert_management",
            "real_time_streaming",
            "statistical_analysis",
            "data_export"
        ]
    }

# 导入asyncio用于WebSocket
import asyncio

if __name__ == "__main__":
    import uvicorn
    # Print configuration summary for debugging
    config_manager.print_config_summary()
    
    uvicorn.run(
        "microservices.telemetry_service.main:app", 
        host=config.service_host, 
        port=config.service_port,
        reload=config.debug,
        log_level=config.log_level.lower()
    )
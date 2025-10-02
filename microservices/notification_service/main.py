"""
Notification Service API

通知服务的FastAPI应用入口
提供通知发送、模板管理、应用内通知等功能
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import ConsulRegistry and ConfigManager
from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from typing import Optional, List
import logging
import asyncio
from contextlib import asynccontextmanager

from .notification_service import NotificationService
from .models import (
    SendNotificationRequest, SendBatchRequest,
    CreateTemplateRequest, UpdateTemplateRequest,
    NotificationResponse, TemplateResponse, BatchResponse,
    NotificationTemplate, Notification, InAppNotification,
    NotificationStatsResponse, HealthResponse, ServiceInfo,
    NotificationType, NotificationStatus, TemplateStatus, NotificationPriority,
    RegisterPushSubscriptionRequest, PushSubscription, PushPlatform
)


# Initialize configuration
config_manager = ConfigManager("notification_service")
config = config_manager.get_service_config()

# Import logger after config
from core.logger import setup_service_logger

# Setup loggers (use actual service name)
app_logger = setup_service_logger("notification_service")
api_logger = setup_service_logger("notification_service", "API")
logger = app_logger  # for backward compatibility

# 全局服务实例
service: Optional[NotificationService] = None

# 后台任务
background_task = None


async def process_pending_notifications_task():
    """后台任务：处理待发送的通知"""
    global service
    while True:
        try:
            if service:
                count = await service.process_pending_notifications()
                if count > 0:
                    logger.info(f"Processed {count} pending notifications")
        except Exception as e:
            logger.error(f"Error in background task: {str(e)}")
        
        # 每30秒检查一次
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global service, background_task
    
    # 启动时初始化
    logger.info("Starting Notification Service...")
    service = NotificationService()
    
    # Register with Consul
    if config.consul_enabled:
        consul_registry = ConsulRegistry(
            service_name=config.service_name,
            service_port=config.service_port,
            consul_host=config.consul_host,
            consul_port=config.consul_port,
            service_host=config.service_host,
            tags=["microservice", "notification", "api"]
        )
        
        if consul_registry.register():
            consul_registry.start_maintenance()
            app.state.consul_registry = consul_registry
            logger.info(f"{config.service_name} registered with Consul")
        else:
            logger.warning("Failed to register with Consul, continuing without service discovery")
    
    # 启动后台任务
    background_task = asyncio.create_task(process_pending_notifications_task())
    
    yield
    
    # 关闭时清理
    logger.info("Shutting down Notification Service...")
    
    # Deregister from Consul
    if config.consul_enabled and hasattr(app.state, 'consul_registry'):
        app.state.consul_registry.stop_maintenance()
        app.state.consul_registry.deregister()
    
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass
    
    if service:
        await service.cleanup()


# 创建FastAPI应用
app = FastAPI(
    title="Notification Service",
    description="通知服务API - 支持邮件、应用内通知、模板管理等",
    version="1.0.0",
    lifespan=lifespan
)

# 配置CORS
# CORS handled by Gateway


# ====================
# 健康检查和服务信息
# ====================

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="healthy",
        service=config.service_name,
        port=config.service_port,
        version="1.0.0"
    )


@app.get("/info", response_model=ServiceInfo, tags=["System"])
async def service_info():
    """服务信息"""
    return ServiceInfo(
        service="notification-service",
        version="1.0.0",
        description="Notification management and delivery service",
        capabilities={
            "email": True,
            "sms": False,
            "in_app": True,
            "push": True,
            "webhook": True,
            "templates": True,
            "batch_sending": True
        },
        endpoints={
            "send_notification": "/api/v1/notifications/send",
            "send_batch": "/api/v1/notifications/batch",
            "templates": "/api/v1/notifications/templates",
            "in_app_notifications": "/api/v1/notifications/in-app"
        }
    )


# ====================
# 通知模板管理
# ====================

@app.post("/api/v1/notifications/templates", response_model=TemplateResponse, tags=["Templates"])
async def create_template(request: CreateTemplateRequest):
    """创建通知模板"""
    try:
        return await service.create_template(request)
    except Exception as e:
        logger.error(f"Failed to create template: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/notifications/templates/{template_id}", response_model=NotificationTemplate, tags=["Templates"])
async def get_template(template_id: str):
    """获取通知模板"""
    template = await service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@app.get("/api/v1/notifications/templates", response_model=List[NotificationTemplate], tags=["Templates"])
async def list_templates(
    type: Optional[NotificationType] = None,
    status: Optional[TemplateStatus] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """列出通知模板"""
    try:
        return await service.list_templates(type, status, limit, offset)
    except Exception as e:
        logger.error(f"Failed to list templates: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v1/notifications/templates/{template_id}", response_model=TemplateResponse, tags=["Templates"])
async def update_template(template_id: str, request: UpdateTemplateRequest):
    """更新通知模板"""
    try:
        return await service.update_template(template_id, request)
    except Exception as e:
        logger.error(f"Failed to update template: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ====================
# 发送通知
# ====================

@app.post("/api/v1/notifications/send", response_model=NotificationResponse, tags=["Notifications"])
async def send_notification(request: SendNotificationRequest):
    """发送单个通知"""
    try:
        return await service.send_notification(request)
    except Exception as e:
        logger.error(f"Failed to send notification: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/notifications/batch", response_model=BatchResponse, tags=["Notifications"])
async def send_batch(request: SendBatchRequest):
    """批量发送通知"""
    try:
        return await service.send_batch(request)
    except Exception as e:
        logger.error(f"Failed to send batch: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/notifications", response_model=List[Notification], tags=["Notifications"])
async def list_notifications(
    user_id: Optional[str] = None,
    type: Optional[NotificationType] = None,
    status: Optional[NotificationStatus] = None,
    priority: Optional[NotificationPriority] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """列出通知"""
    try:
        return await service.repository.list_notifications(
            user_id, type, status, priority, limit, offset
        )
    except Exception as e:
        logger.error(f"Failed to list notifications: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ====================
# 应用内通知
# ====================

@app.get("/api/v1/notifications/in-app/{user_id}", response_model=List[InAppNotification], tags=["In-App"])
async def list_user_notifications(
    user_id: str,
    is_read: Optional[bool] = None,
    is_archived: Optional[bool] = None,
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """列出用户的应用内通知"""
    try:
        return await service.list_user_notifications(
            user_id, is_read, is_archived, category, limit, offset
        )
    except Exception as e:
        logger.error(f"Failed to list user notifications: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/notifications/in-app/{notification_id}/read", tags=["In-App"])
async def mark_notification_read(notification_id: str, user_id: str):
    """标记通知为已读"""
    try:
        success = await service.mark_notification_read(notification_id, user_id)
        if success:
            return {"message": "Notification marked as read"}
        else:
            raise HTTPException(status_code=404, detail="Notification not found")
    except Exception as e:
        logger.error(f"Failed to mark notification as read: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/notifications/in-app/{notification_id}/archive", tags=["In-App"])
async def mark_notification_archived(notification_id: str, user_id: str):
    """标记通知为已归档"""
    try:
        success = await service.mark_notification_archived(notification_id, user_id)
        if success:
            return {"message": "Notification archived"}
        else:
            raise HTTPException(status_code=404, detail="Notification not found")
    except Exception as e:
        logger.error(f"Failed to archive notification: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/notifications/in-app/{user_id}/unread-count", tags=["In-App"])
async def get_unread_count(user_id: str):
    """获取未读通知数量"""
    try:
        count = await service.get_unread_count(user_id)
        return {"unread_count": count}
    except Exception as e:
        logger.error(f"Failed to get unread count: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ====================
# Push通知订阅
# ====================

@app.post("/api/v1/notifications/push/subscribe", response_model=PushSubscription, tags=["Push"])
async def register_push_subscription(request: RegisterPushSubscriptionRequest):
    """注册推送订阅"""
    try:
        return await service.register_push_subscription(request)
    except Exception as e:
        logger.error(f"Failed to register push subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/notifications/push/subscriptions/{user_id}", response_model=List[PushSubscription], tags=["Push"])
async def get_user_push_subscriptions(
    user_id: str,
    platform: Optional[PushPlatform] = None
):
    """获取用户的推送订阅"""
    try:
        return await service.get_user_push_subscriptions(user_id, platform)
    except Exception as e:
        logger.error(f"Failed to get push subscriptions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/notifications/push/unsubscribe", tags=["Push"])
async def unsubscribe_push(user_id: str, device_token: str):
    """取消推送订阅"""
    try:
        success = await service.unsubscribe_push(user_id, device_token)
        if success:
            return {"message": "Push subscription removed"}
        else:
            raise HTTPException(status_code=404, detail="Subscription not found")
    except Exception as e:
        logger.error(f"Failed to unsubscribe push: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ====================
# 统计和报告
# ====================

@app.get("/api/v1/notifications/stats", response_model=NotificationStatsResponse, tags=["Statistics"])
async def get_notification_stats(
    user_id: Optional[str] = None,
    period: str = Query("all_time", regex="^(today|week|month|year|all_time)$")
):
    """获取通知统计"""
    try:
        return await service.get_notification_stats(user_id, period)
    except Exception as e:
        logger.error(f"Failed to get notification stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ====================
# 测试端点（开发环境）
# ====================

@app.post("/api/v1/notifications/test/email", tags=["Test"])
async def test_email(to: str, subject: str = "Test Email"):
    """测试邮件发送"""
    try:
        request = SendNotificationRequest(
            type=NotificationType.EMAIL,
            recipient_email=to,
            subject=subject,
            content="This is a test email from Notification Service.",
            html_content="<h1>Test Email</h1><p>This is a test email from <b>Notification Service</b>.</p>",
            priority=NotificationPriority.HIGH
        )
        return await service.send_notification(request)
    except Exception as e:
        logger.error(f"Failed to send test email: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/notifications/test/in-app", tags=["Test"])
async def test_in_app_notification(user_id: str, title: str = "Test Notification"):
    """测试应用内通知"""
    try:
        request = SendNotificationRequest(
            type=NotificationType.IN_APP,
            recipient_id=user_id,
            subject=title,
            content="This is a test in-app notification.",
            priority=NotificationPriority.NORMAL
        )
        return await service.send_notification(request)
    except Exception as e:
        logger.error(f"Failed to send test in-app notification: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    
    # Print configuration summary for debugging
    config_manager.print_config_summary()
    
    uvicorn.run(
        app,
        host=config.service_host,
        port=config.service_port,
        log_level="info"
    )
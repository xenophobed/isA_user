"""
Event Service - Main Application

统一事件管理服务的主应用程序
"""

import os
import json
import asyncio
import uuid
import logging
import sys
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query, Body, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import nats
from nats.aio.client import Client as NATS
from nats.js import JetStreamContext
import uvicorn

# 添加父目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from .models import (
    Event, EventSource, EventCategory, EventStatus,
    EventCreateRequest, EventQueryRequest, EventResponse, EventListResponse,
    EventStatistics, EventReplayRequest, EventProcessingResult,
    RudderStackEvent, EventProcessor, EventSubscription,
    EventProjection
)
from .event_service import EventService
from .event_repository import EventRepository
from core.config_manager import ConfigManager
from core.consul_registry import ConsulRegistry
from core.logger import setup_service_logger


# ==================== 配置 ====================

# 初始化配置
config_manager = ConfigManager("event_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("event_service")
api_logger = setup_service_logger("event_service", "API")
logger = app_logger  # for backward compatibility


# ==================== 全局变量 ====================

event_service: Optional[EventService] = None
event_repository: Optional[EventRepository] = None
nats_client: Optional[NATS] = None
js: Optional[JetStreamContext] = None


# ==================== 生命周期管理 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global event_service, event_repository, nats_client, js
    
    try:
        # 初始化事件服务（EventService 会自己初始化 repository）
        print(f"[event-service] Initializing event service...")
        event_service = EventService()
        event_repository = event_service.repository
        await event_repository.initialize()
        
        # 连接NATS（可选）
        try:
            if config.nats_enabled and config.nats_url:
                print(f"[event-service] Connecting to NATS at {config.nats_url}...")
                nats_client = await nats.connect(
                    servers=[config.nats_url],
                    user=config.nats_username or "isa_user_service",
                    password=config.nats_password or "service123",
                    name="event-service"
                )
                js = nats_client.jetstream()
            else:
                print(f"[event-service] NATS disabled or not configured")
                nats_client = None
                js = None
                raise Exception("NATS not enabled")
            
            # 创建NATS流
            try:
                await js.add_stream(
                    name="EVENTS",
                    subjects=["events.>"],
                    retention="limits",
                    max_msgs=1000000,
                    max_age=30 * 24 * 60 * 60  # 30天
                )
            except Exception as e:
                print(f"Stream might already exist: {e}")
            
            # 订阅NATS事件
            await subscribe_to_nats_events()
            print(f"[event-service] Connected to NATS successfully")
        except Exception as e:
            print(f"[event-service] NATS connection failed (will work without NATS): {e}")
            nats_client = None
            js = None
        
        # 启动后台任务
        batch_size = int(config.get("batch_size", 100))
        asyncio.create_task(process_pending_events(batch_size))

        # 注册到Consul
        consul_registry = ConsulRegistry(
            service_name="event_service",
            service_port=config.service_port,
            consul_host=config.consul_host,
            consul_port=config.consul_port,
            service_host=config.service_host,
            tags=["microservice", "event", "api"]
        )

        if consul_registry.register():
            consul_registry.start_maintenance()
            app.state.consul_registry = consul_registry
            logger.info("Event service registered with Consul")
        else:
            logger.warning("Failed to register with Consul, continuing without service discovery")

        print(f"[event-service] Service started successfully on port {config.service_port}")

        yield

    finally:
        # 清理资源
        print(f"[event-service] Shutting down...")

        # 注销Consul
        if hasattr(app.state, 'consul_registry'):
            app.state.consul_registry.stop_maintenance()
            app.state.consul_registry.deregister()

        if nats_client:
            await nats_client.close()
        if event_repository:
            await event_repository.close()


# ==================== FastAPI应用 ====================

app = FastAPI(
    title="Event Service",
    description="统一事件管理服务",
    version="1.0.0",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 依赖注入 ====================

async def get_event_service() -> EventService:
    """获取事件服务实例"""
    if not event_service:
        raise HTTPException(status_code=503, detail="Event service not initialized")
    return event_service


async def get_nats() -> NATS:
    """获取NATS客户端"""
    if not nats_client:
        raise HTTPException(status_code=503, detail="NATS not connected")
    return nats_client


# ==================== API端点 ====================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": config.service_name,
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/events/create", response_model=EventResponse)
async def create_event(
    request: EventCreateRequest = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    service: EventService = Depends(get_event_service)
):
    """创建事件"""
    try:
        event = await service.create_event(request)
        
        # 异步发布到NATS
        if nats_client and js:
            background_tasks.add_task(
                publish_event_to_nats,
                event
            )
        
        return EventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            event_source=event.event_source,
            event_category=event.event_category,
            user_id=event.user_id,
            data=event.data,
            status=event.status,
            timestamp=event.timestamp,
            created_at=event.created_at
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/events/batch", response_model=List[EventResponse])
async def create_batch_events(
    requests: List[EventCreateRequest] = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    service: EventService = Depends(get_event_service)
):
    """批量创建事件"""
    try:
        events = []
        for request in requests:
            event = await service.create_event(request)
            events.append(event)
            
            # 异步发布到NATS
            if nats_client and js:
                background_tasks.add_task(
                    publish_event_to_nats,
                    event
                )
        
        return [
            EventResponse(
                event_id=e.event_id,
                event_type=e.event_type,
                event_source=e.event_source,
                event_category=e.event_category,
                user_id=e.user_id,
                data=e.data,
                status=e.status,
                timestamp=e.timestamp,
                created_at=e.created_at
            ) for e in events
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/{{event_id}}", response_model=EventResponse)
async def get_event(
    event_id: str,
    service: EventService = Depends(get_event_service)
):
    """获取单个事件"""
    try:
        event = await service.get_event(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        return EventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            event_source=event.event_source,
            event_category=event.event_category,
            user_id=event.user_id,
            data=event.data,
            status=event.status,
            timestamp=event.timestamp,
            created_at=event.created_at
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/events/query", response_model=EventListResponse)
async def query_events(
    query: EventQueryRequest = Body(...),
    service: EventService = Depends(get_event_service)
):
    """查询事件"""
    try:
        events = await service.query_events(query)
        total = await service.count_events(query)
        
        return EventListResponse(
            events=[
                EventResponse(
                    event_id=e.event_id,
                    event_type=e.event_type,
                    event_source=e.event_source,
                    event_category=e.event_category,
                    user_id=e.user_id,
                    data=e.data,
                    status=e.status,
                    timestamp=e.timestamp,
                    created_at=e.created_at
                ) for e in events
            ],
            total=total,
            limit=query.limit,
            offset=query.offset,
            has_more=(query.offset + query.limit) < total
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/stream/{{stream_id}}")
async def get_event_stream(
    stream_id: str,
    from_version: Optional[int] = Query(None),
    service: EventService = Depends(get_event_service)
):
    """获取事件流"""
    try:
        stream = await service.get_event_stream(stream_id, from_version)
        if not stream:
            raise HTTPException(status_code=404, detail="Stream not found")
        return stream
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/statistics", response_model=EventStatistics)
async def get_statistics(
    user_id: Optional[str] = Query(None),
    service: EventService = Depends(get_event_service)
):
    """获取事件统计"""
    try:
        stats = await service.get_statistics(user_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/events/replay")
async def replay_events(
    request: EventReplayRequest = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    service: EventService = Depends(get_event_service)
):
    """重放事件"""
    try:
        # 在后台执行重放
        background_tasks.add_task(
            service.replay_events,
            request
        )
        
        return {
            "status": "replay_started",
            "message": "Event replay has been initiated",
            "dry_run": request.dry_run
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/projections/{{entity_type}}/{{entity_id}}")
async def get_projection(
    entity_type: str,
    entity_id: str,
    service: EventService = Depends(get_event_service)
):
    """获取实体投影"""
    try:
        projection = await service.get_projection(entity_type, entity_id)
        if not projection:
            raise HTTPException(status_code=404, detail="Projection not found")
        return projection
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Webhook端点 ====================

@app.post("/webhooks/rudderstack")
async def rudderstack_webhook(
    request: Request,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    service: EventService = Depends(get_event_service)
):
    """RudderStack webhook端点"""
    try:
        # 验证webhook密钥（如果配置了）
        if config.RUDDERSTACK_WEBHOOK_SECRET:
            signature = request.headers.get("X-Signature")
            if not signature or signature != config.RUDDERSTACK_WEBHOOK_SECRET:
                raise HTTPException(status_code=401, detail="Invalid signature")
        
        # 解析事件数据
        body = await request.json()
        
        # 处理单个或批量事件
        if isinstance(body, list):
            for event_data in body:
                rudderstack_event = RudderStackEvent(**event_data)
                background_tasks.add_task(
                    service.create_event_from_rudderstack,
                    rudderstack_event
                )
        else:
            rudderstack_event = RudderStackEvent(**body)
            background_tasks.add_task(
                service.create_event_from_rudderstack,
                rudderstack_event
            )
        
        return {"status": "accepted", "message": "Events queued for processing"}
        
    except Exception as e:
        print(f"Error processing RudderStack webhook: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 订阅管理端点 ====================

@app.post("/api/events/subscriptions", response_model=EventSubscription)
async def create_subscription(
    subscription: EventSubscription = Body(...),
    service: EventService = Depends(get_event_service)
):
    """创建事件订阅"""
    try:
        result = await service.create_subscription(subscription)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/subscriptions", response_model=List[EventSubscription])
async def list_subscriptions(
    service: EventService = Depends(get_event_service)
):
    """列出所有订阅"""
    try:
        subscriptions = await service.list_subscriptions()
        return subscriptions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/events/subscriptions/{{subscription_id}}")
async def delete_subscription(
    subscription_id: str,
    service: EventService = Depends(get_event_service)
):
    """删除订阅"""
    try:
        await service.delete_subscription(subscription_id)
        return {"status": "deleted", "subscription_id": subscription_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 处理器管理端点 ====================

@app.post("/api/events/processors", response_model=EventProcessor)
async def register_processor(
    processor: EventProcessor = Body(...),
    service: EventService = Depends(get_event_service)
):
    """注册事件处理器"""
    try:
        result = await service.register_processor(processor)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/processors", response_model=List[EventProcessor])
async def list_processors(
    service: EventService = Depends(get_event_service)
):
    """列出所有处理器"""
    try:
        processors = await service.list_processors()
        return processors
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/events/processors/{{processor_id}}/toggle")
async def toggle_processor(
    processor_id: str,
    enabled: bool = Query(...),
    service: EventService = Depends(get_event_service)
):
    """启用/禁用处理器"""
    try:
        await service.toggle_processor(processor_id, enabled)
        return {
            "status": "updated",
            "processor_id": processor_id,
            "enabled": enabled
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== NATS集成 ====================

async def subscribe_to_nats_events():
    """订阅NATS事件"""
    if not nats_client or not js:
        return
    
    try:
        # 订阅所有后端事件
        async def backend_event_handler(msg):
            try:
                # 解析消息
                data = json.loads(msg.data.decode())
                
                # 创建事件
                if event_service:
                    await event_service.create_event_from_nats(data)
                
                # 确认消息
                await msg.ack()
            except Exception as e:
                print(f"Error processing NATS event: {e}")
                await msg.nak()
        
        # 创建持久订阅
        await js.subscribe(
            "events.backend.>",
            cb=backend_event_handler,
            durable="event-service",
            manual_ack=True
        )
        
        print(f"[{config.service_name}] Subscribed to NATS events")
        
    except Exception as e:
        print(f"Error subscribing to NATS: {e}")


async def publish_event_to_nats(event: Event):
    """发布事件到NATS"""
    if not nats_client or not js:
        return
    
    try:
        # 构建主题
        subject = f"events.{event.event_source.value}.{event.event_category.value}.{event.event_type}"
        
        # 发布消息
        await js.publish(
            subject,
            json.dumps(event.dict(), default=str).encode(),
            headers={
                "event_id": event.event_id,
                "event_type": event.event_type,
                "user_id": event.user_id or "",
                "timestamp": event.timestamp.isoformat()
            }
        )
    except Exception as e:
        print(f"Error publishing to NATS: {e}")


# ==================== 后台任务 ====================

async def process_pending_events(batch_size: int = 100):
    """处理待处理的事件"""
    processing_interval = int(config.get("processing_interval", 5))
    
    while True:
        try:
            if event_service:
                # 获取待处理事件（直接获取Event对象列表）
                events = await event_service.get_unprocessed_events(limit=batch_size)
                
                # 处理每个事件
                for event in events:
                    try:
                        await event_service.process_event(event)
                    except Exception as e:
                        print(f"Error processing event {event.event_id}: {e}")
            
            # 等待下一个处理周期
            await asyncio.sleep(processing_interval)
            
        except Exception as e:
            print(f"Error in event processing loop: {e}")
            await asyncio.sleep(processing_interval)


# ==================== 前端事件采集端点 ====================

from pydantic import BaseModel
from typing import Optional, List

class FrontendEvent(BaseModel):
    """前端事件模型"""
    event_type: str  # 'page_view', 'button_click', 'form_submit', etc.
    category: str = "user_interaction"  # 'user_interaction', 'business_action', 'system_event'
    page_url: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    data: Dict[str, Any] = {}
    metadata: Dict[str, str] = {}

class FrontendEventBatch(BaseModel):
    """批量前端事件"""
    events: List[FrontendEvent]
    client_info: Optional[Dict[str, Any]] = {}

@app.post("/api/frontend/events", response_model=Dict[str, Any])
async def collect_frontend_event(
    event: FrontendEvent,
    request: Request
):
    """采集单个前端事件"""
    try:
        # 添加客户端信息
        client_info = {
            "ip": request.client.host,
            "user_agent": request.headers.get("user-agent", ""),
            "referer": request.headers.get("referer", ""),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # 构建NATS事件
        if nats_client and js:
            # 构建主题：events.frontend.{category}.{event_type}
            subject = f"events.frontend.{event.category}.{event.event_type}"
            
            event_data = {
                "event_id": str(uuid.uuid4()),
                "event_type": event.event_type,
                "event_source": "frontend",
                "event_category": event.category,
                "user_id": event.user_id,
                "session_id": event.session_id,
                "page_url": event.page_url,
                "data": event.data,
                "metadata": {**event.metadata, **client_info},
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # 发布到NATS
            await js.publish(
                subject,
                json.dumps(event_data).encode(),
                headers={
                    "event_type": event.event_type,
                    "source": "frontend",
                    "user_id": event.user_id or "",
                }
            )
            
            return {
                "status": "accepted",
                "event_id": event_data["event_id"],
                "message": "Event published to stream"
            }
        else:
            return {
                "status": "error", 
                "message": "Event stream not available"
            }
            
    except Exception as e:
        logger.error(f"Error collecting frontend event: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/frontend/events/batch", response_model=Dict[str, Any])
async def collect_frontend_events_batch(
    batch: FrontendEventBatch,
    request: Request
):
    """批量采集前端事件 - 高性能处理"""
    try:
        if not nats_client or not js:
            raise HTTPException(status_code=503, detail="Event stream not available")
        
        # 添加客户端信息
        client_info = {
            "ip": request.client.host,
            "user_agent": request.headers.get("user-agent", ""),
            "referer": request.headers.get("referer", ""),
            "batch_timestamp": datetime.utcnow().isoformat()
        }
        
        processed_events = []
        
        # 批量处理事件
        for event in batch.events:
            event_data = {
                "event_id": str(uuid.uuid4()),
                "event_type": event.event_type,
                "event_source": "frontend",
                "event_category": event.category,
                "user_id": event.user_id,
                "session_id": event.session_id,
                "page_url": event.page_url,
                "data": event.data,
                "metadata": {**event.metadata, **client_info, **batch.client_info},
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # 构建主题
            subject = f"events.frontend.{event.category}.{event.event_type}"
            
            # 异步发布（提高性能）
            await js.publish(
                subject,
                json.dumps(event_data).encode(),
                headers={
                    "event_type": event.event_type,
                    "source": "frontend",
                    "user_id": event.user_id or "",
                    "batch": "true"
                }
            )
            
            processed_events.append(event_data["event_id"])
        
        return {
            "status": "accepted",
            "processed_count": len(processed_events),
            "event_ids": processed_events,
            "message": f"Batch of {len(processed_events)} events published to stream"
        }
        
    except Exception as e:
        logger.error(f"Error collecting frontend event batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/frontend/health")
async def frontend_health():
    """前端事件采集健康检查"""
    return {
        "status": "healthy",
        "service": "frontend-event-collection",
        "nats_connected": nats_client is not None,
        "timestamp": datetime.utcnow().isoformat()
    }


# ==================== 主入口 ====================

if __name__ == "__main__":
    uvicorn.run(
        "microservices.event_service.main:app",
        host=config.service_host,
        port=config.service_port,
        reload=config.debug
    )
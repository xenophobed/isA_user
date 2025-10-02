"""
Task Service - Main Application

任务管理微服务主应用，提供待办事项、任务调度、日历管理等功能
"""

from fastapi import FastAPI, HTTPException, Depends, Query, Path, Body, Header
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
    TaskCreateRequest, TaskUpdateRequest, TaskExecutionRequest,
    TaskResponse, TaskExecutionResponse, TaskTemplateResponse,
    TaskAnalyticsResponse, TaskListResponse,
    TaskStatus, TaskType, TaskPriority
)
from .task_service import TaskService
from .task_repository import TaskRepository

# 初始化配置
config_manager = ConfigManager("task_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("task_service")
api_logger = setup_service_logger("task_service", "API")
logger = app_logger  # for backward compatibility

# Service instance
class TaskMicroservice:
    def __init__(self):
        self.service = None
        self.repository = None
    
    async def initialize(self):
        self.repository = TaskRepository()
        self.service = TaskService()
        logger.info("Task service initialized")
    
    async def shutdown(self):
        logger.info("Task service shutting down")

# Global instance
microservice = TaskMicroservice()

# Lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Startup
    await microservice.initialize()
    
    # Consul注册
    consul_registry = ConsulRegistry(
        service_name="task_service",
        service_port=config.service_port,
        consul_host=config.consul_host,
        consul_port=config.consul_port,
        service_host=config.service_host,
        tags=["microservice", "task", "scheduler", "api", "v1"]
    )
    
    if consul_registry.register():
        consul_registry.start_maintenance()
        app.state.consul_registry = consul_registry
        logger.info("Successfully registered with Consul")
    else:
        logger.warning("Failed to register with Consul")
    
    yield
    
    # Shutdown
    if hasattr(app.state, 'consul_registry'):
        app.state.consul_registry.stop_maintenance()
        app.state.consul_registry.deregister()
        logger.info("Deregistered from Consul")
    
    await microservice.shutdown()

# Create FastAPI application
app = FastAPI(
    title="Task Service",
    description="用户任务管理微服务 - 待办事项、任务调度、日历管理",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
# CORS handled by Gateway

# ======================
# Health Check Endpoints
# ======================

@app.get("/health")
async def health_check():
    """基础健康检查"""
    return {
        "status": "healthy",
        "service": "task_service",
        "port": config.service_port,
        "version": "1.0.0"
    }

@app.get("/health/detailed")
async def detailed_health_check():
    """详细健康检查"""
    db_healthy = False
    try:
        # 检查数据库连接
        test_task = await microservice.repository.get_task_by_id("test_id")
        db_healthy = True
    except:
        pass
    
    return {
        "status": "healthy" if db_healthy else "degraded",
        "service": "task_service",
        "port": config.service_port,
        "version": "1.0.0",
        "components": {
            "database": "healthy" if db_healthy else "unhealthy",
            "service": "healthy"
        }
    }

# ======================
# Dependencies
# ======================

async def get_user_context(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key")
) -> Dict[str, Any]:
    """获取用户上下文信息"""
    logger.debug(f"Auth headers: authorization={authorization}, x_api_key={x_api_key}")
    
    if not authorization and not x_api_key:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Call auth service for verification
    auth_service_url = "http://localhost:8202"
    
    try:
        if authorization:
            # Verify JWT token
            token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
            
            response = requests.post(
                f"{auth_service_url}/api/v1/auth/verify-token",
                json={"token": token, "token_type": "jwt"}
            )
            
            if response.status_code != 200:
                logger.warning(f"Token verification failed: {response.status_code}")
                raise HTTPException(status_code=401, detail="Invalid token")
            
            result = response.json()
            if not result.get("valid", False):
                logger.warning("Token verification returned invalid")
                raise HTTPException(status_code=401, detail="Invalid token")

            # Auth service returns user_id at top level, not in user_info
            return {
                "user_id": result.get("user_id", "unknown"),
                "email": result.get("email"),
                "subscription_level": result.get("subscription_level", "free"),
                "organization_id": result.get("organization_id")
            }
            
        elif x_api_key:
            # Verify API key
            response = requests.post(
                f"{auth_service_url}/api/v1/auth/verify-api-key",
                json={"api_key": x_api_key}
            )
            
            if response.status_code != 200:
                logger.warning(f"API key verification failed: {response.status_code}")
                raise HTTPException(status_code=401, detail="Invalid API key")
            
            result = response.json()
            if not result.get("valid", False):
                logger.warning("API key verification returned invalid")
                raise HTTPException(status_code=401, detail="Invalid API key")
            
            user_info = result.get("user_info", {})
            return {
                "user_id": user_info.get("user_id", "unknown"),
                "email": user_info.get("email"),
                "subscription_level": user_info.get("subscription_level", "free"),
                "organization_id": user_info.get("organization_id")
            }
            
    except requests.RequestException as e:
        logger.error(f"Auth service request failed: {e}")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(status_code=500, detail="Authentication error")
    
    raise HTTPException(status_code=401, detail="Authentication required")

# ======================
# Task CRUD Endpoints
# ======================

@app.post("/api/v1/tasks", response_model=TaskResponse)
async def create_task(
    request: TaskCreateRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """创建新任务"""
    try:
        task = await microservice.service.create_task(
            user_context["user_id"],
            request
        )
        if task:
            return task
        raise HTTPException(status_code=400, detail="Failed to create task")
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str = Path(..., description="Task ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取任务详情"""
    try:
        task = await microservice.service.get_task(
            task_id,
            user_context["user_id"]
        )
        if task:
            return task
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        logger.error(f"Error getting task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str = Path(..., description="Task ID"),
    request: TaskUpdateRequest = Body(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """更新任务"""
    try:
        task = await microservice.service.update_task(
            task_id,
            user_context["user_id"],
            request
        )
        if task:
            return task
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        logger.error(f"Error updating task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/tasks/{task_id}")
async def delete_task(
    task_id: str = Path(..., description="Task ID"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """删除任务"""
    try:
        success = await microservice.service.delete_task(
            task_id,
            user_context["user_id"]
        )
        if success:
            return {"message": "Task deleted successfully"}
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        logger.error(f"Error deleting task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/tasks", response_model=TaskListResponse)
async def list_tasks(
    status: Optional[TaskStatus] = Query(None, description="Filter by status"),
    task_type: Optional[TaskType] = Query(None, description="Filter by type"),
    priority: Optional[TaskPriority] = Query(None, description="Filter by priority"),
    limit: int = Query(100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取用户任务列表"""
    try:
        task_list_response = await microservice.service.get_user_tasks(
            user_context["user_id"],
            status=status.value if status else None,
            task_type=task_type.value if task_type else None,
            limit=limit,
            offset=offset
        )
        
        return task_list_response
    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Task Execution Endpoints
# ======================

@app.post("/api/v1/tasks/{task_id}/execute", response_model=TaskExecutionResponse)
async def execute_task(
    task_id: str = Path(..., description="Task ID"),
    request: TaskExecutionRequest = Body(default=TaskExecutionRequest()),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """手动执行任务"""
    try:
        execution = await microservice.service.execute_task(
            task_id,
            user_context["user_id"],
            request
        )
        if execution:
            return execution
        raise HTTPException(status_code=400, detail="Failed to execute task")
    except Exception as e:
        logger.error(f"Error executing task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/tasks/{task_id}/executions", response_model=List[TaskExecutionResponse])
async def get_task_executions(
    task_id: str = Path(..., description="Task ID"),
    limit: int = Query(50, ge=1, le=200, description="Max executions to return"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取任务执行历史"""
    try:
        # 验证用户对任务的访问权限
        task = await microservice.repository.get_task_by_id(task_id, user_context["user_id"])
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        executions = await microservice.repository.get_task_executions(task_id, limit)
        return executions
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Task Templates Endpoints
# ======================

@app.get("/api/v1/templates", response_model=List[TaskTemplateResponse])
async def get_task_templates(
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取可用的任务模板"""
    try:
        templates = await microservice.service.get_task_templates(
            user_context["subscription_level"]
        )
        return templates
    except Exception as e:
        logger.error(f"Error getting task templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/tasks/from-template", response_model=TaskResponse)
async def create_task_from_template(
    template_id: str = Body(..., embed=True),
    customization: Dict[str, Any] = Body(default={}),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """从模板创建任务"""
    try:
        # 获取模板
        templates = await microservice.repository.get_task_templates(
            user_context["subscription_level"]
        )
        
        template = None
        for t in templates:
            if t.template_id == template_id:
                template = t
                break
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        # 创建任务
        task_data = {
            "name": customization.get("name", template.name),
            "description": customization.get("description", template.description),
            "task_type": template.task_type,
            "config": {**template.default_config, **customization.get("config", {})},
            "credits_per_run": template.credits_per_run,
            **customization
        }
        
        task = await microservice.service.create_task(
            user_context["user_id"],
            task_data
        )
        
        if task:
            return task
        raise HTTPException(status_code=400, detail="Failed to create task from template")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating task from template: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Analytics Endpoints
# ======================

@app.get("/api/v1/analytics", response_model=TaskAnalyticsResponse)
async def get_task_analytics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """获取任务分析数据"""
    try:
        analytics = await microservice.service.get_task_analytics(
            user_context["user_id"],
            days
        )
        if analytics:
            return analytics
        raise HTTPException(status_code=404, detail="No analytics data available")
    except Exception as e:
        logger.error(f"Error getting task analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Scheduler Endpoints
# ======================

@app.get("/api/v1/scheduler/pending", response_model=List[TaskResponse])
async def get_pending_tasks(
    limit: int = Query(50, ge=1, le=200, description="Max tasks to return"),
    x_internal_key: Optional[str] = None
):
    """获取待执行的任务（内部调度器使用）"""
    # 验证内部密钥
    if x_internal_key != "internal_scheduler_key":  # 实际应该从环境变量读取
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        tasks = await microservice.service.get_pending_tasks(limit)
        return tasks
    except Exception as e:
        logger.error(f"Error getting pending tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/scheduler/execute/{task_id}")
async def scheduler_execute_task(
    task_id: str = Path(..., description="Task ID"),
    x_internal_key: Optional[str] = None
):
    """调度器执行任务（内部使用）"""
    # 验证内部密钥
    if x_internal_key != "internal_scheduler_key":
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        # 获取任务信息
        task = await microservice.repository.get_task_by_id(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # 执行任务
        execution = await microservice.service.execute_task(
            task_id,
            task.user_id,
            {"trigger_type": "scheduler"}
        )
        
        if execution:
            return {"message": "Task executed", "execution_id": execution.execution_id}
        raise HTTPException(status_code=400, detail="Failed to execute task")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in scheduler execute: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ======================
# Service Statistics
# ======================

@app.get("/api/v1/service/stats")
async def get_service_stats():
    """获取服务统计信息"""
    return {
        "service": "task_service",
        "version": "1.0.0",
        "port": config.service_port,
        "endpoints": {
            "health": 2,
            "crud": 5,
            "execution": 2,
            "templates": 2,
            "analytics": 1,
            "scheduler": 2
        },
        "features": [
            "todo_management",
            "task_scheduling", 
            "calendar_events",
            "reminders",
            "analytics",
            "templates"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.service_host, port=config.service_port)
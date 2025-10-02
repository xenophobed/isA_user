"""
Authorization Microservice

A comprehensive authorization service that provides:
- User and organization resource access control
- Permission validation and management  
- Multi-level authorization (subscription, organization, admin)
- Resource-based access control (RBAC)

Port: 8203
"""

import asyncio
import logging
import signal
import sys
import os
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# Add parent directory to path for consul_registry
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager
from core.logger import setup_service_logger

# Import internal modules
from .authorization_service import AuthorizationService
from .models import (
    HealthResponse, ServiceInfo, ServiceStats,
    ResourceAccessRequest, ResourceAccessResponse,
    GrantPermissionRequest, RevokePermissionRequest,
    UserPermissionSummary, BulkPermissionRequest
)

# Initialize configuration
config_manager = ConfigManager("authorization_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("authorization_service")
api_logger = setup_service_logger("authorization_service", "API")
logger = app_logger  # for backward compatibility

# Global service instance
authorization_service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    global authorization_service
    
    # Startup
    logger.info("🚀 Authorization Service starting up...")
    try:
        authorization_service = AuthorizationService()
        
        # Initialize default permissions
        await authorization_service.initialize_default_permissions()
        
        # Register with Consul
        if config.consul_enabled:
            consul_registry = ConsulRegistry(
                service_name=config.service_name,
                service_port=config.service_port,
                consul_host=config.consul_host,
                consul_port=config.consul_port,
                service_host=config.service_host,
                tags=["microservice", "authorization", "api"]
            )
            
            if consul_registry.register():
                consul_registry.start_maintenance()
                app.state.consul_registry = consul_registry
                logger.info(f"{config.service_name} registered with Consul")
            else:
                logger.warning("Failed to register with Consul, continuing without service discovery")
        
        logger.info("✅ Authorization Service started successfully")
        yield
        
    except Exception as e:
        logger.error(f"❌ Failed to start Authorization Service: {e}")
        raise
    
    # Shutdown
    logger.info("🛑 Authorization Service shutting down...")
    
    # Deregister from Consul
    if config.consul_enabled and hasattr(app.state, 'consul_registry'):
        app.state.consul_registry.stop_maintenance()
        app.state.consul_registry.deregister()
    
    if authorization_service:
        await authorization_service.cleanup()
    logger.info("✅ Authorization Service shutdown completed")

# Create FastAPI application
app = FastAPI(
    title="Authorization Microservice",
    description="Resource authorization and permission management service",
    version="1.0.0",
    lifespan=lifespan
)

# CORS handled by Gateway

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}"}
    )

# ==========================================
# Health Check & Service Information
# ==========================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Basic health check"""
    return HealthResponse(
        status="healthy",
        service=config.service_name, 
        port=config.service_port,
        version="1.0.0"
    )

@app.get("/health/detailed")
async def detailed_health():
    """Detailed health check with service dependencies"""
    global authorization_service
    
    # Check database connectivity
    db_connected = False
    try:
        if authorization_service:
            db_connected = await authorization_service.repository.check_connection()
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
    
    return {
        "service": config.service_name,
        "status": "operational" if db_connected else "degraded",
        "port": config.service_port,
        "version": "1.0.0",
        "database_connected": db_connected,
        "timestamp": datetime.utcnow()
    }

@app.get("/api/v1/authorization/info", response_model=ServiceInfo)
async def service_info():
    """Service information and capabilities"""
    return ServiceInfo(
        service="authorization_service",
        version="1.0.0",
        description="Comprehensive resource authorization and permission management",
        capabilities={
            "resource_access_control": True,
            "multi_level_authorization": ["subscription", "organization", "admin"],
            "permission_management": True,
            "bulk_operations": True
        },
        endpoints={
            "check_access": "/api/v1/authorization/check-access",
            "grant_permission": "/api/v1/authorization/grant",
            "revoke_permission": "/api/v1/authorization/revoke", 
            "user_permissions": "/api/v1/authorization/user-permissions",
            "bulk_operations": "/api/v1/authorization/bulk"
        }
    )

@app.get("/api/v1/authorization/stats", response_model=ServiceStats)
async def service_stats():
    """Service statistics and metrics"""
    global authorization_service
    
    stats = {
        "total_permissions": 0,
        "active_users": 0,
        "resource_types": 0
    }
    
    if authorization_service:
        try:
            stats = await authorization_service.get_service_statistics()
        except Exception as e:
            logger.error(f"Failed to get service stats: {e}")
    
    return ServiceStats(
        service="authorization_service",
        version="1.0.0", 
        status="operational",
        uptime="running",
        endpoints_count=8,
        statistics=stats
    )

# ==========================================
# Core Authorization Endpoints
# ==========================================

@app.post("/api/v1/authorization/check-access", response_model=ResourceAccessResponse)
async def check_resource_access(request: ResourceAccessRequest):
    """Check if user has access to a specific resource"""
    global authorization_service
    
    if not authorization_service:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        logger.info(f"Checking access: user={request.user_id}, resource={request.resource_type}:{request.resource_name}")
        
        result = await authorization_service.check_resource_access(request)
        
        logger.info(f"Access check result: {result.has_access} - {result.reason}")
        return result
        
    except Exception as e:
        logger.error(f"Access check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Access check failed: {str(e)}")

@app.post("/api/v1/authorization/grant")
async def grant_permission(request: GrantPermissionRequest):
    """Grant resource access permission to user"""
    global authorization_service
    
    if not authorization_service:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        logger.info(f"Granting permission: user={request.user_id}, resource={request.resource_type}:{request.resource_name}")
        
        success = await authorization_service.grant_resource_permission(request)
        
        if success:
            return {"message": "Permission granted successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to grant permission")
            
    except Exception as e:
        logger.error(f"Grant permission failed: {e}")
        raise HTTPException(status_code=500, detail=f"Grant permission failed: {str(e)}")

@app.post("/api/v1/authorization/revoke")
async def revoke_permission(request: RevokePermissionRequest):
    """Revoke resource access permission from user"""
    global authorization_service
    
    if not authorization_service:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        logger.info(f"Revoking permission: user={request.user_id}, resource={request.resource_type}:{request.resource_name}")
        
        success = await authorization_service.revoke_resource_permission(request)
        
        if success:
            return {"message": "Permission revoked successfully"}
        else:
            raise HTTPException(status_code=404, detail="Permission not found")
            
    except Exception as e:
        logger.error(f"Revoke permission failed: {e}")
        raise HTTPException(status_code=500, detail=f"Revoke permission failed: {str(e)}")

# ==========================================
# Permission Management Endpoints
# ==========================================

@app.get("/api/v1/authorization/user-permissions/{user_id}", response_model=UserPermissionSummary)
async def get_user_permissions(user_id: str):
    """Get comprehensive permission summary for a user"""
    global authorization_service
    
    if not authorization_service:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        logger.info(f"Getting permissions for user: {user_id}")
        
        summary = await authorization_service.get_user_permission_summary(user_id)
        
        if not summary:
            raise HTTPException(status_code=404, detail=f"User not found: {user_id}")
        
        return summary
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user permissions failed: {e}")
        raise HTTPException(status_code=500, detail=f"Get user permissions failed: {str(e)}")

@app.get("/api/v1/authorization/user-resources/{user_id}")
async def list_user_accessible_resources(user_id: str, resource_type: str = None):
    """List all resources accessible to a user"""
    global authorization_service
    
    if not authorization_service:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        logger.info(f"Listing accessible resources for user: {user_id}")
        
        resources = await authorization_service.list_user_accessible_resources(user_id, resource_type)
        
        return {
            "user_id": user_id,
            "resource_type_filter": resource_type,
            "accessible_resources": resources,
            "total_count": len(resources)
        }
        
    except Exception as e:
        logger.error(f"List user resources failed: {e}")
        raise HTTPException(status_code=500, detail=f"List user resources failed: {str(e)}")

@app.post("/api/v1/authorization/bulk-grant")
async def bulk_grant_permissions(request: BulkPermissionRequest):
    """Grant multiple permissions in a single operation"""
    global authorization_service
    
    if not authorization_service:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        logger.info(f"Bulk granting permissions: {len(request.operations)} operations")
        
        results = await authorization_service.bulk_grant_permissions(request)
        
        return {
            "total_operations": len(request.operations),
            "successful": len([r for r in results if r.success]),
            "failed": len([r for r in results if not r.success]),
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Bulk grant permissions failed: {e}")
        raise HTTPException(status_code=500, detail=f"Bulk grant permissions failed: {str(e)}")

@app.post("/api/v1/authorization/bulk-revoke")
async def bulk_revoke_permissions(request: BulkPermissionRequest):
    """Revoke multiple permissions in a single operation"""
    global authorization_service
    
    if not authorization_service:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        logger.info(f"Bulk revoking permissions: {len(request.operations)} operations")
        
        results = await authorization_service.bulk_revoke_permissions(request)
        
        return {
            "total_operations": len(request.operations),
            "successful": len([r for r in results if r.success]),
            "failed": len([r for r in results if not r.success]),
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Bulk revoke permissions failed: {e}")
        raise HTTPException(status_code=500, detail=f"Bulk revoke permissions failed: {str(e)}")

# ==========================================
# Administrative Endpoints
# ==========================================

@app.post("/api/v1/authorization/cleanup-expired")
async def cleanup_expired_permissions():
    """Clean up expired permissions (admin operation)"""
    global authorization_service
    
    if not authorization_service:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        logger.info("Cleaning up expired permissions")
        
        cleaned_count = await authorization_service.cleanup_expired_permissions()
        
        return {
            "message": "Expired permissions cleaned up successfully",
            "cleaned_count": cleaned_count
        }
        
    except Exception as e:
        logger.error(f"Cleanup expired permissions failed: {e}")
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

# ==========================================
# Signal Handlers & Main
# ==========================================

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)

def main():
    """Main entry point"""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Print configuration summary for debugging
    config_manager.print_config_summary()
    
    logger.info(f"🚀 Starting Authorization Microservice on port {config.service_port}...")
    
    try:
        uvicorn.run(
            app,
            host=config.service_host,
            port=config.service_port,
            log_level="info",
            access_log=True
        )
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
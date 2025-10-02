"""
Account Microservice

Responsibilities:
- User account management (CRUD operations)
- User profile management  
- Account status management
- User preferences management
- Account search and listing

Note: Authentication is handled by auth_service, credits by credit_service
"""

from fastapi import FastAPI, HTTPException, Depends, status, Query
import uvicorn
import logging
from contextlib import asynccontextmanager
import sys
import os
from typing import Optional, List
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Import ConfigManager
from core.config_manager import ConfigManager
from core.logger import setup_service_logger

# Import local components
from .account_service import AccountService, AccountServiceError, AccountValidationError, AccountNotFoundError
from core.consul_registry import ConsulRegistry
from .models import (
    AccountEnsureRequest, AccountUpdateRequest, AccountPreferencesRequest,
    AccountStatusChangeRequest, AccountProfileResponse, AccountSummaryResponse,
    AccountSearchResponse, AccountStatsResponse, AccountServiceStatus,
    AccountListParams, AccountSearchParams
)
# Database connection now handled by repositories directly

# Initialize configuration
config_manager = ConfigManager("account_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("account_service")
api_logger = setup_service_logger("account_service", "API")
logger = app_logger  # for backward compatibility


class AccountMicroservice:
    """Account microservice core class"""
    
    def __init__(self):
        self.account_service = None
    
    async def initialize(self):
        """Initialize the microservice"""
        try:
            self.account_service = AccountService()
            logger.info("Account microservice initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize account microservice: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown the microservice"""
        try:
            logger.info("Account microservice shutdown completed")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


# Global microservice instance
account_microservice = AccountMicroservice()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Initialize microservice
    await account_microservice.initialize()
    
    # Register with Consul
    consul_registry = ConsulRegistry(
        service_name=config.service_name,
        service_port=config.service_port,
        consul_host=config.consul_host,
        consul_port=config.consul_port,
        service_host=config.service_host,
        tags=["microservice", "accounts", "api"]
    )
    
    if config.consul_enabled and consul_registry.register():
        consul_registry.start_maintenance()
        app.state.consul_registry = consul_registry
        logger.info(f"{config.service_name} registered with Consul")
    elif config.consul_enabled:
        logger.warning("Failed to register with Consul, continuing without service discovery")
    
    yield
    
    # Cleanup
    if config.consul_enabled and hasattr(app.state, 'consul_registry'):
        app.state.consul_registry.stop_maintenance()
        app.state.consul_registry.deregister()
    
    await account_microservice.shutdown()


# Create FastAPI application
app = FastAPI(
    title="Account Service",
    description="User account management microservice",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware is handled by the Gateway
# Remove local CORS to avoid duplicate headers


# Dependency injection
def get_account_service() -> AccountService:
    """Get account service instance"""
    if not account_microservice.account_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account service not initialized"
        )
    return account_microservice.account_service


# Health check endpoints
@app.get("/health")
async def health_check():
    """Service health check"""
    return {
        "status": "healthy",
        "service": config.service_name,
        "port": config.service_port,
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health/detailed")
async def detailed_health_check(
    account_service: AccountService = Depends(get_account_service)
):
    """Detailed health check with database connectivity"""
    try:
        health_data = await account_service.health_check()
        return AccountServiceStatus(
            database_connected=health_data["status"] == "healthy",
            timestamp=health_data["timestamp"]
        )
    except Exception as e:
        return AccountServiceStatus(
            database_connected=False,
            timestamp=health_data.get("timestamp") if 'health_data' in locals() else None
        )


# Core account management endpoints

@app.post("/api/v1/accounts/ensure", response_model=AccountProfileResponse)
async def ensure_account(
    request: AccountEnsureRequest,
    account_service: AccountService = Depends(get_account_service)
):
    """Ensure user account exists, create if needed"""
    try:
        account_response, was_created = await account_service.ensure_account(request)
        return account_response
    except AccountValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/accounts/profile/{user_id}", response_model=AccountProfileResponse)
async def get_account_profile(
    user_id: str,
    account_service: AccountService = Depends(get_account_service)
):
    """Get detailed account profile"""
    try:
        return await account_service.get_account_profile(user_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.put("/api/v1/accounts/profile/{user_id}", response_model=AccountProfileResponse)
async def update_account_profile(
    user_id: str,
    request: AccountUpdateRequest,
    account_service: AccountService = Depends(get_account_service)
):
    """Update account profile"""
    try:
        return await account_service.update_account_profile(user_id, request)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AccountValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.put("/api/v1/accounts/preferences/{user_id}")
async def update_account_preferences(
    user_id: str,
    request: AccountPreferencesRequest,
    account_service: AccountService = Depends(get_account_service)
):
    """Update account preferences"""
    try:
        success = await account_service.update_account_preferences(user_id, request)
        if success:
            return {"message": "Preferences updated successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update preferences"
            )
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.delete("/api/v1/accounts/profile/{user_id}")
async def delete_account(
    user_id: str,
    reason: Optional[str] = Query(None, description="Deletion reason"),
    account_service: AccountService = Depends(get_account_service)
):
    """Delete account (soft delete)"""
    try:
        success = await account_service.delete_account(user_id, reason)
        if success:
            return {"message": "Account deleted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete account"
            )
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Account query endpoints

@app.get("/api/v1/accounts", response_model=AccountSearchResponse)
async def list_accounts(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    subscription_status: Optional[str] = Query(None, description="Filter by subscription"),
    search: Optional[str] = Query(None, description="Search in name/email"),
    account_service: AccountService = Depends(get_account_service)
):
    """List accounts with filtering and pagination"""
    try:
        params = AccountListParams(
            page=page,
            page_size=page_size,
            is_active=is_active,
            subscription_status=subscription_status,
            search=search
        )
        return await account_service.list_accounts(params)
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/accounts/search", response_model=List[AccountSummaryResponse])
async def search_accounts(
    query: str = Query(..., description="Search query"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    include_inactive: bool = Query(False, description="Include inactive accounts"),
    account_service: AccountService = Depends(get_account_service)
):
    """Search accounts by query"""
    try:
        params = AccountSearchParams(
            query=query,
            limit=limit,
            include_inactive=include_inactive
        )
        return await account_service.search_accounts(params)
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/accounts/by-email/{email}", response_model=AccountProfileResponse)
async def get_account_by_email(
    email: str,
    account_service: AccountService = Depends(get_account_service)
):
    """Get account by email address"""
    try:
        account = await account_service.get_account_by_email(email)
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account not found with email: {email}"
            )
        return account
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Admin operations

@app.put("/api/v1/accounts/status/{user_id}")
async def change_account_status(
    user_id: str,
    request: AccountStatusChangeRequest,
    account_service: AccountService = Depends(get_account_service)
):
    """Change account status (admin operation)"""
    try:
        success = await account_service.change_account_status(user_id, request)
        if success:
            status_text = "activated" if request.is_active else "deactivated"
            return {"message": f"Account {status_text} successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to change account status"
            )
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Service statistics

@app.get("/api/v1/accounts/stats", response_model=AccountStatsResponse)
async def get_account_stats(
    account_service: AccountService = Depends(get_account_service)
):
    """Get account service statistics"""
    try:
        return await account_service.get_service_stats()
    except AccountServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Error handlers
@app.exception_handler(AccountValidationError)
async def validation_error_handler(request, exc):
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@app.exception_handler(AccountNotFoundError)
async def not_found_error_handler(request, exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@app.exception_handler(AccountServiceError)
async def service_error_handler(request, exc):
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


if __name__ == "__main__":
    # Print configuration summary for debugging
    config_manager.print_config_summary()
    
    uvicorn.run(
        "microservices.account_service.main:app",
        host=config.service_host,
        port=config.service_port,
        reload=config.debug,
        log_level=config.log_level.lower()
    )
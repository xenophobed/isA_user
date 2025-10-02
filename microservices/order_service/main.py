"""
Order Microservice

Responsibilities:
- Order management and lifecycle
- Transaction recording and tracking
- Payment service integration
- Wallet service integration
- Order analytics and reporting
"""

from fastapi import FastAPI, HTTPException, Depends, status, Query, Path, Body
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
from .order_service import OrderService, OrderServiceError, OrderValidationError, OrderNotFoundError
from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager
from core.logger import setup_service_logger
from .models import (
    OrderCreateRequest, OrderUpdateRequest, OrderCancelRequest,
    OrderCompleteRequest, OrderResponse, OrderListResponse,
    OrderSummaryResponse, OrderStatistics, OrderFilter,
    OrderSearchParams, Order, OrderStatus, OrderType, PaymentStatus,
    OrderServiceStatus
)

# Initialize configuration
config_manager = ConfigManager("order_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("order_service")
api_logger = setup_service_logger("order_service", "API")
logger = app_logger  # for backward compatibility


class OrderMicroservice:
    """Order microservice core class"""
    
    def __init__(self):
        self.order_service = None
    
    async def initialize(self):
        """Initialize the microservice"""
        try:
            self.order_service = OrderService()
            logger.info("Order microservice initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize order microservice: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown the microservice"""
        try:
            logger.info("Order microservice shutdown completed")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


# Global microservice instance
order_microservice = OrderMicroservice()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Initialize microservice
    await order_microservice.initialize()
    
    # Register with Consul
    if config.consul_enabled:
        consul_registry = ConsulRegistry(
            service_name=config.service_name,
            service_port=config.service_port,
            consul_host=config.consul_host,
            consul_port=config.consul_port,
            service_host=config.service_host,
            tags=["microservice", "order", "api"]
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
    
    await order_microservice.shutdown()


# Create FastAPI application
app = FastAPI(
    title="Order Service",
    description="Order management and transaction recording microservice",
    version="1.0.0",
    lifespan=lifespan
)

# CORS handled by Gateway


# Dependency injection
def get_order_service() -> OrderService:
    """Get order service instance"""
    if not order_microservice.order_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order service not initialized"
        )
    return order_microservice.order_service


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
    order_service: OrderService = Depends(get_order_service)
):
    """Detailed health check with database connectivity"""
    try:
        health_data = await order_service.health_check()
        return OrderServiceStatus(
            database_connected=health_data["status"] == "healthy",
            timestamp=health_data["timestamp"]
        )
    except Exception as e:
        return OrderServiceStatus(
            database_connected=False,
            timestamp=datetime.utcnow()
        )


# Core order management endpoints

@app.post("/api/v1/orders", response_model=OrderResponse)
async def create_order(
    request: OrderCreateRequest,
    order_service: OrderService = Depends(get_order_service)
):
    """Create a new order"""
    try:
        return await order_service.create_order(request)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/orders/{order_id}")
async def get_order(
    order_id: str = Path(..., description="Order ID"),
    order_service: OrderService = Depends(get_order_service)
):
    """Get order details"""
    try:
        order = await order_service.get_order(order_id)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return order
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.put("/api/v1/orders/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: str = Path(..., description="Order ID"),
    request: OrderUpdateRequest = Body(...),
    order_service: OrderService = Depends(get_order_service)
):
    """Update order"""
    try:
        return await order_service.update_order(order_id, request)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/v1/orders/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: str = Path(..., description="Order ID"),
    request: OrderCancelRequest = Body(...),
    order_service: OrderService = Depends(get_order_service)
):
    """Cancel an order"""
    try:
        return await order_service.cancel_order(order_id, request)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/v1/orders/{order_id}/complete", response_model=OrderResponse)
async def complete_order(
    order_id: str = Path(..., description="Order ID"),
    request: OrderCompleteRequest = Body(...),
    order_service: OrderService = Depends(get_order_service)
):
    """Complete an order"""
    try:
        return await order_service.complete_order(order_id, request)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Order query endpoints

@app.get("/api/v1/orders", response_model=OrderListResponse)
async def list_orders(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    order_type: Optional[OrderType] = Query(None, description="Filter by order type"),
    status: Optional[OrderStatus] = Query(None, description="Filter by status"),
    payment_status: Optional[PaymentStatus] = Query(None, description="Filter by payment status"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    order_service: OrderService = Depends(get_order_service)
):
    """List orders with filtering and pagination"""
    try:
        filter_params = OrderFilter(
            user_id=user_id,
            order_type=order_type,
            status=status,
            payment_status=payment_status,
            start_date=start_date,
            end_date=end_date,
            limit=page_size,
            offset=(page - 1) * page_size
        )
        return await order_service.list_orders(filter_params)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/users/{user_id}/orders")
async def get_user_orders(
    user_id: str = Path(..., description="User ID"),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    order_service: OrderService = Depends(get_order_service)
):
    """Get orders for a specific user"""
    try:
        orders = await order_service.get_user_orders(user_id, limit, offset)
        return {
            "orders": orders,
            "count": len(orders),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/orders/search")
async def search_orders(
    query: str = Query(..., description="Search query"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    include_cancelled: bool = Query(False, description="Include cancelled orders"),
    order_service: OrderService = Depends(get_order_service)
):
    """Search orders"""
    try:
        search_params = OrderSearchParams(
            query=query,
            user_id=user_id,
            limit=limit,
            include_cancelled=include_cancelled
        )
        orders = await order_service.search_orders(search_params)
        return {
            "orders": orders,
            "count": len(orders),
            "query": query
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Integration endpoints

@app.get("/api/v1/payments/{payment_intent_id}/orders")
async def get_orders_by_payment(
    payment_intent_id: str = Path(..., description="Payment intent ID"),
    order_service: OrderService = Depends(get_order_service)
):
    """Get orders associated with a payment intent"""
    try:
        # This would be implemented in the repository layer
        orders = await order_service.order_repo.get_orders_by_payment_intent(payment_intent_id)
        return {
            "orders": orders,
            "payment_intent_id": payment_intent_id,
            "count": len(orders)
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/subscriptions/{subscription_id}/orders")
async def get_orders_by_subscription(
    subscription_id: str = Path(..., description="Subscription ID"),
    order_service: OrderService = Depends(get_order_service)
):
    """Get orders associated with a subscription"""
    try:
        orders = await order_service.order_repo.get_orders_by_subscription(subscription_id)
        return {
            "orders": orders,
            "subscription_id": subscription_id,
            "count": len(orders)
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Statistics endpoints

@app.get("/api/v1/orders/statistics", response_model=OrderStatistics)
async def get_order_statistics(
    order_service: OrderService = Depends(get_order_service)
):
    """Get order service statistics"""
    try:
        return await order_service.get_order_statistics()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Service info endpoints

@app.get("/api/v1/order/info")
async def get_service_info():
    """Get order service information"""
    return {
        "service": "order_service",
        "version": "1.0.0",
        "port": 8210,
        "status": "operational",
        "capabilities": {
            "order_management": True,
            "payment_integration": True,
            "wallet_integration": True,
            "transaction_recording": True,
            "order_analytics": True
        },
        "integrations": {
            "payment_service": "http://localhost:8207",
            "wallet_service": "http://localhost:8209"
        }
    }


# Error handlers
@app.exception_handler(OrderValidationError)
async def validation_error_handler(request, exc):
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@app.exception_handler(OrderNotFoundError)
async def not_found_error_handler(request, exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@app.exception_handler(OrderServiceError)
async def service_error_handler(request, exc):
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


if __name__ == "__main__":
    # Print configuration summary for debugging
    config_manager.print_config_summary()
    
    uvicorn.run(
        "microservices.order_service.main:app",
        host=config.service_host,
        port=config.service_port,
        reload=config.debug,
        log_level=config.log_level.lower()
    )
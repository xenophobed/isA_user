"""
Payment Microservice API

提供支付、订阅、发票和退款管理的REST API服务
"""

from fastapi import FastAPI, HTTPException, Depends, Request, Header, Body
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List
import logging
import os
import sys
from datetime import datetime

# 添加父目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager
from core.logger import setup_service_logger  # 使用新的日志模块

from .payment_repository import PaymentRepository
from .payment_service import PaymentService
from .models import (
    SubscriptionPlan, Subscription, Payment, Invoice, Refund,
    PaymentMethodInfo, SubscriptionTier, PaymentStatus,
    BillingCycle, CreatePaymentIntentRequest,
    CreateSubscriptionRequest, UpdateSubscriptionRequest,
    CancelSubscriptionRequest, CreateRefundRequest,
    PaymentIntentResponse, SubscriptionResponse,
    PaymentHistoryResponse, InvoiceResponse,
    HealthResponse, ServiceInfo, ServiceStats
)
from .blockchain_integration import blockchain_router

# 初始化配置管理器
config_manager = ConfigManager("payment_service")
config = config_manager.get_service_config()

# 配置日志 (使用集成 Loki 的新日志系统)
app_logger = setup_service_logger("payment_service", level=config.log_level.upper())
api_logger = setup_service_logger("payment_service", "API", level=config.log_level.upper())
stripe_logger = setup_service_logger("payment_service", "Stripe", level=config.log_level.upper())

# 兼容旧代码
logger = app_logger

# 打印配置信息（开发环境）
if config.debug:
    config_manager.print_config_summary(show_secrets=False)

# 全局变量
payment_service: Optional[PaymentService] = None
SERVICE_PORT = config.service_port


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    global payment_service
    
    # 初始化数据访问层
    repository = PaymentRepository()
    
    # 初始化业务逻辑层
    # 获取 Stripe 配置
    stripe_key = config_manager.get("STRIPE_SECRET_KEY") or config_manager.get("PAYMENT_SERVICE_STRIPE_SECRET_KEY")
    
    payment_service = PaymentService(
        repository=repository,
        stripe_secret_key=stripe_key
    )
    
    # Register with Consul
    consul_registry = ConsulRegistry(
        service_name="payment",
        service_port=SERVICE_PORT,
        consul_host=config.consul_host,
        consul_port=config.consul_port,
        service_host=config.service_host,
        tags=["microservice", "payment", "api"]
    )
    
    if consul_registry.register():
        consul_registry.start_maintenance()
        app.state.consul_registry = consul_registry
        app_logger.info("Payment service registered with Consul")
    else:
        app_logger.warning("Failed to register with Consul, continuing without service discovery")

    app_logger.info(f"Payment Service started on port {SERVICE_PORT}")
    
    yield
    
    # Cleanup
    if hasattr(app.state, 'consul_registry'):
        app.state.consul_registry.stop_maintenance()
        app.state.consul_registry.deregister()

    app_logger.info("Payment Service shutting down...")


# 创建FastAPI应用
app = FastAPI(
    title="Payment Service",
    description="支付和订阅管理微服务",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# 配置CORS
# CORS handled by Gateway

# Include blockchain routes
app.include_router(blockchain_router, prefix="/api/v1/payments")

# ====================
# 健康检查和服务信息
# ====================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点"""
    return HealthResponse(
        status="healthy",
        service="payment_service",
        port=SERVICE_PORT,
        version="1.0.0"
    )


@app.get("/info", response_model=ServiceInfo)
async def service_info():
    """获取服务信息"""
    return ServiceInfo(
        service="payment_service",
        version="1.0.0",
        description="Payment and Subscription Management Service",
        capabilities={
            "stripe_integration": bool(config_manager.get("STRIPE_SECRET_KEY") or config_manager.get("PAYMENT_SERVICE_STRIPE_SECRET_KEY")),
            "subscription_management": True,
            "payment_processing": True,
            "invoice_generation": True,
            "refund_processing": True,
            "webhook_support": True,
            "blockchain_integration": True
        },
        endpoints={
            "health": "/health",
            "subscriptions": "/api/v1/subscriptions",
            "payments": "/api/v1/payments",
            "invoices": "/api/v1/invoices",
            "refunds": "/api/v1/refunds",
            "plans": "/api/v1/plans",
            "webhooks": "/api/v1/webhooks/stripe"
        }
    )


@app.get("/api/v1/stats", response_model=ServiceStats)
async def get_service_stats():
    """获取服务统计信息"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    revenue_stats = await payment_service.get_revenue_stats()
    subscription_stats = await payment_service.get_subscription_stats()
    
    return ServiceStats(
        total_payments=subscription_stats.get("total_payments", 0),
        active_subscriptions=subscription_stats.get("active_subscriptions", 0),
        revenue_today=revenue_stats.get("daily_revenue", 0),
        revenue_month=revenue_stats.get("monthly_revenue", 0),
        failed_payments_today=0,  # TODO: 实现失败支付统计
        refunds_today=0  # TODO: 实现退款统计
    )


# ====================
# 订阅计划管理
# ====================

@app.post("/api/v1/plans", response_model=SubscriptionPlan)
async def create_plan(
    plan_id: str = Body(...),
    name: str = Body(...),
    tier: SubscriptionTier = Body(...),
    price: float = Body(...),
    billing_cycle: BillingCycle = Body(...),
    features: Dict[str, Any] = Body(default={}),
    trial_days: int = Body(default=0),
    stripe_product_id: Optional[str] = Body(default=None),
    stripe_price_id: Optional[str] = Body(default=None)
):
    """创建订阅计划"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        api_logger.info(f"Creating subscription plan | plan_id={plan_id} | tier={tier.value}")
        plan = await payment_service.create_subscription_plan(
            plan_id=plan_id,
            name=name,
            tier=tier,
            price=price,
            billing_cycle=billing_cycle,
            features=features,
            trial_days=trial_days,
            stripe_product_id=stripe_product_id,
            stripe_price_id=stripe_price_id
        )
        api_logger.info(f"Subscription plan created successfully | plan_id={plan_id}")
        return plan
    except Exception as e:
        api_logger.error(f"Error creating plan | plan_id={plan_id} | error={str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/plans/{plan_id}", response_model=SubscriptionPlan)
async def get_plan(plan_id: str):
    """获取订阅计划"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    plan = await payment_service.get_subscription_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    return plan


@app.get("/api/v1/plans", response_model=List[SubscriptionPlan])
async def list_plans(
    tier: Optional[SubscriptionTier] = None,
    is_active: bool = True
):
    """列出订阅计划"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    plans = await payment_service.list_subscription_plans(tier, is_active)
    return plans


# ====================
# 订阅管理
# ====================

@app.post("/api/v1/subscriptions", response_model=SubscriptionResponse)
async def create_subscription(request: CreateSubscriptionRequest):
    """创建订阅"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        response = await payment_service.create_subscription(request)
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating subscription: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create subscription")


@app.get("/api/v1/subscriptions/user/{user_id}", response_model=SubscriptionResponse)
async def get_user_subscription(user_id: str):
    """获取用户当前订阅"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    response = await payment_service.get_user_subscription(user_id)
    if not response:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    return response


@app.put("/api/v1/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: str,
    request: UpdateSubscriptionRequest
):
    """更新订阅"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        response = await payment_service.update_subscription(subscription_id, request)
        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating subscription: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update subscription")


@app.post("/api/v1/subscriptions/{subscription_id}/cancel", response_model=Subscription)
async def cancel_subscription(
    subscription_id: str,
    request: CancelSubscriptionRequest
):
    """取消订阅"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        subscription = await payment_service.cancel_subscription(subscription_id, request)
        return subscription
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error canceling subscription: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to cancel subscription")


# ====================
# 支付处理
# ====================

@app.post("/api/v1/payments/intent", response_model=PaymentIntentResponse)
async def create_payment_intent(request: CreatePaymentIntentRequest):
    """创建支付意图"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        response = await payment_service.create_payment_intent(request)
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating payment intent: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create payment intent")


@app.post("/api/v1/payments/{payment_id}/confirm", response_model=Payment)
async def confirm_payment(
    payment_id: str,
    processor_response: Optional[Dict[str, Any]] = Body(default=None)
):
    """确认支付"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        payment = await payment_service.confirm_payment(payment_id, processor_response)
        return payment
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error confirming payment: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to confirm payment")


@app.post("/api/v1/payments/{payment_id}/fail", response_model=Payment)
async def fail_payment(
    payment_id: str,
    failure_reason: str = Body(...),
    failure_code: Optional[str] = Body(default=None)
):
    """标记支付失败"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        payment = await payment_service.fail_payment(payment_id, failure_reason, failure_code)
        return payment
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error failing payment: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to mark payment as failed")


@app.get("/api/v1/payments/user/{user_id}", response_model=PaymentHistoryResponse)
async def get_payment_history(
    user_id: str,
    status: Optional[PaymentStatus] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 100
):
    """获取用户支付历史"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    response = await payment_service.get_payment_history(
        user_id, status, start_date, end_date, limit
    )
    return response


# ====================
# 发票管理
# ====================

@app.post("/api/v1/invoices", response_model=Invoice)
async def create_invoice(
    user_id: str = Body(...),
    subscription_id: Optional[str] = Body(default=None),
    amount_due: float = Body(...),
    due_date: Optional[datetime] = Body(default=None),
    line_items: List[Dict[str, Any]] = Body(...)
):
    """创建发票"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        invoice = await payment_service.create_invoice(
            user_id, subscription_id, amount_due, due_date, line_items
        )
        return invoice
    except Exception as e:
        logger.error(f"Error creating invoice: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create invoice")


@app.get("/api/v1/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(invoice_id: str):
    """获取发票"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    response = await payment_service.get_invoice(invoice_id)
    if not response:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    return response


@app.post("/api/v1/invoices/{invoice_id}/pay", response_model=Invoice)
async def pay_invoice(
    invoice_id: str,
    payment_method_id: str = Body(...)
):
    """支付发票"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        invoice = await payment_service.pay_invoice(invoice_id, payment_method_id)
        return invoice
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error paying invoice: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to pay invoice")


# ====================
# 退款处理
# ====================

@app.post("/api/v1/refunds", response_model=Refund)
async def create_refund(request: CreateRefundRequest):
    """创建退款"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        refund = await payment_service.create_refund(request)
        return refund
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating refund: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create refund")


@app.post("/api/v1/refunds/{refund_id}/process", response_model=Refund)
async def process_refund(
    refund_id: str,
    approved_by: Optional[str] = Body(default=None)
):
    """处理退款"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        refund = await payment_service.process_refund(refund_id, approved_by)
        return refund
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing refund: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process refund")


# ====================
# Webhook处理
# ====================

@app.post("/api/v1/webhooks/stripe")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature")
):
    """处理Stripe webhook事件"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")
    
    try:
        payload = await request.body()
        result = await payment_service.handle_stripe_webhook(payload, stripe_signature)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error handling webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to handle webhook")


# ====================
# 使用量记录
# ====================

@app.post("/api/v1/usage")
async def record_usage(
    user_id: str = Body(...),
    subscription_id: str = Body(...),
    metric_name: str = Body(...),
    quantity: int = Body(...),
    metadata: Optional[Dict[str, Any]] = Body(default=None)
):
    """记录使用量"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        usage_record = await payment_service.record_usage(
            user_id, subscription_id, metric_name, quantity, metadata
        )
        return {"success": True, "usage_record": usage_record}
    except Exception as e:
        logger.error(f"Error recording usage: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to record usage")


# ====================
# 统计和报告
# ====================

@app.get("/api/v1/stats/revenue")
async def get_revenue_stats(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
):
    """获取收入统计"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    stats = await payment_service.get_revenue_stats(start_date, end_date)
    return stats


@app.get("/api/v1/stats/subscriptions")
async def get_subscription_stats():
    """获取订阅统计"""
    if not payment_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    stats = await payment_service.get_subscription_stats()
    return stats


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=SERVICE_PORT,
        log_level="info"
    )
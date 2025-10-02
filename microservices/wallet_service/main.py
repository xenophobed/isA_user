"""
Wallet Microservice

Responsibilities:
- Digital wallet management (CRUD operations)
- Transaction management (deposit, withdraw, consume, transfer)
- Credit/token balance management
- Transaction history and analytics
"""

from fastapi import FastAPI, HTTPException, Depends, status, Query, Path, Body
import uvicorn
import logging
from contextlib import asynccontextmanager
import sys
import os
from typing import Optional, List
from datetime import datetime
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Import local components
from .wallet_service import WalletService
from core.consul_registry import ConsulRegistry
from core.config_manager import ConfigManager
from core.logger import setup_service_logger
from .models import (
    WalletCreate, WalletUpdate, WalletBalance, WalletResponse,
    DepositRequest, WithdrawRequest, ConsumeRequest, TransferRequest,
    RefundRequest, TransactionFilter, WalletTransaction,
    TransactionType, WalletType, WalletStatistics
)

# Initialize configuration
config_manager = ConfigManager("wallet_service")
config = config_manager.get_service_config()

# Setup loggers (use actual service name)
app_logger = setup_service_logger("wallet_service")
api_logger = setup_service_logger("wallet_service", "API")
logger = app_logger  # for backward compatibility


class WalletMicroservice:
    """Wallet microservice core class"""
    
    def __init__(self):
        self.wallet_service = None
    
    async def initialize(self):
        """Initialize the microservice"""
        try:
            self.wallet_service = WalletService()
            logger.info("Wallet microservice initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize wallet microservice: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown the microservice"""
        try:
            logger.info("Wallet microservice shutdown completed")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


# Global microservice instance
wallet_microservice = WalletMicroservice()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Initialize microservice
    await wallet_microservice.initialize()
    
    # Register with Consul
    if config.consul_enabled:
        consul_registry = ConsulRegistry(
            service_name=config.service_name,
            service_port=config.service_port,
            consul_host=config.consul_host,
            consul_port=config.consul_port,
            service_host=config.service_host,
        tags=["microservice", "wallet", "api"]
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
    
    await wallet_microservice.shutdown()


# Create FastAPI application
app = FastAPI(
    title="Wallet Service",
    description="Digital wallet management microservice",
    version="1.0.0",
    lifespan=lifespan
)

# CORS handled by Gateway


# Dependency injection
def get_wallet_service() -> WalletService:
    """Get wallet service instance"""
    if not wallet_microservice.wallet_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Wallet service not initialized"
        )
    return wallet_microservice.wallet_service


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


# Core wallet management endpoints

@app.post("/api/v1/wallets", response_model=WalletResponse)
async def create_wallet(
    wallet_data: WalletCreate,
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Create a new wallet for user"""
    try:
        result = await wallet_service.create_wallet(wallet_data)
        if not result.success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/wallets/{wallet_id}")
async def get_wallet(
    wallet_id: str = Path(..., description="Wallet ID"),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Get wallet details"""
    try:
        wallet = await wallet_service.get_wallet(wallet_id)
        if not wallet:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")
        return wallet
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/users/{user_id}/wallets")
async def get_user_wallets(
    user_id: str = Path(..., description="User ID"),
    wallet_type: Optional[WalletType] = Query(None, description="Filter by wallet type"),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Get all wallets for a user"""
    try:
        wallets = await wallet_service.get_user_wallets(user_id)
        
        # Filter by type if specified
        if wallet_type:
            wallets = [w for w in wallets if w.wallet_type == wallet_type]
            
        return {"wallets": wallets, "count": len(wallets)}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/wallets/{wallet_id}/balance", response_model=WalletResponse)
async def get_balance(
    wallet_id: str = Path(..., description="Wallet ID"),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Get wallet balance"""
    try:
        result = await wallet_service.get_balance(wallet_id)
        if not result.success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Transaction endpoints

@app.post("/api/v1/wallets/{wallet_id}/deposit", response_model=WalletResponse)
async def deposit(
    wallet_id: str = Path(..., description="Wallet ID"),
    request: DepositRequest = Body(...),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Deposit funds to wallet"""
    try:
        result = await wallet_service.deposit(wallet_id, request)
        if not result.success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/v1/wallets/{wallet_id}/withdraw", response_model=WalletResponse)
async def withdraw(
    wallet_id: str = Path(..., description="Wallet ID"),
    request: WithdrawRequest = Body(...),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Withdraw funds from wallet"""
    try:
        result = await wallet_service.withdraw(wallet_id, request)
        if not result.success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/v1/wallets/{wallet_id}/consume", response_model=WalletResponse)
async def consume(
    wallet_id: str = Path(..., description="Wallet ID"),
    request: ConsumeRequest = Body(...),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Consume credits/tokens from wallet"""
    try:
        result = await wallet_service.consume(wallet_id, request)
        if not result.success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Backward compatibility endpoint for credit consumption
@app.post("/api/v1/users/{user_id}/credits/consume", response_model=WalletResponse)
async def consume_user_credits(
    user_id: str = Path(..., description="User ID"),
    request: ConsumeRequest = Body(...),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Consume credits from user's primary wallet (backward compatibility)"""
    try:
        result = await wallet_service.consume_by_user(user_id, request)
        if not result.success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/v1/wallets/{wallet_id}/transfer", response_model=WalletResponse)
async def transfer(
    wallet_id: str = Path(..., description="Source wallet ID"),
    request: TransferRequest = Body(...),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Transfer funds between wallets"""
    try:
        result = await wallet_service.transfer(wallet_id, request)
        if not result.success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/v1/transactions/{transaction_id}/refund", response_model=WalletResponse)
async def refund_transaction(
    transaction_id: str = Path(..., description="Original transaction ID"),
    request: RefundRequest = Body(...),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Refund a previous transaction"""
    try:
        result = await wallet_service.refund(transaction_id, request)
        if not result.success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Transaction history endpoints

@app.get("/api/v1/wallets/{wallet_id}/transactions")
async def get_wallet_transactions(
    wallet_id: str = Path(..., description="Wallet ID"),
    transaction_type: Optional[TransactionType] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Get wallet transaction history"""
    try:
        filter_params = TransactionFilter(
            wallet_id=wallet_id,
            transaction_type=transaction_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )
        
        transactions = await wallet_service.get_transactions(filter_params)
        return {
            "transactions": transactions,
            "count": len(transactions),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/users/{user_id}/transactions")
async def get_user_transactions(
    user_id: str = Path(..., description="User ID"),
    transaction_type: Optional[TransactionType] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Get user transaction history across all wallets"""
    try:
        transactions = await wallet_service.get_user_transactions(
            user_id=user_id,
            transaction_type=transaction_type,
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date
        )
        
        return {
            "transactions": transactions,
            "count": len(transactions),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Statistics endpoints

@app.get("/api/v1/wallets/{wallet_id}/statistics")
async def get_wallet_statistics(
    wallet_id: str = Path(..., description="Wallet ID"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Get wallet statistics"""
    try:
        stats = await wallet_service.get_statistics(wallet_id, start_date, end_date)
        if not stats:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")
        return stats
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/users/{user_id}/statistics")
async def get_user_statistics(
    user_id: str = Path(..., description="User ID"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Get aggregated statistics for all user wallets"""
    try:
        stats = await wallet_service.get_user_statistics(user_id, start_date, end_date)
        return stats
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Backward compatibility for credit balance
@app.get("/api/v1/users/{user_id}/credits/balance")
async def get_user_credit_balance(
    user_id: str = Path(..., description="User ID"),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Get user's credit balance (backward compatibility)"""
    try:
        wallets = await wallet_service.get_user_wallets(user_id)
        
        # Get primary fiat wallet
        fiat_wallets = [w for w in wallets if w.wallet_type == WalletType.FIAT]
        if not fiat_wallets:
            # Create default wallet if doesn't exist
            create_result = await wallet_service.create_wallet(
                WalletCreate(
                    user_id=user_id,
                    wallet_type=WalletType.FIAT,
                    initial_balance=Decimal(0),
                    currency="CREDIT"
                )
            )
            if create_result.success:
                return {
                    "success": True,
                    "balance": float(create_result.balance or 0),
                    "currency": "CREDIT"
                }
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create wallet")
        
        return {
            "success": True,
            "balance": float(fiat_wallets[0].balance),
            "currency": fiat_wallets[0].currency,
            "wallet_id": fiat_wallets[0].wallet_id
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Service statistics
@app.get("/api/v1/wallet/stats")
async def get_wallet_service_stats(
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """Get wallet service statistics"""
    try:
        # Return basic service info
        return {
            "service": "wallet_service",
            "version": "1.0.0",
            "status": "operational",
            "capabilities": {
                "wallet_management": True,
                "transaction_management": True,
                "blockchain_ready": True
            }
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


if __name__ == "__main__":
    # Print configuration summary for debugging
    config_manager.print_config_summary()
    
    uvicorn.run(
        "microservices.wallet_service.main:app",
        host=config.service_host,
        port=config.service_port,
        reload=config.debug,
        log_level=config.log_level.lower()
    )
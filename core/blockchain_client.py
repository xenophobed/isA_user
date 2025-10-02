"""
Blockchain Client for Microservices

This client allows microservices to interact with blockchain functionality
through the API Gateway, without needing direct blockchain integration.
"""

import httpx
from typing import Optional, Dict, Any
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

class BlockchainClient:
    """Client for interacting with blockchain through the Gateway"""
    
    def __init__(
        self,
        gateway_url: str = "http://localhost:8000",
        auth_token: Optional[str] = None,
        timeout: float = 30.0
    ):
        """
        Initialize blockchain client
        
        Args:
            gateway_url: URL of the API Gateway
            auth_token: Authentication token for Gateway
            timeout: Request timeout in seconds
        """
        self.gateway_url = gateway_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout
        self.base_url = f"{self.gateway_url}/api/v1/blockchain"
        
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication"""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "python-httpx/blockchain-client",  # Identify as internal service
            "X-Service-Name": "payment-service"  # Service identification for Consul
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers
    
    async def get_status(self) -> Dict[str, Any]:
        """Get blockchain connection status"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/status",
                headers=self._get_headers()
            )
            response.raise_for_status()
            return response.json()
    
    async def get_balance(self, address: str) -> Dict[str, str]:
        """
        Get balance for a blockchain address
        
        Args:
            address: Blockchain address
            
        Returns:
            Dictionary with balance information
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/balance/{address}",
                headers=self._get_headers()
            )
            response.raise_for_status()
            return response.json()
    
    async def send_transaction(
        self,
        to: str,
        value: str,
        data: str = "",
        gas_limit: Optional[int] = None,
        gas_price: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Send a blockchain transaction
        
        Args:
            to: Recipient address
            value: Transaction value (in wei)
            data: Transaction data (optional)
            gas_limit: Gas limit (optional)
            gas_price: Gas price (optional)
            
        Returns:
            Dictionary with transaction hash and status
        """
        payload = {
            "to": to,
            "value": value,
            "data": data
        }
        
        if gas_limit:
            payload["gasLimit"] = gas_limit
        if gas_price:
            payload["gasPrice"] = gas_price
            
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/transaction",
                json=payload,
                headers=self._get_headers()
            )
            response.raise_for_status()
            return response.json()
    
    async def get_transaction(self, tx_hash: str) -> Dict[str, Any]:
        """
        Get transaction details by hash
        
        Args:
            tx_hash: Transaction hash
            
        Returns:
            Transaction details
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/transaction/{tx_hash}",
                headers=self._get_headers()
            )
            response.raise_for_status()
            return response.json()
    
    async def get_block(self, block_number: str) -> Dict[str, Any]:
        """
        Get block information
        
        Args:
            block_number: Block number or 'latest'
            
        Returns:
            Block information
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/block/{block_number}",
                headers=self._get_headers()
            )
            response.raise_for_status()
            return response.json()
    
    # Service-specific blockchain operations
    
    async def charge_for_service(
        self,
        user_address: str,
        amount: str,
        service_id: str
    ) -> Dict[str, str]:
        """
        Charge user for service usage
        
        Args:
            user_address: User's blockchain address
            amount: Amount to charge (in wei)
            service_id: ID of the service
            
        Returns:
            Transaction result
        """
        data = f"charge:service:{service_id}"
        return await self.send_transaction(
            to=user_address,
            value=amount,
            data=data
        )
    
    async def reward_user(
        self,
        user_address: str,
        amount: str,
        reason: str
    ) -> Dict[str, str]:
        """
        Send reward tokens to user
        
        Args:
            user_address: User's blockchain address
            amount: Reward amount (in wei)
            reason: Reason for reward
            
        Returns:
            Transaction result
        """
        data = f"reward:{reason}"
        return await self.send_transaction(
            to=user_address,
            value=amount,
            data=data
        )
    
    async def verify_payment(
        self,
        tx_hash: str,
        expected_amount: str
    ) -> bool:
        """
        Verify a payment transaction
        
        Args:
            tx_hash: Transaction hash to verify
            expected_amount: Expected payment amount
            
        Returns:
            True if payment is valid and confirmed
        """
        try:
            tx = await self.get_transaction(tx_hash)
            
            # Check transaction status
            if tx.get("status") != "confirmed":
                return False
            
            # Check amount
            if tx.get("value") != expected_amount:
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to verify payment {tx_hash}: {e}")
            return False
    
    async def check_service_access(
        self,
        user_address: str,
        service_id: str
    ) -> bool:
        """
        Check if user has access to a service
        
        Args:
            user_address: User's blockchain address
            service_id: Service ID to check
            
        Returns:
            True if user has access
        """
        # This would typically check NFT ownership or subscription status
        # For now, we check if user has sufficient balance
        try:
            balance_info = await self.get_balance(user_address)
            balance = Decimal(balance_info.get("balance", "0"))
            
            # Define minimum balance for service access (example: 1 token = 10^18 wei)
            min_balance = Decimal("1000000000000000000")  # 1 token
            
            return balance >= min_balance
            
        except Exception as e:
            logger.error(f"Failed to check service access: {e}")
            return False


class BlockchainError(Exception):
    """Base exception for blockchain operations"""
    pass


class InsufficientBalanceError(BlockchainError):
    """Raised when user has insufficient balance"""
    pass


class TransactionFailedError(BlockchainError):
    """Raised when a transaction fails"""
    pass
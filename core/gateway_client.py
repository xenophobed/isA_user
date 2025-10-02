"""
Gateway Client Library for Internal Services
Provides authenticated communication with the Gateway service
"""
import httpx
import os
import socket
import json
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class GatewayClient:
    """
    Client for communicating with the Gateway service
    Handles internal service authentication automatically
    """
    
    def __init__(self, 
                 gateway_url: str = "http://localhost:8000",
                 service_name: str = None,
                 service_secret: str = None):
        """
        Initialize Gateway client
        
        Args:
            gateway_url: Base URL of the gateway service
            service_name: Name of this service for internal auth
            service_secret: Secret for service-to-service auth
        """
        self.gateway_url = gateway_url.rstrip('/')
        self.service_name = service_name or self._detect_service_name()
        self.service_secret = service_secret or os.getenv('GATEWAY_SERVICE_SECRET', 'dev-secret')
        
        # Create HTTP client with default headers
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers=self._get_default_headers()
        )
    
    def _detect_service_name(self) -> str:
        """Auto-detect service name from environment or context"""
        # Try environment variable first
        service_name = os.getenv('SERVICE_NAME')
        if service_name:
            return service_name
            
        # Try to detect from current working directory
        cwd = os.getcwd()
        if 'payment_service' in cwd:
            return 'payment'
        elif 'user_service' in cwd:
            return 'users'
        elif 'auth_service' in cwd:
            return 'auth'
        
        # Default fallback
        return 'unknown-service'
    
    def _get_default_headers(self) -> Dict[str, str]:
        """Get default headers for internal service requests"""
        return {
            "Content-Type": "application/json",
            "User-Agent": f"python-httpx/{self.service_name}-client",
            "X-Service-Name": self.service_name,
            "X-Service-Secret": self.service_secret,
            "X-Service-Host": socket.gethostname(),
        }
    
    async def call_blockchain_api(self, endpoint: str, method: str = "GET", data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Call blockchain API through Gateway
        
        Args:
            endpoint: Blockchain endpoint (e.g., 'status', 'balance/0x123')
            method: HTTP method
            data: Request payload for POST requests
            
        Returns:
            Response data from blockchain API
        """
        url = f"{self.gateway_url}/api/v1/blockchain/{endpoint}"
        
        try:
            if method.upper() == "GET":
                response = await self.client.get(url)
            elif method.upper() == "POST":
                response = await self.client.post(url, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Blockchain API call failed: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Blockchain API call error: {str(e)}")
            raise
    
    async def call_service_api(self, service: str, endpoint: str, method: str = "GET", 
                             data: Dict[str, Any] = None, headers: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Call another microservice through Gateway
        
        Args:
            service: Service name (e.g., 'users', 'agents', 'mcp')
            endpoint: Service endpoint
            method: HTTP method
            data: Request payload
            headers: Additional headers
            
        Returns:
            Response data from target service
        """
        url = f"{self.gateway_url}/api/v1/{service}/{endpoint}"
        
        # Merge additional headers
        request_headers = self._get_default_headers()
        if headers:
            request_headers.update(headers)
        
        try:
            if method.upper() == "GET":
                response = await self.client.get(url, headers=request_headers)
            elif method.upper() == "POST":
                response = await self.client.post(url, json=data, headers=request_headers)
            elif method.upper() == "PUT":
                response = await self.client.put(url, json=data, headers=request_headers)
            elif method.upper() == "DELETE":
                response = await self.client.delete(url, headers=request_headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            
            # Handle different content types
            content_type = response.headers.get('content-type', '')
            if 'application/json' in content_type:
                return response.json()
            else:
                return {"content": response.text, "content_type": content_type}
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Service API call failed: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Service API call error: {str(e)}")
            raise
    
    async def stream_service_api(self, service: str, endpoint: str, method: str = "POST",
                               data: Dict[str, Any] = None, headers: Dict[str, str] = None):
        """
        Stream data from a service API (for SSE endpoints)
        
        Args:
            service: Service name (e.g., 'agents', 'mcp')
            endpoint: Service endpoint
            method: HTTP method
            data: Request payload
            headers: Additional headers
            
        Yields:
            Streaming response lines
        """
        url = f"{self.gateway_url}/api/v1/{service}/{endpoint}"
        
        # Set up streaming headers
        request_headers = self._get_default_headers()
        request_headers["Accept"] = "text/event-stream"
        if headers:
            request_headers.update(headers)
        
        try:
            async with self.client.stream(method, url, json=data, headers=request_headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        yield line
                        
        except httpx.HTTPStatusError as e:
            logger.error(f"Streaming API call failed: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"Streaming API call error: {str(e)}")
            raise
    
    async def get_gateway_services(self) -> Dict[str, Any]:
        """Get list of available services from Gateway"""
        try:
            response = await self.client.get(f"{self.gateway_url}/api/v1/gateway/services")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get gateway services: {str(e)}")
            raise
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

# Convenience functions for common operations

async def call_blockchain_api(endpoint: str, method: str = "GET", data: Dict[str, Any] = None, 
                            service_name: str = None) -> Dict[str, Any]:
    """
    Convenience function to call blockchain API
    
    Usage:
        balance = await call_blockchain_api('balance/0x123')
        status = await call_blockchain_api('status')
    """
    async with GatewayClient(service_name=service_name) as client:
        return await client.call_blockchain_api(endpoint, method, data)

async def call_service_api(service: str, endpoint: str, method: str = "GET", 
                         data: Dict[str, Any] = None, service_name: str = None) -> Dict[str, Any]:
    """
    Convenience function to call another service API
    
    Usage:
        user_info = await call_service_api('users', 'api/v1/users/123')
        chat_response = await call_service_api('agents', 'api/chat', 'POST', {'message': 'Hello'})
    """
    async with GatewayClient(service_name=service_name) as client:
        return await client.call_service_api(service, endpoint, method, data)

async def stream_chat(message: str, session_id: str = None, user_id: str = None, service_name: str = None):
    """
    Convenience function for streaming chat with Agent service
    
    Usage:
        async for line in stream_chat('Hello', session_id='test-123'):
            if line.startswith('data: '):
                event_data = json.loads(line[6:])
                print(event_data)
    """
    payload = {
        "message": message,
        "session_id": session_id or "default-session",
        "user_id": user_id or "default-user"
    }
    
    async with GatewayClient(service_name=service_name) as client:
        async for line in client.stream_service_api('agents', 'api/chat', 'POST', payload):
            yield line

# Example usage and testing
if __name__ == "__main__":
    import asyncio
    
    async def test_gateway_client():
        """Test the Gateway client functionality"""
        
        # Test blockchain API
        try:
            status = await call_blockchain_api('status')
            print(f"Blockchain status: {status}")
        except Exception as e:
            print(f"Blockchain test failed: {e}")
        
        # Test service discovery
        try:
            async with GatewayClient(service_name='test-service') as client:
                services = await client.get_gateway_services()
                print(f"Available services: {services}")
        except Exception as e:
            print(f"Service discovery test failed: {e}")
        
        # Test streaming chat (if Agent service is available)
        try:
            print("Testing streaming chat...")
            async for line in stream_chat('Hello, test message', service_name='test-service'):
                print(f"Chat response: {line}")
                if 'end' in line:
                    break
        except Exception as e:
            print(f"Streaming chat test failed: {e}")
    
    # Run tests
    asyncio.run(test_gateway_client())
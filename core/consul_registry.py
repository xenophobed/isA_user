"""
Consul Service Registry Module

Provides service registration and health check functionality for microservices
"""

import consul
import logging
import asyncio
import socket
import json
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class ConsulRegistry:
    """Handles service registration with Consul"""
    
    def __init__(
        self,
        service_name: str,
        service_port: int,
        consul_host: str = "localhost",
        consul_port: int = 8500,
        service_host: Optional[str] = None,
        tags: Optional[List[str]] = None,
        health_check_type: str = "ttl"  # ttl or http
    ):
        """
        Initialize Consul registry
        
        Args:
            service_name: Name of the service to register
            service_port: Port the service is running on
            consul_host: Consul server host
            consul_port: Consul server port
            service_host: Service host (defaults to hostname)
            tags: Service tags for discovery
            health_check_type: Type of health check (ttl or http)
        """
        self.consul = consul.Consul(host=consul_host, port=consul_port)
        self.service_name = service_name
        self.service_port = service_port
        self.service_host = service_host or socket.gethostname()
        self.service_id = f"{service_name}-{self.service_host}-{service_port}"
        self.tags = tags or []
        self.check_interval = "10s"
        self.deregister_after = "60s"
        self._health_check_task = None
        self.health_check_type = health_check_type
        self.ttl_interval = 15  # seconds for TTL check
        
    def register(self) -> bool:
        """Register service with Consul"""
        try:
            # Choose health check type
            if self.health_check_type == "ttl":
                check = consul.Check.ttl(f"{self.ttl_interval}s")
            else:
                check = consul.Check.http(
                    f"http://{self.service_host}:{self.service_port}/health",
                    interval=self.check_interval,
                    timeout="5s",
                    deregister=self.deregister_after
                )
            
            # Register service with selected health check
            self.consul.agent.service.register(
                name=self.service_name,
                service_id=self.service_id,
                address=self.service_host,
                port=self.service_port,
                tags=self.tags,
                check=check
            )
            
            # If TTL, immediately pass the health check
            if self.health_check_type == "ttl":
                self.consul.agent.check.ttl_pass(f"service:{self.service_id}")
            
            logger.info(
                f"Service registered with Consul: {self.service_name} "
                f"({self.service_id}) at {self.service_host}:{self.service_port} "
                f"with {self.health_check_type} health check"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to register service with Consul: {e}")
            return False
    
    def deregister(self) -> bool:
        """Deregister service from Consul"""
        try:
            self.consul.agent.service.deregister(self.service_id)
            logger.info(f"Service deregistered from Consul: {self.service_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to deregister service from Consul: {e}")
            return False
    
    async def maintain_registration(self):
        """Maintain service registration (re-register if needed)"""
        while True:
            try:
                # Check if service is still registered
                services = self.consul.agent.services()
                if self.service_id not in services:
                    logger.warning(f"Service {self.service_id} not found in Consul, re-registering...")
                    self.register()
                
                # If using TTL checks, update the health status
                if self.health_check_type == "ttl":
                    try:
                        self.consul.agent.check.ttl_pass(
                            f"service:{self.service_id}",
                            "Service is healthy"
                        )
                        logger.debug(f"TTL health check passed for {self.service_id}")
                    except Exception as e:
                        logger.warning(f"Failed to update TTL health check: {e}")
                
                # Wait before next check (shorter for TTL)
                sleep_time = self.ttl_interval / 2 if self.health_check_type == "ttl" else 30
                await asyncio.sleep(sleep_time)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error maintaining registration: {e}")
                await asyncio.sleep(10)
    
    def start_maintenance(self):
        """Start the background maintenance task"""
        if not self._health_check_task:
            loop = asyncio.get_event_loop()
            self._health_check_task = loop.create_task(self.maintain_registration())
    
    def stop_maintenance(self):
        """Stop the background maintenance task"""
        if self._health_check_task:
            self._health_check_task.cancel()
            self._health_check_task = None
    
    # Configuration Management Methods
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value from Consul KV store"""
        try:
            full_key = f"{self.service_name}/{key}"
            index, data = self.consul.kv.get(full_key)
            if data and data.get('Value'):
                value = data['Value'].decode('utf-8')
                # Try to parse as JSON
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return default
        except Exception as e:
            logger.error(f"Failed to get config {key}: {e}")
            return default
    
    def set_config(self, key: str, value: Any) -> bool:
        """Set configuration value in Consul KV store"""
        try:
            full_key = f"{self.service_name}/{key}"
            # Convert to JSON if not string
            if not isinstance(value, str):
                value = json.dumps(value)
            return self.consul.kv.put(full_key, value)
        except Exception as e:
            logger.error(f"Failed to set config {key}: {e}")
            return False
    
    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration for this service"""
        try:
            prefix = f"{self.service_name}/"
            index, data = self.consul.kv.get(prefix, recurse=True)
            if not data:
                return {}
            
            config = {}
            for item in data:
                if item['Value']:
                    key = item['Key'].replace(prefix, '')
                    value = item['Value'].decode('utf-8')
                    try:
                        config[key] = json.loads(value)
                    except json.JSONDecodeError:
                        config[key] = value
            return config
        except Exception as e:
            logger.error(f"Failed to get all config: {e}")
            return {}
    
    def watch_config(self, key: str, callback):
        """Watch for configuration changes (blocking call)"""
        full_key = f"{self.service_name}/{key}"
        index = None
        while True:
            try:
                index, data = self.consul.kv.get(full_key, index=index, wait='30s')
                if data:
                    value = data['Value'].decode('utf-8')
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        pass
                    callback(key, value)
            except Exception as e:
                logger.error(f"Error watching config {key}: {e}")
                break
    
    # Service Discovery Methods
    def discover_service(self, service_name: str) -> List[Dict[str, Any]]:
        """Discover healthy instances of a service"""
        try:
            # Get health checks for the service
            index, services = self.consul.health.service(service_name, passing=True)
            
            instances = []
            for service in services:
                instance = {
                    'id': service['Service']['ID'],
                    'address': service['Service']['Address'],
                    'port': service['Service']['Port'],
                    'tags': service['Service'].get('Tags', []),
                    'meta': service['Service'].get('Meta', {})
                }
                instances.append(instance)
            
            return instances
        except Exception as e:
            logger.error(f"Failed to discover service {service_name}: {e}")
            return []
    
    def get_service_endpoint(self, service_name: str, strategy: str = 'random') -> Optional[str]:
        """Get a single service endpoint using load balancing strategy"""
        instances = self.discover_service(service_name)
        if not instances:
            return None
        
        # Load balancing strategies
        if strategy == 'random':
            import random
            instance = random.choice(instances)
        elif strategy == 'round_robin':
            # Simple round-robin (would need state management for proper implementation)
            instance = instances[0]
        else:
            # Default to first available
            instance = instances[0]
        
        return f"http://{instance['address']}:{instance['port']}"
    
    def watch_service(self, service_name: str, callback, wait_time: str = '30s'):
        """Watch for changes in service instances"""
        index = None
        while True:
            try:
                index, services = self.consul.health.service(
                    service_name, 
                    passing=True, 
                    index=index, 
                    wait=wait_time
                )
                # Convert to simplified format
                instances = []
                for service in services:
                    instances.append({
                        'id': service['Service']['ID'],
                        'address': service['Service']['Address'],
                        'port': service['Service']['Port']
                    })
                callback(service_name, instances)
            except Exception as e:
                logger.error(f"Error watching service {service_name}: {e}")
                break


@asynccontextmanager
async def consul_lifespan(
    app,
    service_name: str,
    service_port: int,
    consul_host: str = "localhost",
    consul_port: int = 8500,
    tags: Optional[List[str]] = None,
    health_check_type: str = "ttl"
):
    """
    FastAPI lifespan context manager for Consul registration
    
    Usage:
        app = FastAPI(lifespan=lambda app: consul_lifespan(app, "my-service", 8080))
    """
    # Startup
    # Use SERVICE_HOST env var if available, otherwise use hostname
    import os
    service_host = os.getenv('SERVICE_HOST', socket.gethostname())

    registry = ConsulRegistry(
        service_name=service_name,
        service_port=service_port,
        consul_host=consul_host,
        consul_port=consul_port,
        service_host=service_host,  # Use SERVICE_HOST from env or hostname
        tags=tags,
        health_check_type=health_check_type
    )
    
    # Register with Consul
    if registry.register():
        # Start maintenance task
        registry.start_maintenance()
        # Store in app state for access in routes
        app.state.consul_registry = registry
    else:
        logger.warning("Failed to register with Consul, continuing without service discovery")
    
    yield
    
    # Shutdown
    if hasattr(app.state, 'consul_registry'):
        registry.stop_maintenance()
        registry.deregister()
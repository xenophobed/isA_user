"""
NATS JetStream Client for Python Microservices
Provides event-driven communication with isA_Cloud
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List
from enum import Enum

import nats
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig
from nats.errors import TimeoutError

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Event types matching Go implementation"""
    # User Events
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_LOGGED_IN = "user.logged_in"
    USER_LOGGED_OUT = "user.logged_out"
    
    # Payment Events
    PAYMENT_INITIATED = "payment.initiated"
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_CANCELED = "subscription.canceled"
    
    # Organization Events
    ORG_CREATED = "organization.created"
    ORG_UPDATED = "organization.updated"
    ORG_MEMBER_ADDED = "organization.member_added"
    ORG_MEMBER_REMOVED = "organization.member_removed"
    
    # Task Events
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    TASK_ASSIGNED = "task.assigned"
    
    # Notification Events
    NOTIFICATION_SENT = "notification.sent"
    NOTIFICATION_READ = "notification.read"


class ServiceSource(Enum):
    """Service sources matching Go implementation"""
    AUTH_SERVICE = "auth_service"
    USER_SERVICE = "user_service"
    ORG_SERVICE = "organization_service"
    PAYMENT_SERVICE = "payment_service"
    TASK_SERVICE = "task_service"
    NOTIFICATION_SERVICE = "notification_service"
    AUDIT_SERVICE = "audit_service"
    GATEWAY = "api_gateway"


class Event:
    """Event model"""
    def __init__(self, 
                 event_type: EventType,
                 source: ServiceSource,
                 data: Dict[str, Any],
                 subject: Optional[str] = None,
                 metadata: Optional[Dict[str, str]] = None):
        self.id = str(uuid.uuid4())
        self.type = event_type.value
        self.source = source.value
        self.data = data
        self.subject = subject
        self.timestamp = datetime.utcnow().isoformat()
        self.metadata = metadata or {}
        self.version = "1.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "subject": self.subject,
            "timestamp": self.timestamp,
            "data": self.data,
            "metadata": self.metadata,
            "version": self.version
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        event = cls.__new__(cls)
        event.id = data.get("id")
        event.type = data.get("type")
        event.source = data.get("source")
        event.subject = data.get("subject")
        event.timestamp = data.get("timestamp")
        event.data = data.get("data", {})
        event.metadata = data.get("metadata", {})
        event.version = data.get("version", "1.0.0")
        return event


class NATSEventBus:
    """NATS JetStream event bus client"""
    
    def __init__(self, 
                 service_name: str,
                 nats_url: str = None,
                 username: str = None,
                 password: str = None):
        self.service_name = service_name
        self.nats_url = nats_url or os.getenv("NATS_URL", "nats://localhost:4222")
        self.username = username or os.getenv("NATS_USERNAME", "isa_user_service")
        self.password = password or os.getenv("NATS_PASSWORD", "service123")
        
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self._subscriptions = []
        self._is_connected = False
        
    async def connect(self):
        """Connect to NATS server"""
        try:
            self.nc = await nats.connect(
                servers=[self.nats_url],
                user=self.username,
                password=self.password,
                name=self.service_name,
                reconnect_time_wait=2,
                max_reconnect_attempts=10,
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback
            )
            
            # Create JetStream context
            self.js = self.nc.jetstream()
            
            # Initialize streams (will be created by Go service if not exists)
            await self._ensure_streams()
            
            self._is_connected = True
            logger.info(f"Connected to NATS at {self.nats_url}")
            
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise
    
    async def _ensure_streams(self):
        """Ensure required streams exist"""
        try:
            # Try to get stream info, streams should be created by Go service
            await self.js.stream_info("EVENTS")
            logger.info("Connected to EVENTS stream")
        except Exception as e:
            logger.warning(f"EVENTS stream not found, will be created by isA_Cloud: {e}")
    
    async def publish_event(self, event: Event) -> bool:
        """Publish an event to JetStream"""
        if not self._is_connected:
            logger.error("Not connected to NATS")
            return False
        
        try:
            # Construct subject
            subject = f"events.{event.source}.{event.type}"
            
            # Publish to JetStream
            ack = await self.js.publish(
                subject,
                json.dumps(event.to_dict()).encode()
            )
            
            logger.info(f"Published event {event.type} [{event.id}] to {subject}")
            return True
            
        except TimeoutError:
            logger.error(f"Timeout publishing event {event.id}")
            return False
        except Exception as e:
            logger.error(f"Error publishing event {event.id}: {e}")
            return False
    
    async def subscribe_to_events(self, 
                                  pattern: str,
                                  handler: Callable,
                                  durable: Optional[str] = None) -> str:
        """Subscribe to events with a pattern"""
        if not self._is_connected:
            logger.error("Not connected to NATS")
            return None
        
        try:
            # Create subject filter
            subject = f"events.{pattern}"
            
            # Try simple ephemeral consumer first (no durable)
            sub = await self.js.subscribe(
                subject,
                manual_ack=False  # Automatic ack for simplicity
            )
            
            # Start message handler
            asyncio.create_task(self._handle_messages(sub, handler))
            
            self._subscriptions.append(sub)
            logger.info(f"Subscribed to {subject} with durable {durable}")
            
            return durable
            
        except Exception as e:
            logger.error(f"Error subscribing to events: {e}")
            return None
    
    async def _handle_messages(self, subscription, handler: Callable):
        """Handle incoming messages"""
        try:
            async for msg in subscription.messages:
                try:
                    # Parse event
                    data = json.loads(msg.data.decode())
                    event = Event.from_dict(data)
                    
                    # Call handler
                    await handler(event)
                    
                    # Message auto-acknowledged (no manual ack needed)
                    
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    # Auto-ack mode - no manual error handling needed
                    
        except Exception as e:
            logger.error(f"Subscription error: {e}")
    
    async def close(self):
        """Close NATS connection"""
        if self.nc:
            await self.nc.close()
            self._is_connected = False
            logger.info("Disconnected from NATS")
    
    async def _error_callback(self, e):
        logger.error(f"NATS error: {e}")
    
    async def _disconnected_callback(self):
        self._is_connected = False
        logger.warning("Disconnected from NATS")
    
    async def _reconnected_callback(self):
        self._is_connected = True
        logger.info("Reconnected to NATS")


# Singleton instance
_event_bus: Optional[NATSEventBus] = None


async def get_event_bus(service_name: str) -> NATSEventBus:
    """Get or create event bus instance"""
    global _event_bus
    
    if _event_bus is None:
        _event_bus = NATSEventBus(service_name)
        await _event_bus.connect()
    
    return _event_bus


async def publish_payment_event(payment_id: str, 
                               amount: float, 
                               status: str,
                               user_id: str,
                               metadata: Optional[Dict] = None):
    """Helper function to publish payment events"""
    event_bus = await get_event_bus("payment_service")
    
    # Determine event type based on status
    event_type_map = {
        "initiated": EventType.PAYMENT_INITIATED,
        "completed": EventType.PAYMENT_COMPLETED,
        "failed": EventType.PAYMENT_FAILED,
        "refunded": EventType.PAYMENT_REFUNDED
    }
    
    event_type = event_type_map.get(status, EventType.PAYMENT_INITIATED)
    
    event = Event(
        event_type=event_type,
        source=ServiceSource.PAYMENT_SERVICE,
        data={
            "payment_id": payment_id,
            "amount": amount,
            "status": status,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        },
        metadata=metadata
    )
    
    return await event_bus.publish_event(event)
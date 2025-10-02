#!/usr/bin/env python
"""
Supabase Database Client
Centralized Supabase connection and utilities for the MCP server
"""
import os
import json
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

import logging
from functools import wraps

logger = logging.getLogger(__name__)

def require_client(default_return=None):
    """Decorator to check if client is available before executing method"""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            if self._client is None:
                logger.error(f"Error in {func.__name__}: Supabase client not available")
                return default_return
            return await func(self, *args, **kwargs)
        return wrapper
    return decorator

class SupabaseClient:
    """Singleton Supabase client for database operations"""
    
    _instance = None
    _client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SupabaseClient, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize Supabase client"""
        load_dotenv()
        
        # Load environment-specific configuration
        env = os.getenv("ENV", "development")
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, '../..'))
        
        if env == "development":
            env_file = os.path.join(project_root, "deployment/dev/.env")
        else:
            env_file = os.path.join(project_root, f"deployment/{env}/.env.{env}")
        
        if os.path.exists(env_file):
            load_dotenv(env_file)
        
        # Try multiple environment variable names for flexibility
        self.supabase_url = (
            os.getenv('SUPABASE_CLOUD_URL') or 
            os.getenv('NEXT_PUBLIC_SUPABASE_URL') or 
            os.getenv('SUPABASE_URL') or
            os.getenv('SUPABASE_LOCAL_URL')
        )
        self.supabase_key = (
            os.getenv('SUPABASE_CLOUD_SERVICE_ROLE_KEY') or 
            os.getenv('SUPABASE_SERVICE_ROLE_KEY') or 
            os.getenv('SUPABASE_LOCAL_SERVICE_ROLE_KEY') or
            os.getenv('SUPABASE_ANON_KEY') or
            os.getenv('SUPABASE_LOCAL_ANON_KEY')
        )
        
        if not self.supabase_url or not self.supabase_key:
            logger.warning("Missing Supabase credentials. Database operations will not be available.")
            self._client = None
            return
        
        try:
            self._client: Client = create_client(self.supabase_url, self.supabase_key)
            
            # Get schema from environment (defaults to 'public')
            self.schema = os.getenv('DB_SCHEMA', 'public')
            logger.info(f"Supabase client initialized successfully with schema: {self.schema}")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            raise
    
    @property
    def client(self) -> Client:
        """Get the Supabase client instance"""
        if self._client is None:
            self._initialize()
        if self._client is None:
            raise RuntimeError("Supabase client is not available")
        return self._client
    
    def table(self, table_name: str):
        """Get a table with the configured schema"""
        return self.client.schema(self.schema).table(table_name)
    
    def rpc(self, function_name: str, params: dict = None):
        """Call a remote procedure/function"""
        if params is None:
            params = {}
        return self.client.schema(self.schema).rpc(function_name, params)
    
    # Memory operations
    @require_client(default_return=None)
    async def get_memory(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a memory by key"""
        try:
            result = self.table('memories').select('*').eq('key', key).single().execute()
            return result.data if result.data else None
        except Exception as e:
            logger.error(f"Error getting memory {key}: {e}")
            return None
    
    @require_client(default_return=False)
    async def set_memory(self, key: str, value: str, category: str = "general", 
                        importance: int = 1, user_id: str = "default") -> bool:
        """Store or update a memory"""
        try:
            now = datetime.now().isoformat()
            
            # Try to update existing memory
            existing = await self.get_memory(key)
            if existing:
                result = self.table('memories').update({
                    'value': value,
                    'category': category,
                    'importance': importance,
                    'updated_at': now
                }).eq('key', key).execute()
            else:
                # Insert new memory
                result = self.table('memories').insert({
                    'key': key,
                    'value': value,
                    'category': category,
                    'importance': importance,
                    'created_by': user_id,
                    'created_at': now,
                    'updated_at': now
                }).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error setting memory {key}: {e}")
            return False
    
    async def search_memories(self, query: str, category: Optional[str] = None, 
                             limit: int = 10) -> List[Dict[str, Any]]:
        """Search memories by content"""
        try:
            query_builder = self.table('memories').select('*')
            
            if category:
                query_builder = query_builder.eq('category', category)
            
            # Full text search on key and value
            query_builder = query_builder.or_(f'key.ilike.%{query}%,value.ilike.%{query}%')
            query_builder = query_builder.order('importance', desc=True).limit(limit)
            
            result = query_builder.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error searching memories: {e}")
            return []
    
    async def delete_memory(self, key: str) -> bool:
        """Delete a memory by key"""
        try:
            result = self.table('memories').delete().eq('key', key).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting memory {key}: {e}")
            return False
    
    # User operations
    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        try:
            result = self.table('users').select('*').eq('user_id', user_id).single().execute()
            return result.data if result.data else None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    async def create_user(self, user_id: str, email: str = None, phone: str = None,
                         shipping_addresses: List[Dict] = None, 
                         payment_methods: List[Dict] = None,
                         preferences: Dict = None) -> bool:
        """Create a new user"""
        try:
            now = datetime.now().isoformat()
            
            result = self.table('users').insert({
                'user_id': user_id,
                'email': email,
                'phone': phone,
                'shipping_addresses': shipping_addresses or [],
                'payment_methods': payment_methods or [],
                'preferences': preferences or {},
                'created_at': now,
                'updated_at': now
            }).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            return False
    
    async def update_user(self, user_id: str, updates: Dict[str, Any]) -> bool:
        """Update user data"""
        try:
            updates['updated_at'] = datetime.now().isoformat()
            
            result = self.table('users').update(updates).eq('user_id', user_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return False
    
    # Session operations  
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get user session"""
        try:
            result = self.table('user_sessions').select('*').eq('session_id', session_id).single().execute()
            return result.data if result.data else None
        except Exception as e:
            logger.error(f"Error getting session {session_id}: {e}")
            return None
    
    async def create_session(self, session_id: str, user_id: str, 
                           cart_data: Dict = None, checkout_data: Dict = None,
                           expires_at: str = None) -> bool:
        """Create user session"""
        try:
            now = datetime.now().isoformat()
            
            result = self.table('user_sessions').insert({
                'session_id': session_id,
                'user_id': user_id,
                'cart_data': cart_data or {},
                'checkout_data': checkout_data or {},
                'created_at': now,
                'expires_at': expires_at
            }).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error creating session {session_id}: {e}")
            return False
    
    # Model operations
    async def get_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get model by ID"""
        try:
            result = self.table('models').select('*').eq('model_id', model_id).single().execute()
            return result.data if result.data else None
        except Exception as e:
            logger.error(f"Error getting model {model_id}: {e}")
            return None
    
    async def register_model(self, model_id: str, model_type: str, 
                           metadata: Dict = None, capabilities: List[str] = None) -> bool:
        """Register a new model"""
        try:
            now = datetime.now().isoformat()
            
            # Insert model
            result = self.table('models').insert({
                'model_id': model_id,
                'model_type': model_type,
                'metadata': json.dumps(metadata) if metadata else None,
                'created_at': now,
                'updated_at': now
            }).execute()
            
            # Insert capabilities
            if capabilities:
                capability_data = [
                    {'model_id': model_id, 'capability': cap} 
                    for cap in capabilities
                ]
                self.table('model_capabilities').insert(capability_data).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error registering model {model_id}: {e}")
            return False
    
    # Weather operations
    async def get_weather_cache(self, city: str) -> Optional[Dict[str, Any]]:
        """Get cached weather data"""
        try:
            result = self.table('weather_cache').select('*').eq('city', city).single().execute()
            return result.data if result.data else None
        except Exception as e:
            logger.error(f"Error getting weather cache for {city}: {e}")
            return None
    
    async def set_weather_cache(self, city: str, weather_data: Dict) -> bool:
        """Cache weather data"""
        try:
            now = datetime.now().isoformat()
            
            # Try to update existing cache
            existing = await self.get_weather_cache(city)
            if existing:
                result = self.table('weather_cache').update({
                    'weather_data': json.dumps(weather_data),
                    'updated_at': now
                }).eq('city', city).execute()
            else:
                result = self.table('weather_cache').insert({
                    'city': city,
                    'weather_data': json.dumps(weather_data),
                    'created_at': now,
                    'updated_at': now
                }).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error caching weather for {city}: {e}")
            return False
    
    # Audit operations
    async def log_tool_usage(self, tool_name: str, user_id: str, success: bool,
                           execution_time: float, security_level: str, 
                           details: str = None) -> bool:
        """Log tool usage to audit log"""
        try:
            result = self.table('audit_log').insert({
                'timestamp': datetime.now().isoformat(),
                'tool_name': tool_name,
                'user_id': user_id,
                'success': success,
                'execution_time': execution_time,
                'security_level': security_level,
                'details': details
            }).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error logging tool usage: {e}")
            return False
    
    # Authorization operations
    async def create_auth_request(self, request_id: str, tool_name: str, 
                                arguments: Dict, user_id: str, security_level: str,
                                reason: str, expires_at: str) -> bool:
        """Create authorization request"""
        try:
            result = self.table('authorization_requests').insert({
                'id': request_id,
                'tool_name': tool_name,
                'arguments': json.dumps(arguments),
                'user_id': user_id,
                'timestamp': datetime.now().isoformat(),
                'security_level': security_level,
                'reason': reason,
                'expires_at': expires_at,
                'status': 'pending'
            }).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error creating auth request: {e}")
            return False
    
    # Generic operations
    async def execute_query(self, table: str, operation: str, data: Dict = None, 
                           filters: Dict = None) -> Optional[Any]:
        """Execute generic database operation"""
        try:
            query_builder = self.table(table)
            
            if operation == 'select':
                query_builder = query_builder.select('*')
            elif operation == 'insert':
                return query_builder.insert(data).execute()
            elif operation == 'update':
                query_builder = query_builder.update(data)
            elif operation == 'delete':
                query_builder = query_builder.delete()
            
            # Apply filters
            if filters:
                for key, value in filters.items():
                    query_builder = query_builder.eq(key, value)
            
            return query_builder.execute()
            
        except Exception as e:
            logger.error(f"Error executing query on {table}: {e}")
            return None

# Global instance
_supabase_client = None

def get_supabase_client() -> SupabaseClient:
    """Get the global Supabase client instance"""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseClient()
    return _supabase_client
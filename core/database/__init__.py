"""
Database Management Module
Centralized database management for the MCP server
"""

from .supabase_client import get_supabase_client

__all__ = [
    'get_supabase_client'
]
"""
Configuration Manager for Microservices
Handles environment-specific configuration loading with best practices
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass, field
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class Environment(Enum):
    """Environment types"""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"
    LOCAL = "local"


@dataclass
class ServiceConfig:
    """Base configuration for a microservice"""
    service_name: str
    service_port: int
    environment: Environment
    debug: bool = False
    log_level: str = "INFO"

    # Service discovery
    consul_enabled: bool = True
    consul_host: str = "localhost"
    consul_port: int = 8500
    service_host: str = "localhost"

    # Database
    database_url: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None

    # NATS Configuration
    nats_enabled: bool = True
    nats_url: Optional[str] = None
    nats_username: Optional[str] = None
    nats_password: Optional[str] = None
    nats_servers: Optional[List[str]] = None

    # MinIO/S3 Configuration
    minio_enabled: bool = False
    minio_endpoint: Optional[str] = None
    minio_access_key: Optional[str] = None
    minio_secret_key: Optional[str] = None
    minio_secure: bool = False
    minio_bucket_name: Optional[str] = None

    # S3 Configuration (for production)
    s3_enabled: bool = False
    s3_bucket_name: Optional[str] = None
    s3_region: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None

    # Gateway Configuration
    gateway_url: Optional[str] = None
    gateway_enabled: bool = False

    # JWT/Auth Configuration
    local_jwt_secret: Optional[str] = None
    local_jwt_algorithm: str = "HS256"
    jwt_expiration: int = 3600
    auth0_domain: Optional[str] = None
    auth0_audience: Optional[str] = None

    # Additional service-specific configs
    extra_config: Dict[str, Any] = field(default_factory=dict)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get config value by key"""
        # First check direct attributes
        if hasattr(self, key):
            return getattr(self, key)
        # Then check extra_config
        return self.extra_config.get(key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        result = {
            "service_name": self.service_name,
            "service_port": self.service_port,
            "environment": self.environment.value,
            "debug": self.debug,
            "log_level": self.log_level,
            "consul_enabled": self.consul_enabled,
            "consul_host": self.consul_host,
            "consul_port": self.consul_port,
            "service_host": self.service_host,
        }
        
        if self.database_url:
            result["database_url"] = self.database_url
        if self.supabase_url:
            result["supabase_url"] = self.supabase_url
        if self.supabase_key:
            result["supabase_key"] = self.supabase_key
            
        # Add extra configs
        result.update(self.extra_config)
        return result


class ConfigManager:
    """
    Centralized configuration manager for microservices
    
    Load order (highest priority first):
    1. Environment variables
    2. .env.{environment} file (e.g., .env.production)
    3. .env file
    4. config/{environment}.json file
    5. config/default.json file
    6. Default values
    """
    
    def __init__(self, service_name: str, config_dir: Optional[Path] = None):
        """
        Initialize config manager
        
        Args:
            service_name: Name of the microservice
            config_dir: Directory containing config files (default: ./config)
        """
        self.service_name = service_name
        self.config_dir = config_dir or Path("config")
        self.environment = self._detect_environment()
        self._config_cache: Dict[str, Any] = {}
        
        # Load configurations in order
        self._load_configs()
    
    def _detect_environment(self) -> Environment:
        """Detect current environment from ENV variable"""
        env_name = os.getenv("ENV", os.getenv("ENVIRONMENT", "development")).lower()
        
        try:
            return Environment(env_name)
        except ValueError:
            logger.warning(f"Unknown environment: {env_name}, using development")
            return Environment.DEVELOPMENT
    
    def _load_configs(self):
        """Load all configuration sources"""
        # 1. Load default config file
        self._load_json_config("default.json")

        # 2. Load environment-specific config file
        env_config_file = f"{self.environment.value}.json"
        self._load_json_config(env_config_file)

        # 3. Map environment values to deployment folder names and env file names
        env_config_map = {
            "development": ("dev", ".env"),
            "testing": ("test", ".env.test"),
            "staging": ("staging", ".env.staging"),
            "production": ("production", ".env.production"),
            "local": ("dev", ".env")  # local uses dev environment
        }
        env_folder, env_filename = env_config_map.get(
            self.environment.value,
            (self.environment.value, ".env")
        )

        # 4. Load environment-specific .env file from deployment/{env}/.env{.suffix}
        env_file = f"deployment/{env_folder}/{env_filename}"
        self._load_env_file(env_file)

        # 5. Load .env.local (highest priority for local overrides)
        self._load_env_file(".env.local")

        # 6. Environment variables (highest priority)
        self._load_environment_variables()
    
    def _load_json_config(self, filename: str):
        """Load configuration from JSON file"""
        config_path = self.config_dir / filename
        
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config_data = json.load(f)
                    
                    # Merge with existing config
                    self._merge_config(config_data)
                    logger.info(f"Loaded config from {config_path}")
            except Exception as e:
                logger.error(f"Failed to load config from {config_path}: {e}")
    
    def _load_env_file(self, filename: str):
        """Load environment variables from .env file"""
        env_path = Path(filename)

        if env_path.exists():
            load_dotenv(env_path, override=False)
            logger.info(f"Loaded environment from {env_path}")
    
    def _load_environment_variables(self):
        """Load configuration from environment variables"""
        # Service-specific environment variables (e.g., PAYMENT_SERVICE_PORT)
        service_prefix = self.service_name.upper().replace("-", "_")
        
        for key, value in os.environ.items():
            # Check for service-specific variables
            if key.startswith(service_prefix):
                config_key = key[len(service_prefix) + 1:].lower()
                self._config_cache[config_key] = self._parse_value(value)
            
            # Also store general environment variables
            self._config_cache[key] = value
    
    def _merge_config(self, new_config: Dict[str, Any]):
        """Merge new configuration with existing"""
        for key, value in new_config.items():
            if isinstance(value, dict) and key in self._config_cache:
                # Merge nested dictionaries
                if isinstance(self._config_cache[key], dict):
                    self._config_cache[key].update(value)
                else:
                    self._config_cache[key] = value
            else:
                self._config_cache[key] = value
    
    def _parse_value(self, value: str) -> Any:
        """Parse string value to appropriate type"""
        # Try to parse as JSON first (handles lists, dicts, booleans)
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass

        # Try to parse as number
        if value.isdigit():
            return int(value)

        try:
            return float(value)
        except ValueError:
            pass

        # Return as string
        return value

    def _parse_bool(self, value: Any) -> bool:
        """Parse a value to boolean, handling string 'true'/'false' correctly"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key
        
        Args:
            key: Configuration key (case-insensitive)
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        # Try exact match first
        if key in self._config_cache:
            return self._config_cache[key]
        
        # Try lowercase
        lower_key = key.lower()
        if lower_key in self._config_cache:
            return self._config_cache[lower_key]
        
        # Try uppercase
        upper_key = key.upper()
        if upper_key in self._config_cache:
            return self._config_cache[upper_key]
        
        # Try with service prefix
        service_key = f"{self.service_name.upper()}_{upper_key}"
        if service_key in self._config_cache:
            return self._config_cache[service_key]
        
        return default
    
    def get_required(self, key: str) -> Any:
        """
        Get required configuration value
        
        Args:
            key: Configuration key
            
        Returns:
            Configuration value
            
        Raises:
            ValueError: If key not found
        """
        value = self.get(key)
        if value is None:
            raise ValueError(f"Required configuration '{key}' not found")
        return value
    
    def get_service_config(self) -> ServiceConfig:
        """
        Get service configuration object

        Returns:
            ServiceConfig object with all configurations
        """
        # Parse NATS servers if provided as comma-separated list
        nats_servers_str = self.get("NATS_SERVERS", self.get("nats_servers"))
        nats_servers = nats_servers_str.split(",") if nats_servers_str else None

        return ServiceConfig(
            service_name=self.service_name,
            service_port=int(self.get("port", self.get("service_port", 8000))),
            environment=self.environment,
            debug=self._parse_bool(self.get("debug", self.environment == Environment.DEVELOPMENT)),
            log_level=self.get("log_level", "DEBUG" if self.environment == Environment.DEVELOPMENT else "INFO"),

            # Consul
            consul_enabled=self._parse_bool(self.get("consul_enabled", True)),
            consul_host=self.get("CONSUL_HOST", self.get("consul_host", "localhost")),
            consul_port=int(self.get("CONSUL_PORT", self.get("consul_port", 8500))),
            service_host=self.get("SERVICE_HOST", self.get("service_host", "localhost")),

            # Database
            database_url=self.get("database_url"),
            supabase_url=self.get("SUPABASE_LOCAL_URL", self.get("SUPABASE_URL", self.get("supabase_url"))),
            supabase_key=self.get("SUPABASE_LOCAL_SERVICE_ROLE_KEY", self.get("SUPABASE_LOCAL_ANON_KEY", self.get("SUPABASE_KEY", self.get("supabase_key")))),

            # NATS
            nats_enabled=self._parse_bool(self.get("NATS_ENABLED", self.get("nats_enabled", True))),
            nats_url=self.get("NATS_URL", self.get("nats_url")),
            nats_username=self.get("NATS_USERNAME", self.get("nats_username")),
            nats_password=self.get("NATS_PASSWORD", self.get("nats_password")),
            nats_servers=nats_servers,

            # MinIO
            minio_enabled=self._parse_bool(self.get("MINIO_ENABLED", self.get("minio_enabled", False))),
            minio_endpoint=self.get("MINIO_ENDPOINT", self.get("minio_endpoint")),
            minio_access_key=self.get("MINIO_ACCESS_KEY", self.get("minio_access_key")),
            minio_secret_key=self.get("MINIO_SECRET_KEY", self.get("minio_secret_key")),
            minio_secure=self._parse_bool(self.get("MINIO_SECURE", self.get("minio_secure", False))),
            minio_bucket_name=self.get("MINIO_BUCKET_NAME", self.get("minio_bucket_name")),

            # S3 (for production)
            s3_enabled=self._parse_bool(self.get("S3_ENABLED", self.get("s3_enabled", False))),
            s3_bucket_name=self.get("S3_BUCKET_NAME", self.get("s3_bucket_name")),
            s3_region=self.get("S3_REGION", self.get("s3_region")),
            s3_access_key=self.get("S3_ACCESS_KEY", self.get("s3_access_key")),
            s3_secret_key=self.get("S3_SECRET_KEY", self.get("s3_secret_key")),

            # Gateway
            gateway_url=self.get("GATEWAY_URL", self.get("gateway_url")),
            gateway_enabled=self._parse_bool(self.get("GATEWAY_ENABLED", self.get("gateway_enabled", False))),

            # JWT/Auth Configuration
            local_jwt_secret=self.get("LOCAL_JWT_SECRET", self.get("AUTH_SERVICE_JWT_SECRET", self.get("local_jwt_secret"))),
            local_jwt_algorithm=self.get("LOCAL_JWT_ALGORITHM", self.get("local_jwt_algorithm", "HS256")),
            jwt_expiration=int(self.get("JWT_EXPIRATION", self.get("AUTH_SERVICE_JWT_EXPIRATION", self.get("jwt_expiration", 3600)))),
            auth0_domain=self.get("AUTH0_DOMAIN", self.get("auth0_domain")),
            auth0_audience=self.get("AUTH0_AUDIENCE", self.get("auth0_audience")),

            extra_config=self._get_service_specific_config()
        )
    
    def _get_service_specific_config(self) -> Dict[str, Any]:
        """Get service-specific configuration"""
        # Extract all non-standard configs
        standard_keys = {
            "service_name", "port", "service_port", "environment", "debug",
            "log_level", "consul_enabled", "consul_host", "consul_port",
            "service_host", "database_url", "supabase_url", "supabase_key",
            "nats_enabled", "nats_url", "nats_username", "nats_password", "nats_servers",
            "minio_enabled", "minio_endpoint", "minio_access_key", "minio_secret_key",
            "minio_secure", "minio_bucket_name",
            "s3_enabled", "s3_bucket_name", "s3_region", "s3_access_key", "s3_secret_key",
            "gateway_url", "gateway_enabled",
            "local_jwt_secret", "local_jwt_algorithm", "jwt_expiration", "auth0_domain", "auth0_audience",
            "auth_service_jwt_secret", "auth_service_jwt_expiration"
        }

        extra = {}
        for key, value in self._config_cache.items():
            if key.lower() not in standard_keys:
                extra[key] = value

        return extra
    
    def get_secrets(self) -> Dict[str, str]:
        """
        Get all secret/sensitive configurations
        
        Returns:
            Dictionary of secret configurations
        """
        secrets = {}
        secret_keys = [
            "api_key", "secret_key", "password", "token", "private_key",
            "webhook_secret", "stripe_secret_key", "stripe_webhook_secret"
        ]
        
        for key, value in self._config_cache.items():
            if any(secret in key.lower() for secret in secret_keys):
                secrets[key] = value
        
        return secrets
    
    def validate_required_configs(self, required_keys: List[str]):
        """
        Validate that required configurations exist
        
        Args:
            required_keys: List of required configuration keys
            
        Raises:
            ValueError: If any required configuration is missing
        """
        missing = []
        for key in required_keys:
            if self.get(key) is None:
                missing.append(key)
        
        if missing:
            raise ValueError(f"Missing required configurations: {', '.join(missing)}")
    
    def print_config_summary(self, show_secrets: bool = False):
        """Print configuration summary for debugging"""
        config = self.get_service_config()

        print(f"\n{'='*50}")
        print(f"Configuration for {self.service_name}")
        print(f"{'='*50}")
        print(f"Environment: {self.environment.value}")
        print(f"Service Port: {config.service_port}")
        print(f"Debug Mode: {config.debug}")
        print(f"Log Level: {config.log_level}")

        # Consul
        print(f"\n[Consul Service Discovery]")
        print(f"  Enabled: {config.consul_enabled}")
        print(f"  Host: {config.consul_host}:{config.consul_port}")

        # Database
        if config.database_url or config.supabase_url:
            print(f"\n[Database]")
            if config.database_url:
                print(f"  Database URL: {'***' if not show_secrets else config.database_url[:50]}...")
            if config.supabase_url:
                print(f"  Supabase URL: {config.supabase_url}")
                print(f"  Supabase Key: {'***' if not show_secrets else config.supabase_key[:20]}...")

        # NATS
        if config.nats_enabled or config.nats_url:
            print(f"\n[NATS Event Streaming]")
            print(f"  Enabled: {config.nats_enabled}")
            if config.nats_url:
                print(f"  URL: {config.nats_url}")
            if config.nats_username:
                print(f"  Username: {config.nats_username}")
                print(f"  Password: {'***' if not show_secrets else config.nats_password}")
            if config.nats_servers:
                print(f"  Servers: {', '.join(config.nats_servers)}")

        # MinIO
        if config.minio_enabled or config.minio_endpoint:
            print(f"\n[MinIO Object Storage]")
            print(f"  Enabled: {config.minio_enabled}")
            if config.minio_endpoint:
                print(f"  Endpoint: {config.minio_endpoint}")
                print(f"  Bucket: {config.minio_bucket_name}")
                print(f"  Access Key: {config.minio_access_key if show_secrets else '***'}")
                print(f"  Secure: {config.minio_secure}")

        # S3
        if config.s3_enabled or config.s3_bucket_name:
            print(f"\n[AWS S3 Storage]")
            print(f"  Enabled: {config.s3_enabled}")
            if config.s3_bucket_name:
                print(f"  Bucket: {config.s3_bucket_name}")
                print(f"  Region: {config.s3_region}")
                print(f"  Access Key: {config.s3_access_key[:20] if show_secrets and config.s3_access_key else '***'}")

        # Gateway
        if config.gateway_enabled or config.gateway_url:
            print(f"\n[API Gateway]")
            print(f"  Enabled: {config.gateway_enabled}")
            if config.gateway_url:
                print(f"  URL: {config.gateway_url}")

        if config.extra_config:
            print(f"\n[Extra Configurations]")
            for key, value in sorted(config.extra_config.items()):
                if not show_secrets and any(s in key.lower() for s in ["secret", "key", "password", "token"]):
                    print(f"  {key}: ***")
                else:
                    print(f"  {key}: {value}")

        print(f"{'='*50}\n")


# Convenience function for creating config manager
def create_config(service_name: str, config_dir: Optional[Path] = None) -> ConfigManager:
    """
    Create a configuration manager for a service
    
    Args:
        service_name: Name of the microservice
        config_dir: Directory containing config files
        
    Returns:
        ConfigManager instance
    """
    return ConfigManager(service_name, config_dir)
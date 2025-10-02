"""
便捷的 Logger 工具模块
为各个微服务提供预配置的 Logger 实例，集成 Loki 中心化日志
"""

import logging
import os
from typing import Optional
from .logging_config import UnifiedLoggingConfig, LogLevel


def setup_service_logger(
    service_name: str,
    component: Optional[str] = None,
    level: Optional[str] = None,
    log_dir: str = "logs",
    enable_loki: Optional[bool] = None
) -> logging.Logger:
    """
    为服务设置 logger (带 Loki 集成)

    Args:
        service_name: 服务名称 (例如: "payment_service", "auth_service")
        component: 组件名称 (例如: "API", "Database", "Worker")
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: 日志目录
        enable_loki: 是否启用 Loki (None 时使用环境变量)

    Returns:
        配置好的 logger 实例

    Example:
        >>> # 主 logger
        >>> app_logger = setup_service_logger("payment_service")
        >>> app_logger.info("Payment service started")
        >>>
        >>> # 组件 logger
        >>> api_logger = setup_service_logger("payment_service", "API")
        >>> api_logger.info("API request received")
    """
    # 构建 logger 名称
    logger_name = service_name
    if component:
        logger_name = f"{service_name}.{component}"

    # 避免重复配置
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    # 从环境变量读取日志级别
    log_level = level or os.getenv("LOG_LEVEL", "INFO")

    # 配置统一日志系统
    config = UnifiedLoggingConfig(logger_name, log_dir)
    logger = config.setup_logging(
        level=LogLevel(log_level.upper()),
        enable_console=True,
        enable_file=True,
        enable_json=True,
        enable_loki=enable_loki
    )

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取已存在的 logger 或创建新的 logger

    Args:
        name: Logger 名称

    Returns:
        Logger 实例

    Example:
        >>> logger = get_logger("payment_service.Stripe")
        >>> logger.info("Stripe integration initialized")
    """
    logger = logging.getLogger(name)

    # 如果 logger 还没有 handlers，使用默认配置
    if not logger.handlers:
        # 尝试从名称中提取服务名和组件名
        if "." in name:
            service_name, component = name.split(".", 1)
            return setup_service_logger(service_name, component)
        else:
            return setup_service_logger(name)

    return logger


# 预配置的常用 logger 工厂函数
def create_payment_logger(component: Optional[str] = None) -> logging.Logger:
    """创建 Payment Service logger"""
    return setup_service_logger("payment_service", component)


def create_auth_logger(component: Optional[str] = None) -> logging.Logger:
    """创建 Auth Service logger"""
    return setup_service_logger("auth_service", component)


def create_account_logger(component: Optional[str] = None) -> logging.Logger:
    """创建 Account Service logger"""
    return setup_service_logger("account_service", component)


def create_wallet_logger(component: Optional[str] = None) -> logging.Logger:
    """创建 Wallet Service logger"""
    return setup_service_logger("wallet_service", component)


def create_notification_logger(component: Optional[str] = None) -> logging.Logger:
    """创建 Notification Service logger"""
    return setup_service_logger("notification_service", component)


def create_order_logger(component: Optional[str] = None) -> logging.Logger:
    """创建 Order Service logger"""
    return setup_service_logger("order_service", component)


def create_device_logger(component: Optional[str] = None) -> logging.Logger:
    """创建 Device Service logger"""
    return setup_service_logger("device_service", component)


def create_event_logger(component: Optional[str] = None) -> logging.Logger:
    """创建 Event Service logger"""
    return setup_service_logger("event_service", component)


# 导出
__all__ = [
    "setup_service_logger",
    "get_logger",
    "create_payment_logger",
    "create_auth_logger",
    "create_account_logger",
    "create_wallet_logger",
    "create_notification_logger",
    "create_order_logger",
    "create_device_logger",
    "create_event_logger",
]

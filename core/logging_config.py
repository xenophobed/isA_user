"""
统一日志配置管理器
支持结构化日志、日志轮转、集中化配置
集成 Loki 中心化日志系统
"""

import logging
import logging.handlers
import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
from enum import Enum


class LogLevel(Enum):
    """日志级别枚举"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StructuredFormatter(logging.Formatter):
    """结构化JSON日志格式化器"""
    
    def __init__(self, service_name: str, include_trace: bool = True):
        self.service_name = service_name
        self.include_trace = include_trace
        super().__init__()
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为JSON"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "service": self.service_name,
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # 添加请求ID（如果存在）
        if hasattr(record, 'request_id'):
            log_data["request_id"] = record.request_id
        
        # 添加用户ID（如果存在）
        if hasattr(record, 'user_id'):
            log_data["user_id"] = record.user_id
        
        # 添加额外字段
        if hasattr(record, 'extra'):
            log_data["extra"] = record.extra
        
        # 添加异常信息
        if record.exc_info and self.include_trace:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info) if record.exc_info else None
            }
        
        return json.dumps(log_data, ensure_ascii=False)


class HumanReadableFormatter(logging.Formatter):
    """人类可读的日志格式化器"""
    
    def __init__(self, service_name: str, use_colors: bool = True):
        self.service_name = service_name
        self.use_colors = use_colors
        
        # 颜色代码
        self.colors = {
            'DEBUG': '\033[36m',    # 青色
            'INFO': '\033[32m',     # 绿色
            'WARNING': '\033[33m',  # 黄色
            'ERROR': '\033[31m',    # 红色
            'CRITICAL': '\033[35m', # 紫色
            'ENDC': '\033[0m'       # 结束颜色
        }
        
        fmt = "%(asctime)s | %(service)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
        super().__init__(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    
    def format(self, record: logging.LogRecord) -> str:
        # 添加服务名
        record.service = self.service_name
        
        # 格式化消息
        formatted = super().format(record)
        
        # 添加颜色（如果在终端环境）
        if self.use_colors and sys.stderr.isatty():
            level_color = self.colors.get(record.levelname, '')
            if level_color:
                formatted = f"{level_color}{formatted}{self.colors['ENDC']}"
        
        return formatted


class UnifiedLoggingConfig:
    """统一日志配置管理器"""

    def __init__(self, service_name: str, log_dir: str = "logs"):
        self.service_name = service_name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # 确保服务日志目录存在
        self.service_log_dir = self.log_dir / service_name
        self.service_log_dir.mkdir(exist_ok=True)

        # Loki 配置 (从环境变量读取)
        self.loki_url = os.getenv("LOKI_URL", "http://localhost:3100")
        self.loki_enabled = os.getenv("LOKI_ENABLED", "true").lower() == "true"

    def setup_logging(self,
                     level: LogLevel = LogLevel.INFO,
                     enable_console: bool = True,
                     enable_file: bool = True,
                     enable_json: bool = True,
                     enable_rotation: bool = True,
                     enable_loki: bool = None,  # 新增: Loki 支持
                     max_bytes: int = 10 * 1024 * 1024,  # 10MB
                     backup_count: int = 5) -> logging.Logger:
        """
        配置统一日志系统

        Args:
            level: 日志级别
            enable_console: 启用控制台输出
            enable_file: 启用文件输出
            enable_json: 启用JSON格式文件
            enable_rotation: 启用日志轮转
            enable_loki: 启用 Loki 中心化日志 (None 时使用环境变量)
            max_bytes: 单个日志文件最大大小
            backup_count: 保留的备份文件数量
        """

        # 决定是否启用 Loki (优先级: 参数 > 环境变量)
        use_loki = enable_loki if enable_loki is not None else self.loki_enabled
        
        # 获取根日志器
        logger = logging.getLogger(self.service_name)
        logger.setLevel(getattr(logging, level.value))
        
        # 清除现有处理器
        logger.handlers.clear()
        
        # 控制台处理器
        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, level.value))
            console_formatter = HumanReadableFormatter(
                self.service_name, 
                use_colors=True
            )
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)
        
        # 文件处理器 - 人类可读格式
        if enable_file:
            file_path = self.service_log_dir / f"{self.service_name}.log"
            
            if enable_rotation:
                file_handler = logging.handlers.RotatingFileHandler(
                    file_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding='utf-8'
                )
            else:
                file_handler = logging.FileHandler(file_path, encoding='utf-8')
            
            file_handler.setLevel(getattr(logging, level.value))
            file_formatter = HumanReadableFormatter(
                self.service_name, 
                use_colors=False
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        
        # JSON文件处理器 - 结构化格式
        if enable_json:
            json_file_path = self.service_log_dir / f"{self.service_name}.json"
            
            if enable_rotation:
                json_handler = logging.handlers.RotatingFileHandler(
                    json_file_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding='utf-8'
                )
            else:
                json_handler = logging.FileHandler(json_file_path, encoding='utf-8')
            
            json_handler.setLevel(getattr(logging, level.value))
            json_formatter = StructuredFormatter(self.service_name)
            json_handler.setFormatter(json_formatter)
            logger.addHandler(json_handler)
        
        # 设置错误处理器
        if enable_file:
            error_file_path = self.service_log_dir / f"{self.service_name}_error.log"
            error_handler = logging.FileHandler(error_file_path, encoding='utf-8')
            error_handler.setLevel(logging.ERROR)
            error_formatter = StructuredFormatter(self.service_name)
            error_handler.setFormatter(error_formatter)
            logger.addHandler(error_handler)

        # Loki Handler - 中心化日志系统
        if use_loki:
            try:
                from logging_loki import LokiHandler

                # 提取 logger 组件名称
                # 例如: "payment_service" -> service="payment", logger="main"
                # 例如: "payment_service.API" -> service="payment", logger="API"
                logger_component = "main"
                if "." in self.service_name:
                    parts = self.service_name.split(".", 1)
                    service_base = parts[0].replace("_service", "")
                    logger_component = parts[1]
                else:
                    service_base = self.service_name.replace("_service", "")

                # Loki 标签 (用于过滤和查询)
                loki_labels = {
                    "service": service_base,
                    "logger": logger_component,
                    "environment": os.getenv("ENVIRONMENT", os.getenv("ENV", "development")),
                    "job": f"{service_base}_service"
                }

                # 创建 Loki handler
                loki_handler = LokiHandler(
                    url=f"{self.loki_url}/loki/api/v1/push",
                    tags=loki_labels,
                    version="1",
                )

                # 只发送 INFO 及以上级别到 Loki (减少网络流量)
                loki_handler.setLevel(logging.INFO)

                logger.addHandler(loki_handler)

                # 只在主 logger 上记录一次成功信息
                if logger_component == "main":
                    logger.info(f"✅ Centralized logging enabled | loki_url={self.loki_url}")

            except ImportError:
                if self.service_name == "main" or "." not in self.service_name:
                    logger.warning("⚠️  python-logging-loki not installed. Logging to console/file only.")
            except Exception as e:
                # Loki 不可用 - 不影响应用启动
                if self.service_name == "main" or "." not in self.service_name:
                    logger.warning(f"⚠️  Could not connect to Loki: {e}")
                    logger.info("📝 Logging to console/file only")

        return logger
    
    def get_log_file_paths(self) -> Dict[str, str]:
        """获取日志文件路径"""
        return {
            "main_log": str(self.service_log_dir / f"{self.service_name}.log"),
            "json_log": str(self.service_log_dir / f"{self.service_name}.json"),
            "error_log": str(self.service_log_dir / f"{self.service_name}_error.log")
        }


class LoggingContextManager:
    """日志上下文管理器"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.context: Dict[str, Any] = {}
    
    def set_context(self, **kwargs):
        """设置日志上下文"""
        self.context.update(kwargs)
    
    def clear_context(self):
        """清除日志上下文"""
        self.context.clear()
    
    def log(self, level: str, message: str, **extra):
        """带上下文的日志记录"""
        combined_extra = {**self.context, **extra}
        
        # 创建LogRecord并添加额外信息
        record = self.logger.makeRecord(
            self.logger.name,
            getattr(logging, level.upper()),
            "",
            0,
            message,
            (),
            None
        )
        
        # 添加上下文信息
        for key, value in combined_extra.items():
            setattr(record, key, value)
        
        self.logger.handle(record)
    
    def info(self, message: str, **extra):
        self.log("info", message, **extra)
    
    def error(self, message: str, **extra):
        self.log("error", message, **extra)
    
    def warning(self, message: str, **extra):
        self.log("warning", message, **extra)
    
    def debug(self, message: str, **extra):
        self.log("debug", message, **extra)


def setup_service_logging(service_name: str, 
                         level: str = "INFO",
                         log_dir: str = "logs") -> tuple[logging.Logger, LoggingContextManager]:
    """
    便捷函数：为服务设置统一日志
    
    Returns:
        tuple: (logger, context_manager)
    """
    config = UnifiedLoggingConfig(service_name, log_dir)
    logger = config.setup_logging(LogLevel(level.upper()))
    context_manager = LoggingContextManager(logger)
    
    return logger, context_manager


# 导出主要类和函数
__all__ = [
    "UnifiedLoggingConfig",
    "LoggingContextManager", 
    "StructuredFormatter",
    "HumanReadableFormatter",
    "LogLevel",
    "setup_service_logging"
]
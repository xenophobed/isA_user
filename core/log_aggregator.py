"""
日志聚合和分析工具
提供日志收集、分析和监控功能
"""

import json
import asyncio
import aiofiles
from datetime import datetime, timedelta
from typing import Dict, List, Optional, AsyncGenerator, Any
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
import re
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class LogSeverity(Enum):
    """日志严重性级别"""
    DEBUG = 1
    INFO = 2
    WARNING = 3
    ERROR = 4
    CRITICAL = 5


@dataclass
class LogEntry:
    """标准化日志条目"""
    timestamp: datetime
    service: str
    level: str
    message: str
    logger: str
    module: Optional[str] = None
    function: Optional[str] = None
    line: Optional[int] = None
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    exception: Optional[Dict] = None
    extra: Optional[Dict] = None


@dataclass
class LogMetrics:
    """日志指标"""
    total_logs: int
    error_count: int
    warning_count: int
    services: List[str]
    time_range: Dict[str, str]
    error_rate: float
    top_errors: List[Dict[str, Any]]
    service_distribution: Dict[str, int]


@dataclass
class ServiceHealth:
    """基于日志的服务健康状态"""
    service_name: str
    status: str  # healthy, degraded, unhealthy
    last_log_time: datetime
    error_count_1h: int
    warning_count_1h: int
    total_logs_1h: int
    error_rate_1h: float
    common_errors: List[str]


class LogAggregator:
    """日志聚合器"""
    
    def __init__(self, log_directory: str = "logs"):
        self.log_directory = Path(log_directory)
        self.parsed_logs: List[LogEntry] = []
        self.metrics_cache: Optional[LogMetrics] = None
        self.cache_ttl = 300  # 5分钟缓存
        self.last_cache_time: Optional[datetime] = None
    
    async def parse_log_line(self, line: str, service_name: str) -> Optional[LogEntry]:
        """解析单行日志"""
        line = line.strip()
        if not line:
            return None
        
        try:
            # 尝试解析JSON格式
            if line.startswith('{'):
                data = json.loads(line)
                return LogEntry(
                    timestamp=datetime.fromisoformat(data.get('timestamp', '').replace('Z', '+00:00')),
                    service=data.get('service', service_name),
                    level=data.get('level', 'INFO'),
                    message=data.get('message', ''),
                    logger=data.get('logger', ''),
                    module=data.get('module'),
                    function=data.get('function'),
                    line=data.get('line'),
                    request_id=data.get('request_id'),
                    user_id=data.get('user_id'),
                    exception=data.get('exception'),
                    extra=data.get('extra')
                )
            else:
                # 解析传统格式日志
                return await self.parse_traditional_log(line, service_name)
                
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug(f"Failed to parse log line: {e}")
            return None
    
    async def parse_traditional_log(self, line: str, service_name: str) -> Optional[LogEntry]:
        """解析传统格式日志"""
        # 匹配格式: "2025-09-28 15:44:27,291 - logger_name - LEVEL - message"
        pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (.*?) - (DEBUG|INFO|WARNING|ERROR|CRITICAL) - (.*)'
        match = re.match(pattern, line)
        
        if match:
            timestamp_str, logger_name, level, message = match.groups()
            try:
                # 转换时间戳
                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')
                
                return LogEntry(
                    timestamp=timestamp,
                    service=service_name,
                    level=level,
                    message=message.strip(),
                    logger=logger_name.strip()
                )
            except ValueError:
                pass
        
        return None
    
    async def read_service_logs(self, service_name: str, 
                              hours_back: int = 24) -> AsyncGenerator[LogEntry, None]:
        """读取指定服务的日志"""
        service_dir = self.log_directory / service_name
        
        # 检查服务特定目录
        if service_dir.exists():
            log_files = list(service_dir.glob("*.log")) + list(service_dir.glob("*.json"))
        else:
            # 回退到根目录下的日志文件
            log_files = list(self.log_directory.glob(f"{service_name}*.log"))
        
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        for log_file in log_files:
            try:
                async with aiofiles.open(log_file, 'r', encoding='utf-8') as f:
                    async for line in f:
                        entry = await self.parse_log_line(line, service_name)
                        if entry and entry.timestamp >= cutoff_time:
                            yield entry
            except Exception as e:
                logger.warning(f"Failed to read log file {log_file}: {e}")
    
    async def collect_all_logs(self, hours_back: int = 24) -> List[LogEntry]:
        """收集所有服务日志"""
        all_logs = []
        
        # 获取所有服务名
        services = set()
        
        # 从目录结构推断服务名
        for item in self.log_directory.iterdir():
            if item.is_dir():
                services.add(item.name)
            elif item.is_file() and item.suffix == '.log':
                # 从文件名推断服务名
                service_name = item.stem.replace('_service', '').replace('-service', '')
                services.add(service_name)
        
        # 收集每个服务的日志
        for service in services:
            async for log_entry in self.read_service_logs(service, hours_back):
                all_logs.append(log_entry)
        
        # 按时间排序
        all_logs.sort(key=lambda x: x.timestamp)
        self.parsed_logs = all_logs
        
        return all_logs
    
    async def generate_metrics(self, hours_back: int = 24) -> LogMetrics:
        """生成日志指标"""
        now = datetime.now()
        
        # 检查缓存
        if (self.metrics_cache and self.last_cache_time and 
            (now - self.last_cache_time).total_seconds() < self.cache_ttl):
            return self.metrics_cache
        
        # 收集日志
        logs = await self.collect_all_logs(hours_back)
        
        if not logs:
            return LogMetrics(
                total_logs=0,
                error_count=0,
                warning_count=0,
                services=[],
                time_range={},
                error_rate=0.0,
                top_errors=[],
                service_distribution={}
            )
        
        # 统计指标
        total_logs = len(logs)
        error_count = len([log for log in logs if log.level == 'ERROR'])
        warning_count = len([log for log in logs if log.level == 'WARNING'])
        
        services = list(set(log.service for log in logs))
        
        time_range = {
            'start': logs[0].timestamp.isoformat(),
            'end': logs[-1].timestamp.isoformat()
        }
        
        error_rate = (error_count / total_logs) * 100 if total_logs > 0 else 0
        
        # 顶级错误
        error_messages = [log.message for log in logs if log.level == 'ERROR']
        error_counter = Counter(error_messages)
        top_errors = [
            {'message': msg, 'count': count} 
            for msg, count in error_counter.most_common(10)
        ]
        
        # 服务分布
        service_counter = Counter(log.service for log in logs)
        service_distribution = dict(service_counter)
        
        metrics = LogMetrics(
            total_logs=total_logs,
            error_count=error_count,
            warning_count=warning_count,
            services=services,
            time_range=time_range,
            error_rate=error_rate,
            top_errors=top_errors,
            service_distribution=service_distribution
        )
        
        # 更新缓存
        self.metrics_cache = metrics
        self.last_cache_time = now
        
        return metrics
    
    async def get_service_health(self, service_name: str) -> ServiceHealth:
        """获取服务健康状态"""
        logs = []
        async for log_entry in self.read_service_logs(service_name, hours_back=1):
            logs.append(log_entry)
        
        if not logs:
            return ServiceHealth(
                service_name=service_name,
                status="unknown",
                last_log_time=datetime.min,
                error_count_1h=0,
                warning_count_1h=0,
                total_logs_1h=0,
                error_rate_1h=0.0,
                common_errors=[]
            )
        
        # 统计最近1小时的指标
        error_count = len([log for log in logs if log.level == 'ERROR'])
        warning_count = len([log for log in logs if log.level == 'WARNING'])
        total_logs = len(logs)
        
        error_rate = (error_count / total_logs) * 100 if total_logs > 0 else 0
        
        # 常见错误
        error_messages = [log.message for log in logs if log.level == 'ERROR']
        common_errors = [msg for msg, _ in Counter(error_messages).most_common(5)]
        
        # 确定健康状态
        if error_rate > 10 or error_count > 50:
            status = "unhealthy"
        elif error_rate > 5 or warning_count > 20:
            status = "degraded"
        else:
            status = "healthy"
        
        return ServiceHealth(
            service_name=service_name,
            status=status,
            last_log_time=max(log.timestamp for log in logs),
            error_count_1h=error_count,
            warning_count_1h=warning_count,
            total_logs_1h=total_logs,
            error_rate_1h=error_rate,
            common_errors=common_errors
        )
    
    async def search_logs(self, 
                         query: str,
                         service: Optional[str] = None,
                         level: Optional[str] = None,
                         hours_back: int = 24,
                         limit: int = 100) -> List[LogEntry]:
        """搜索日志"""
        logs = await self.collect_all_logs(hours_back)
        
        results = []
        query_lower = query.lower()
        
        for log in logs:
            # 过滤条件
            if service and log.service != service:
                continue
            if level and log.level != level:
                continue
            
            # 搜索匹配
            if (query_lower in log.message.lower() or 
                query_lower in log.logger.lower()):
                results.append(log)
                
                if len(results) >= limit:
                    break
        
        return results
    
    def to_dict(self, obj) -> Dict:
        """转换对象为字典"""
        if isinstance(obj, LogMetrics):
            return asdict(obj)
        elif isinstance(obj, ServiceHealth):
            result = asdict(obj)
            result['last_log_time'] = obj.last_log_time.isoformat()
            return result
        elif isinstance(obj, LogEntry):
            result = asdict(obj)
            result['timestamp'] = obj.timestamp.isoformat()
            return result
        return {}


class LogMonitor:
    """日志监控器"""
    
    def __init__(self, aggregator: LogAggregator):
        self.aggregator = aggregator
        self.alert_thresholds = {
            'error_rate': 5.0,  # 错误率超过5%
            'error_count': 20,  # 1小时内错误数超过20
            'no_logs_minutes': 10,  # 10分钟没有日志
        }
    
    async def check_alerts(self) -> List[Dict[str, Any]]:
        """检查告警条件"""
        alerts = []
        
        metrics = await self.aggregator.generate_metrics(hours_back=1)
        
        # 检查全局错误率
        if metrics.error_rate > self.alert_thresholds['error_rate']:
            alerts.append({
                'type': 'high_error_rate',
                'severity': 'warning',
                'message': f"Global error rate {metrics.error_rate:.2f}% exceeds threshold {self.alert_thresholds['error_rate']}%",
                'value': metrics.error_rate,
                'timestamp': datetime.now().isoformat()
            })
        
        # 检查每个服务
        for service in metrics.services:
            health = await self.aggregator.get_service_health(service)
            
            # 服务错误率告警
            if health.error_rate_1h > self.alert_thresholds['error_rate']:
                alerts.append({
                    'type': 'service_high_error_rate',
                    'severity': 'warning',
                    'service': service,
                    'message': f"Service {service} error rate {health.error_rate_1h:.2f}% exceeds threshold",
                    'value': health.error_rate_1h,
                    'timestamp': datetime.now().isoformat()
                })
            
            # 服务无日志告警
            time_since_last_log = datetime.now() - health.last_log_time
            if time_since_last_log.total_seconds() > self.alert_thresholds['no_logs_minutes'] * 60:
                alerts.append({
                    'type': 'service_no_logs',
                    'severity': 'critical',
                    'service': service,
                    'message': f"Service {service} has not logged for {time_since_last_log.total_seconds()/60:.1f} minutes",
                    'value': time_since_last_log.total_seconds(),
                    'timestamp': datetime.now().isoformat()
                })
        
        return alerts


# 便捷函数
async def get_log_summary(log_dir: str = "logs", hours: int = 24) -> Dict[str, Any]:
    """获取日志摘要"""
    aggregator = LogAggregator(log_dir)
    metrics = await aggregator.generate_metrics(hours)
    return aggregator.to_dict(metrics)


async def search_recent_errors(log_dir: str = "logs", hours: int = 1) -> List[Dict]:
    """搜索最近错误"""
    aggregator = LogAggregator(log_dir)
    errors = await aggregator.search_logs("", level="ERROR", hours_back=hours)
    return [aggregator.to_dict(error) for error in errors[:20]]


# 导出主要类
__all__ = [
    "LogAggregator",
    "LogMonitor", 
    "LogEntry",
    "LogMetrics",
    "ServiceHealth",
    "get_log_summary",
    "search_recent_errors"
]
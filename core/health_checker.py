"""
Enhanced Health Checker

提供增强的健康检查功能，包括依赖服务检查、数据库连接检查等
"""

import asyncio
import time
import socket
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import aiohttp
import json

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """健康状态枚举"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class DependencyHealth:
    """依赖服务健康状态"""
    name: str
    status: HealthStatus
    response_time: float
    error_message: Optional[str] = None
    last_check: Optional[datetime] = None


@dataclass
class ServiceHealthReport:
    """服务健康报告"""
    service_name: str
    overall_status: HealthStatus
    version: str
    uptime: float
    dependencies: Dict[str, DependencyHealth]
    metrics: Dict[str, any]
    timestamp: datetime


class ServiceHealthChecker:
    """增强的服务健康检查器"""
    
    def __init__(self, service_name: str, version: str = "1.0.0"):
        self.service_name = service_name
        self.version = version
        self.start_time = time.time()
        self.dependencies: Dict[str, Dict] = {}
        self.health_cache: Dict[str, Tuple[DependencyHealth, datetime]] = {}
        self.cache_ttl = 30  # 30秒缓存
    
    def add_dependency(self, name: str, url: str, timeout: float = 5.0, critical: bool = True):
        """添加依赖服务"""
        self.dependencies[name] = {
            "url": url,
            "timeout": timeout,
            "critical": critical
        }
    
    async def check_database_health(self, db_url: Optional[str] = None) -> DependencyHealth:
        """检查数据库健康状态"""
        start_time = time.time()
        
        try:
            if not db_url:
                return DependencyHealth(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    response_time=0,
                    error_message="No database configured"
                )
            
            # 这里应该根据数据库类型实现具体的检查逻辑
            # 目前返回模拟结果
            response_time = time.time() - start_time
            
            return DependencyHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                response_time=response_time * 1000,
                last_check=datetime.utcnow()
            )
            
        except Exception as e:
            response_time = time.time() - start_time
            return DependencyHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                response_time=response_time * 1000,
                error_message=str(e),
                last_check=datetime.utcnow()
            )
    
    async def check_external_api_health(self, api_url: str, timeout: float = 5.0) -> DependencyHealth:
        """检查外部API健康状态"""
        start_time = time.time()
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(f"{api_url}/health") as response:
                    response_time = time.time() - start_time
                    
                    if response.status == 200:
                        status = HealthStatus.HEALTHY
                        error_message = None
                    else:
                        status = HealthStatus.DEGRADED
                        error_message = f"HTTP {response.status}"
                    
                    return DependencyHealth(
                        name=api_url,
                        status=status,
                        response_time=response_time * 1000,
                        error_message=error_message,
                        last_check=datetime.utcnow()
                    )
                    
        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            return DependencyHealth(
                name=api_url,
                status=HealthStatus.UNHEALTHY,
                response_time=response_time * 1000,
                error_message="Request timeout",
                last_check=datetime.utcnow()
            )
        except Exception as e:
            response_time = time.time() - start_time
            return DependencyHealth(
                name=api_url,
                status=HealthStatus.UNHEALTHY,
                response_time=response_time * 1000,
                error_message=str(e),
                last_check=datetime.utcnow()
            )
    
    async def check_service_connectivity(self, host: str, port: int, timeout: float = 3.0) -> DependencyHealth:
        """检查服务连接性"""
        start_time = time.time()
        
        try:
            # 创建socket连接测试
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            
            result = sock.connect_ex((host, port))
            sock.close()
            
            response_time = time.time() - start_time
            
            if result == 0:
                status = HealthStatus.HEALTHY
                error_message = None
            else:
                status = HealthStatus.UNHEALTHY
                error_message = f"Connection failed (code: {result})"
            
            return DependencyHealth(
                name=f"{host}:{port}",
                status=status,
                response_time=response_time * 1000,
                error_message=error_message,
                last_check=datetime.utcnow()
            )
            
        except Exception as e:
            response_time = time.time() - start_time
            return DependencyHealth(
                name=f"{host}:{port}",
                status=HealthStatus.UNHEALTHY,
                response_time=response_time * 1000,
                error_message=str(e),
                last_check=datetime.utcnow()
            )
    
    async def check_dependent_services(self) -> Dict[str, DependencyHealth]:
        """检查所有依赖服务"""
        results = {}
        
        # 检查缓存
        now = datetime.utcnow()
        for name, dep_config in self.dependencies.items():
            # 检查缓存是否有效
            if name in self.health_cache:
                cached_health, cached_time = self.health_cache[name]
                if (now - cached_time).total_seconds() < self.cache_ttl:
                    results[name] = cached_health
                    continue
            
            # 执行健康检查
            url = dep_config["url"]
            timeout = dep_config["timeout"]
            
            try:
                if url.startswith("http"):
                    health = await self.check_external_api_health(url, timeout)
                else:
                    # 假设是 host:port 格式
                    host, port = url.split(":")
                    health = await self.check_service_connectivity(host, int(port), timeout)
                
                results[name] = health
                self.health_cache[name] = (health, now)
                
            except Exception as e:
                health = DependencyHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    response_time=0,
                    error_message=f"Check failed: {str(e)}",
                    last_check=now
                )
                results[name] = health
                self.health_cache[name] = (health, now)
        
        return results
    
    def get_uptime(self) -> float:
        """获取服务运行时间（秒）"""
        return time.time() - self.start_time
    
    def determine_overall_status(self, dependencies: Dict[str, DependencyHealth]) -> HealthStatus:
        """根据依赖状态确定整体健康状态"""
        if not dependencies:
            return HealthStatus.HEALTHY
        
        critical_unhealthy = 0
        critical_degraded = 0
        total_critical = 0
        
        for name, health in dependencies.items():
            dep_config = self.dependencies.get(name, {})
            is_critical = dep_config.get("critical", True)
            
            if is_critical:
                total_critical += 1
                if health.status == HealthStatus.UNHEALTHY:
                    critical_unhealthy += 1
                elif health.status == HealthStatus.DEGRADED:
                    critical_degraded += 1
        
        # 如果有关键依赖不健康，整体状态为不健康
        if critical_unhealthy > 0:
            return HealthStatus.UNHEALTHY
        
        # 如果有关键依赖降级，整体状态为降级
        if critical_degraded > 0:
            return HealthStatus.DEGRADED
        
        return HealthStatus.HEALTHY
    
    async def get_comprehensive_health_report(self, 
                                            db_url: Optional[str] = None,
                                            include_metrics: bool = True) -> ServiceHealthReport:
        """获取综合健康报告"""
        
        # 检查依赖服务
        dependencies = await self.check_dependent_services()
        
        # 检查数据库（如果配置了）
        if db_url:
            db_health = await self.check_database_health(db_url)
            dependencies["database"] = db_health
        
        # 确定整体状态
        overall_status = self.determine_overall_status(dependencies)
        
        # 收集性能指标
        metrics = {}
        if include_metrics:
            metrics = {
                "uptime_seconds": self.get_uptime(),
                "dependency_count": len(dependencies),
                "healthy_dependencies": len([d for d in dependencies.values() if d.status == HealthStatus.HEALTHY]),
                "degraded_dependencies": len([d for d in dependencies.values() if d.status == HealthStatus.DEGRADED]),
                "unhealthy_dependencies": len([d for d in dependencies.values() if d.status == HealthStatus.UNHEALTHY]),
                "average_response_time": sum(d.response_time for d in dependencies.values()) / len(dependencies) if dependencies else 0
            }
        
        return ServiceHealthReport(
            service_name=self.service_name,
            overall_status=overall_status,
            version=self.version,
            uptime=self.get_uptime(),
            dependencies=dependencies,
            metrics=metrics,
            timestamp=datetime.utcnow()
        )
    
    def to_dict(self, health_report: ServiceHealthReport) -> Dict:
        """将健康报告转换为字典"""
        result = asdict(health_report)
        
        # 转换枚举值
        result["overall_status"] = health_report.overall_status.value
        
        # 转换依赖状态
        deps = {}
        for name, dep in health_report.dependencies.items():
            deps[name] = {
                "status": dep.status.value,
                "response_time_ms": round(dep.response_time, 2),
                "error_message": dep.error_message,
                "last_check": dep.last_check.isoformat() if dep.last_check else None
            }
        result["dependencies"] = deps
        
        # 转换时间戳
        result["timestamp"] = health_report.timestamp.isoformat()
        
        return result


class HealthCheckRegistry:
    """健康检查注册中心"""
    
    def __init__(self):
        self.checkers: Dict[str, ServiceHealthChecker] = {}
    
    def register_service(self, service_name: str, version: str = "1.0.0") -> ServiceHealthChecker:
        """注册服务健康检查器"""
        checker = ServiceHealthChecker(service_name, version)
        self.checkers[service_name] = checker
        return checker
    
    def get_checker(self, service_name: str) -> Optional[ServiceHealthChecker]:
        """获取服务健康检查器"""
        return self.checkers.get(service_name)
    
    async def get_all_health_reports(self) -> Dict[str, Dict]:
        """获取所有服务的健康报告"""
        reports = {}
        
        for service_name, checker in self.checkers.items():
            try:
                report = await checker.get_comprehensive_health_report()
                reports[service_name] = checker.to_dict(report)
            except Exception as e:
                logger.error(f"Failed to get health report for {service_name}: {e}")
                reports[service_name] = {
                    "service_name": service_name,
                    "overall_status": "unhealthy",
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
        
        return reports


# 全局健康检查注册中心
health_registry = HealthCheckRegistry()


def setup_common_dependencies(checker: ServiceHealthChecker):
    """设置常见的依赖服务"""
    # Consul
    checker.add_dependency("consul", "localhost:8500", timeout=3.0, critical=False)
    
    # Auth Service
    checker.add_dependency("auth_service", "http://localhost:8202", timeout=5.0, critical=True)


async def main():
    """测试健康检查功能"""
    print("Testing Enhanced Health Checker...")
    
    # 创建测试检查器
    checker = ServiceHealthChecker("test_service", "1.0.0")
    
    # 添加依赖
    setup_common_dependencies(checker)
    
    # 获取健康报告
    report = await checker.get_comprehensive_health_report()
    report_dict = checker.to_dict(report)
    
    print(json.dumps(report_dict, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
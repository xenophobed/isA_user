"""
Configuration Validator

提供配置验证功能，确保服务配置的正确性和一致性
"""

import json
import socket
from typing import Dict, List, Set, Tuple, Optional
from pathlib import Path
import subprocess
import logging

logger = logging.getLogger(__name__)


class ConfigValidator:
    """配置验证器"""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def validate_port_range(self, port: int, service_name: str) -> bool:
        """验证端口范围是否合理"""
        if not isinstance(port, int):
            self.errors.append(f"{service_name}: Port must be an integer, got {type(port)}")
            return False
        
        if port < 1024:
            self.errors.append(f"{service_name}: Port {port} is reserved (< 1024)")
            return False
        
        if port > 65535:
            self.errors.append(f"{service_name}: Port {port} is out of valid range (> 65535)")
            return False
        
        if port < 8200 or port > 8299:
            self.warnings.append(f"{service_name}: Port {port} is outside recommended range (8200-8299)")
        
        return True
    
    def check_port_availability(self, port: int, service_name: str) -> bool:
        """检查端口是否可用"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('localhost', port))
                if result == 0:
                    self.warnings.append(f"{service_name}: Port {port} is currently in use")
                    return False
                return True
        except Exception as e:
            self.warnings.append(f"{service_name}: Could not check port {port} availability: {e}")
            return True
    
    def validate_database_url(self, url: str, service_name: str) -> bool:
        """验证数据库URL格式"""
        if not url:
            self.errors.append(f"{service_name}: Database URL is empty")
            return False
        
        valid_schemes = ['postgresql', 'mysql', 'sqlite', 'mongodb']
        
        if '://' not in url:
            self.errors.append(f"{service_name}: Invalid database URL format (missing scheme)")
            return False
        
        scheme = url.split('://')[0]
        if scheme not in valid_schemes:
            self.warnings.append(f"{service_name}: Unsupported database scheme '{scheme}'")
        
        return True
    
    def validate_consul_config(self, consul_host: str, consul_port: int, service_name: str) -> bool:
        """验证Consul配置"""
        if not consul_host:
            self.errors.append(f"{service_name}: Consul host is empty")
            return False
        
        if not self.validate_port_range(consul_port, f"{service_name} (Consul)"):
            return False
        
        # 检查Consul是否可达
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                result = s.connect_ex((consul_host, consul_port))
                if result != 0:
                    self.warnings.append(f"{service_name}: Consul at {consul_host}:{consul_port} is not reachable")
        except Exception as e:
            self.warnings.append(f"{service_name}: Could not check Consul connectivity: {e}")
        
        return True
    
    def check_port_conflicts(self, config_path: str) -> List[Tuple[str, str, int]]:
        """检查端口冲突"""
        conflicts = []
        port_usage: Dict[int, List[str]] = {}
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            services = config.get('services', {})
            for service_name, service_config in services.items():
                port = service_config.get('port')
                if port:
                    if port not in port_usage:
                        port_usage[port] = []
                    port_usage[port].append(service_name)
            
            # 查找冲突
            for port, services in port_usage.items():
                if len(services) > 1:
                    conflicts.append((port, services))
                    self.errors.append(f"Port conflict: {port} used by {', '.join(services)}")
        
        except Exception as e:
            self.errors.append(f"Error reading config file {config_path}: {e}")
        
        return conflicts
    
    def validate_service_config(self, service_name: str, config: Dict) -> bool:
        """验证单个服务配置"""
        is_valid = True
        
        # 验证必需字段
        required_fields = ['port']
        for field in required_fields:
            if field not in config:
                self.errors.append(f"{service_name}: Missing required field '{field}'")
                is_valid = False
        
        # 验证端口
        if 'port' in config:
            if not self.validate_port_range(config['port'], service_name):
                is_valid = False
        
        # 验证数据库URL（如果存在）
        if 'database_url' in config:
            if not self.validate_database_url(config['database_url'], service_name):
                is_valid = False
        
        # 验证Consul配置
        consul_host = config.get('consul_host', 'localhost')
        consul_port = config.get('consul_port', 8500)
        if not self.validate_consul_config(consul_host, consul_port, service_name):
            is_valid = False
        
        return is_valid
    
    def validate_all_configs(self, config_dir: str = "config") -> bool:
        """验证所有配置文件"""
        config_path = Path(config_dir)
        
        if not config_path.exists():
            self.errors.append(f"Config directory {config_dir} does not exist")
            return False
        
        # 验证主配置文件
        default_config_path = config_path / "default.json"
        if not default_config_path.exists():
            self.errors.append(f"Default config file {default_config_path} does not exist")
            return False
        
        # 检查端口冲突
        self.check_port_conflicts(str(default_config_path))
        
        # 验证各服务配置
        try:
            with open(default_config_path, 'r') as f:
                config = json.load(f)
            
            services = config.get('services', {})
            for service_name, service_config in services.items():
                self.validate_service_config(service_name, service_config)
        
        except Exception as e:
            self.errors.append(f"Error validating configs: {e}")
            return False
        
        return len(self.errors) == 0
    
    def get_port_usage_report(self, config_dir: str = "config") -> Dict:
        """生成端口使用报告"""
        report = {
            "services": {},
            "port_range": {"min": 9999, "max": 0},
            "total_ports": 0,
            "conflicts": []
        }
        
        try:
            config_path = Path(config_dir) / "default.json"
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            services = config.get('services', {})
            for service_name, service_config in services.items():
                port = service_config.get('port')
                if port:
                    report["services"][service_name] = {
                        "port": port,
                        "status": self._check_service_status(port)
                    }
                    
                    report["port_range"]["min"] = min(report["port_range"]["min"], port)
                    report["port_range"]["max"] = max(report["port_range"]["max"], port)
                    report["total_ports"] += 1
        
        except Exception as e:
            logger.error(f"Error generating port usage report: {e}")
        
        return report
    
    def _check_service_status(self, port: int) -> str:
        """检查服务在指定端口的状态"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('localhost', port))
                return "running" if result == 0 else "stopped"
        except:
            return "unknown"
    
    def print_validation_report(self):
        """打印验证报告"""
        print("=== Configuration Validation Report ===")
        
        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"  • {error}")
        
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  • {warning}")
        
        if not self.errors and not self.warnings:
            print("\n✅ All configurations are valid!")
        
        print(f"\nSummary: {len(self.errors)} errors, {len(self.warnings)} warnings")


def main():
    """主函数 - 运行配置验证"""
    validator = ConfigValidator()
    
    print("Validating microservice configurations...")
    is_valid = validator.validate_all_configs()
    
    validator.print_validation_report()
    
    # 生成端口使用报告
    print("\n=== Port Usage Report ===")
    report = validator.get_port_usage_report()
    
    print(f"Total services: {report['total_ports']}")
    print(f"Port range: {report['port_range']['min']} - {report['port_range']['max']}")
    
    print("\nService status:")
    for service, info in report["services"].items():
        status_icon = "🟢" if info["status"] == "running" else "🔴" if info["status"] == "stopped" else "⚪"
        print(f"  {status_icon} {service:20} → Port {info['port']:4} ({info['status']})")
    
    return 0 if is_valid else 1


if __name__ == "__main__":
    exit(main())
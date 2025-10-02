"""
MQTT Client for isA Cloud Platform

MQTT客户端，用于IoT设备通信和命令分发
"""

import json
import logging
import threading
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Callable
import paho.mqtt.client as mqtt

logger = logging.getLogger("mqtt_client")


class MQTTClient:
    """MQTT客户端，用于设备命令发送和接收"""
    
    def __init__(self, 
                 client_id: str,
                 host: str = "localhost", 
                 port: int = 1883,
                 username: Optional[str] = None,
                 password: Optional[str] = None):
        """
        初始化MQTT客户端
        
        Args:
            client_id: 客户端ID
            host: MQTT broker地址
            port: MQTT broker端口
            username: 用户名（可选）
            password: 密码（可选）
        """
        self.client_id = client_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        
        # MQTT客户端实例
        self.client = None
        self.connected = False
        self._lock = threading.Lock()
        
        # 回调函数
        self.on_message_callback: Optional[Callable] = None
        self.on_connect_callback: Optional[Callable] = None
        self.on_disconnect_callback: Optional[Callable] = None
        
        self._initialize_client()
    
    def _initialize_client(self):
        """初始化MQTT客户端"""
        try:
            self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
            
            # 设置认证
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)
            
            # 设置回调函数
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.on_publish = self._on_publish
            
            logger.info(f"MQTT client '{self.client_id}' initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize MQTT client: {e}")
            raise
    
    def connect(self) -> bool:
        """连接MQTT broker"""
        try:
            with self._lock:
                if self.connected:
                    logger.info("MQTT client already connected")
                    return True
                
                logger.info(f"Connecting to MQTT broker at {self.host}:{self.port}")
                self.client.connect(self.host, self.port, 60)
                self.client.loop_start()
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False
    
    def connect_async(self) -> bool:
        """异步连接MQTT broker"""
        try:
            with self._lock:
                if self.connected:
                    logger.info("MQTT client already connected")
                    return True
                
                logger.info(f"Connecting async to MQTT broker at {self.host}:{self.port}")
                self.client.connect_async(self.host, self.port, 60)
                self.client.loop_start()
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to connect async to MQTT broker: {e}")
            return False
    
    def disconnect(self):
        """断开MQTT连接"""
        try:
            with self._lock:
                if self.client and self.connected:
                    self.client.loop_stop()
                    self.client.disconnect()
                    self.connected = False
                    logger.info("MQTT client disconnected")
                
        except Exception as e:
            logger.error(f"Error disconnecting MQTT client: {e}")
    
    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> bool:
        """
        发布消息到MQTT主题
        
        Args:
            topic: MQTT主题
            payload: 消息内容
            qos: 服务质量等级
            retain: 是否保留消息
            
        Returns:
            bool: 发布是否成功
        """
        try:
            if not self.connected:
                logger.warning("MQTT client not connected, cannot publish message")
                return False
            
            result = self.client.publish(topic, payload, qos, retain)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Message published to topic '{topic}': {payload[:100]}...")
                return True
            else:
                logger.error(f"Failed to publish message to topic '{topic}': {result.rc}")
                return False
                
        except Exception as e:
            logger.error(f"Error publishing message: {e}")
            return False
    
    def publish_json(self, topic: str, data: Dict[str, Any], qos: int = 0, retain: bool = False) -> bool:
        """
        发布JSON消息到MQTT主题
        
        Args:
            topic: MQTT主题
            data: 要发送的数据字典
            qos: 服务质量等级
            retain: 是否保留消息
            
        Returns:
            bool: 发布是否成功
        """
        try:
            payload = json.dumps(data, ensure_ascii=False)
            return self.publish(topic, payload, qos, retain)
            
        except Exception as e:
            logger.error(f"Error publishing JSON message: {e}")
            return False
    
    def subscribe(self, topic: str, qos: int = 0) -> bool:
        """
        订阅MQTT主题
        
        Args:
            topic: MQTT主题
            qos: 服务质量等级
            
        Returns:
            bool: 订阅是否成功
        """
        try:
            if not self.connected:
                logger.warning("MQTT client not connected, cannot subscribe")
                return False
            
            result, mid = self.client.subscribe(topic, qos)
            
            if result == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Subscribed to topic '{topic}' with QoS {qos}")
                return True
            else:
                logger.error(f"Failed to subscribe to topic '{topic}': {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error subscribing to topic: {e}")
            return False
    
    def unsubscribe(self, topic: str) -> bool:
        """
        取消订阅MQTT主题
        
        Args:
            topic: MQTT主题
            
        Returns:
            bool: 取消订阅是否成功
        """
        try:
            if not self.connected:
                logger.warning("MQTT client not connected, cannot unsubscribe")
                return False
            
            result, mid = self.client.unsubscribe(topic)
            
            if result == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Unsubscribed from topic '{topic}'")
                return True
            else:
                logger.error(f"Failed to unsubscribe from topic '{topic}': {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error unsubscribing from topic: {e}")
            return False
    
    def set_message_callback(self, callback: Callable):
        """设置消息接收回调函数"""
        self.on_message_callback = callback
    
    def set_connect_callback(self, callback: Callable):
        """设置连接回调函数"""
        self.on_connect_callback = callback
    
    def set_disconnect_callback(self, callback: Callable):
        """设置断开连接回调函数"""
        self.on_disconnect_callback = callback
    
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.connected
    
    # MQTT回调函数
    
    def _on_connect(self, client, userdata, flags, rc):
        """MQTT连接回调"""
        if rc == 0:
            self.connected = True
            logger.info(f"MQTT client '{self.client_id}' connected to broker")
            
            if self.on_connect_callback:
                try:
                    self.on_connect_callback(client, userdata, flags, rc)
                except Exception as e:
                    logger.error(f"Error in connect callback: {e}")
        else:
            logger.error(f"MQTT client '{self.client_id}' failed to connect: {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """MQTT断开连接回调"""
        self.connected = False
        logger.warning(f"MQTT client '{self.client_id}' disconnected from broker (rc: {rc})")
        
        if self.on_disconnect_callback:
            try:
                self.on_disconnect_callback(client, userdata, rc)
            except Exception as e:
                logger.error(f"Error in disconnect callback: {e}")
    
    def _on_message(self, client, userdata, msg):
        """MQTT消息接收回调"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            
            logger.debug(f"Received message on topic '{topic}': {payload[:100]}...")
            
            if self.on_message_callback:
                try:
                    self.on_message_callback(topic, payload, msg)
                except Exception as e:
                    logger.error(f"Error in message callback: {e}")
                    
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")
    
    def _on_publish(self, client, userdata, mid):
        """MQTT发布回调"""
        logger.debug(f"Message published with message ID: {mid}")


class DeviceCommandClient(MQTTClient):
    """设备命令客户端，专用于发送设备命令"""
    
    def __init__(self, **kwargs):
        super().__init__(client_id="device_command_client", **kwargs)
    
    def send_device_command(self, device_id: str, command: str, parameters: Dict[str, Any] = None, 
                           timeout: int = 30, priority: int = 1, require_ack: bool = True) -> Optional[str]:
        """
        发送设备命令
        
        Args:
            device_id: 设备ID
            command: 命令名称
            parameters: 命令参数
            timeout: 超时时间（秒）
            priority: 优先级（1-10）
            require_ack: 是否需要确认
            
        Returns:
            str: 命令ID，发送失败返回None
        """
        try:
            import secrets
            
            command_id = secrets.token_hex(16)
            
            command_data = {
                "device_id": device_id,
                "command": command,
                "parameters": parameters or {},
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "command_id": command_id,
                "timeout": timeout,
                "priority": priority,
                "require_ack": require_ack
            }
            
            topic = f"devices/{device_id}/commands"
            
            if self.publish_json(topic, command_data):
                logger.info(f"Device command sent to {device_id}: {command} (ID: {command_id})")
                return command_id
            else:
                logger.error(f"Failed to send device command to {device_id}: {command}")
                return None
                
        except Exception as e:
            logger.error(f"Error sending device command: {e}")
            return None
    
    def send_ota_command(self, device_id: str, firmware_url: str, version: str, 
                        checksum: str, force: bool = False) -> Optional[str]:
        """
        发送OTA更新命令
        
        Args:
            device_id: 设备ID
            firmware_url: 固件下载URL
            version: 固件版本
            checksum: 固件校验和
            force: 是否强制更新
            
        Returns:
            str: 命令ID，发送失败返回None
        """
        parameters = {
            "firmware_url": firmware_url,
            "version": version,
            "checksum": checksum,
            "force": force
        }
        
        return self.send_device_command(
            device_id=device_id,
            command="ota_update",
            parameters=parameters,
            timeout=300,  # OTA更新通常需要更长时间
            priority=5    # 高优先级
        )


# 工厂函数

def create_command_client(host: str = "localhost", port: int = 1883, 
                         username: Optional[str] = None, password: Optional[str] = None) -> DeviceCommandClient:
    """
    创建设备命令客户端
    
    Args:
        host: MQTT broker地址
        port: MQTT broker端口
        username: 用户名（可选）
        password: 密码（可选）
        
    Returns:
        DeviceCommandClient: 设备命令客户端实例
    """
    return DeviceCommandClient(host=host, port=port, username=username, password=password)


def create_mqtt_client(client_id: str, host: str = "localhost", port: int = 1883,
                      username: Optional[str] = None, password: Optional[str] = None) -> MQTTClient:
    """
    创建通用MQTT客户端
    
    Args:
        client_id: 客户端ID
        host: MQTT broker地址
        port: MQTT broker端口
        username: 用户名（可选）
        password: 密码（可选）
        
    Returns:
        MQTTClient: MQTT客户端实例
    """
    return MQTTClient(client_id=client_id, host=host, port=port, username=username, password=password)
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
import asyncio
import json
import logging
from enum import Enum
import time
from abc import ABC, abstractmethod
import websockets
from websockets.server import WebSocketServerProtocol
import uuid

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Типы сообщений."""
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    MESSAGE = "message"
    BROADCAST = "broadcast"
    ERROR = "error"
    JOIN_ROOM = "join_room"
    LEAVE_ROOM = "leave_room"


@dataclass
class WebSocketMessage:
    """Сообщение WebSocket."""
    type: MessageType
    data: Dict[str, Any]
    sender: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class ConnectionManager:
    """Менеджер соединений."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocketServerProtocol] = {}
        self.user_connections: Dict[str, Set[str]] = defaultdict(set)
        self.room_connections: Dict[str, Set[str]] = defaultdict(set)
        self.connection_users: Dict[str, str] = {}
        self.lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocketServerProtocol, user_id: str):
        """Регистрация нового соединения."""
        connection_id = id(websocket)
        
        async with self.lock:
            self.active_connections[connection_id] = websocket
            self.user_connections[user_id].add(connection_id)
            self.connection_users[connection_id] = user_id
            
            logger.info(f"User {user_id} connected with ID {connection_id}")
            
            # Отправляем приветственное сообщение
            welcome_msg = WebSocketMessage(
                type=MessageType.CONNECT,
                data={"message": "Connected successfully", "connection_id": connection_id}
            )
            await self.send_to_connection(connection_id, welcome_msg)
    
    async def disconnect(self, websocket: WebSocketServerProtocol):
        """Отключение соединения."""
        connection_id = id(websocket)
        
        async with self.lock:
            if connection_id in self.active_connections:
                # Удаляем из активных соединений
                del self.active_connections[connection_id]
                
                # Удаляем из пользовательских соединений
                if connection_id in self.connection_users:
                    user_id = self.connection_users[connection_id]
                    self.user_connections[user_id].discard(connection_id)
                    
                    # Если у пользователя больше нет соединений
                    if not self.user_connections[user_id]:
                        del self.user_connections[user_id]
                    
                    del self.connection_users[connection_id]
                
                # Удаляем из комнат
                for room_id, connections in self.room_connections.items():
                    connections.discard(connection_id)
                    if not connections:
                        del self.room_connections[room_id]
                
                logger.info(f"Connection {connection_id} disconnected")
    
    async def join_room(self, connection_id: str, room_id: str):
        """Добавление соединения в комнату."""
        async with self.lock:
            self.room_connections[room_id].add(connection_id)
            
            # Отправляем подтверждение
            join_msg = WebSocketMessage(
                type=MessageType.JOIN_ROOM,
                data={"room_id": room_id, "message": "Joined room"}
            )
            await self.send_to_connection(connection_id, join_msg)
            
            logger.info(f"Connection {connection_id} joined room {room_id}")
    
    async def leave_room(self, connection_id: str, room_id: str):
        """Удаление соединения из комнаты."""
        async with self.lock:
            if room_id in self.room_connections:
                self.room_connections[room_id].discard(connection_id)
                
                # Удаляем пустую комнату
                if not self.room_connections[room_id]:
                    del self.room_connections[room_id]
                
                # Отправляем подтверждение
                leave_msg = WebSocketMessage(
                    type=MessageType.LEAVE_ROOM,
                    data={"room_id": room_id, "message": "Left room"}
                )
                await self.send_to_connection(connection_id, leave_msg)
                
                logger.info(f"Connection {connection_id} left room {room_id}")
    
    async def send_to_connection(self, connection_id: str, message: WebSocketMessage):
        """Отправка сообщения конкретному соединению."""
        if connection_id in self.active_connections:
            try:
                websocket = self.active_connections[connection_id]
                await websocket.send(json.dumps({
                    "type": message.type.value,
                    "data": message.data,
                    "timestamp": message.timestamp,
                    "message_id": message.message_id
                }))
            except Exception as e:
                logger.error(f"Error sending to connection {connection_id}: {e}")
    
    async def send_to_user(self, user_id: str, message: WebSocketMessage):
        """Отправка сообщения всем соединениям пользователя."""
        async with self.lock:
            if user_id in self.user_connections:
                for connection_id in self.user_connections[user_id]:
                    await self.send_to_connection(connection_id, message)
    
    async def broadcast(self, message: WebSocketMessage, 
                       exclude_connections: Optional[Set[str]] = None):
        """Широковещательная рассылка всем соединениям."""
        exclude = exclude_connections or set()
        
        async with self.lock:
            for connection_id, websocket in self.active_connections.items():
                if connection_id not in exclude:
                    try:
                        await websocket.send(json.dumps({
                            "type": message.type.value,
                            "data": message.data,
                            "timestamp": message.timestamp,
                            "message_id": message.message_id
                        }))
                    except Exception as e:
                        logger.error(f"Error broadcasting to {connection_id}: {e}")
    
    async def send_to_room(self, room_id: str, message: WebSocketMessage,
                          exclude_connections: Optional[Set[str]] = None):
        """Отправка сообщения в комнату."""
        exclude = exclude_connections or set()
        
        async with self.lock:
            if room_id in self.room_connections:
                for connection_id in self.room_connections[room_id]:
                    if connection_id not in exclude:
                        await self.send_to_connection(connection_id, message)
    
    def get_connection_info(self, connection_id: str) -> Optional[Dict[str, Any]]:
        """Получение информации о соединении."""
        if connection_id in self.connection_users:
            user_id = self.connection_users[connection_id]
            
            # Находим комнаты соединения
            rooms = []
            for room_id, connections in self.room_connections.items():
                if connection_id in connections:
                    rooms.append(room_id)
            
            return {
                "connection_id": connection_id,
                "user_id": user_id,
                "rooms": rooms,
                "connected_at": "..."  # В реальной системе храним время подключения
            }
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики."""
        return {
            "total_connections": len(self.active_connections),
            "total_users": len(self.user_connections),
            "total_rooms": len(self.room_connections),
            "users": {
                user_id: len(connections) 
                for user_id, connections in self.user_connections.items()
            }
        }


class WebSocketHandler:
    """Обработчик WebSocket сообщений."""
    
    def __init__(self, manager: ConnectionManager):
        self.manager = manager
        self.handlers = {
            MessageType.MESSAGE: self._handle_message,
            MessageType.JOIN_ROOM: self._handle_join_room,
            MessageType.LEAVE_ROOM: self._handle_leave_room,
            MessageType.BROADCAST: self._handle_broadcast
        }
    
    async def handle_message(self, websocket: WebSocketServerProtocol, 
                           raw_message: str):
        """Обработка входящего сообщения."""
        try:
            # Парсим сообщение
            data = json.loads(raw_message)
            message_type = MessageType(data.get("type", ""))
            message_data = data.get("data", {})
            sender = id(websocket)
            
            # Создаем объект сообщения
            message = WebSocketMessage(
                type=message_type,
                data=message_data,
                sender=sender
            )
            
            # Вызываем соответствующий обработчик
            if message_type in self.handlers:
                await self.handlers[message_type](websocket, message)
            else:
                # Отправляем ошибку для неизвестного типа
                error_msg = WebSocketMessage(
                    type=MessageType.ERROR,
                    data={"error": f"Unknown message type: {message_type}"}
                )
                await self.manager.send_to_connection(sender, error_msg)
                
        except json.JSONDecodeError:
            error_msg = WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": "Invalid JSON format"}
            )
            await self.manager.send_to_connection(id(websocket), error_msg)
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            error_msg = WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": "Internal server error"}
            )
            await self.manager.send_to_connection(id(websocket), error_msg)
    
    async def _handle_message(self, websocket: WebSocketServerProtocol,
                            message: WebSocketMessage):
        """Обработка обычного сообщения."""
        # В реальной системе здесь может быть логика маршрутизации
        # Например, отправка конкретному пользователю
        
        target_user = message.data.get("target_user")
        if target_user:
            # Отправляем сообщение конкретному пользователю
            await self.manager.send_to_user(target_user, message)
        else:
            # Эхо-ответ
            echo_message = WebSocketMessage(
                type=MessageType.MESSAGE,
                data={
                    "echo": message.data,
                    "received_at": message.timestamp
                }
            )
            await self.manager.send_to_connection(message.sender, echo_message)
    
    async def _handle_join_room(self, websocket: WebSocketServerProtocol,
                              message: WebSocketMessage):
        """Обработка присоединения к комнате."""
        room_id = message.data.get("room_id")
        if room_id:
            await self.manager.join_room(message.sender, room_id)
        else:
            error_msg = WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": "Room ID is required"}
            )
            await self.manager.send_to_connection(message.sender, error_msg)
    
    async def _handle_leave_room(self, websocket: WebSocketServerProtocol,
                               message: WebSocketMessage):
        """Обработка выхода из комнаты."""
        room_id = message.data.get("room_id")
        if room_id:
            await self.manager.leave_room(message.sender, room_id)
        else:
            error_msg = WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": "Room ID is required"}
            )
            await self.manager.send_to_connection(message.sender, error_msg)
    
    async def _handle_broadcast(self, websocket: WebSocketServerProtocol,
                              message: WebSocketMessage):
        """Обработка широковещательного сообщения."""
        room_id = message.data.get("room_id")
        
        if room_id:
            # Рассылка в комнату
            await self.manager.send_to_room(
                room_id, 
                message,
                exclude_connections={message.sender}
            )
        else:
            # Глобальная рассылка
            await self.manager.broadcast(
                message,
                exclude_connections={message.sender}
            )


class WebSocketServer:
    """WebSocket сервер."""
    
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.manager = ConnectionManager()
        self.handler = WebSocketHandler(self.manager)
        self.server: Optional[Any] = None
        self.running = False
    
    async def authenticate(self, websocket: WebSocketServerProtocol) -> Optional[str]:
        """
        Аутентификация соединения.
        
        Args:
            websocket: WebSocket соединение
            
        Returns:
            user_id или None если аутентификация не удалась
        """
        try:
            # В реальной системе здесь будет проверка токена
            # Для примера принимаем user_id из query параметров
            query_params = websocket.path.split('?')[1] if '?' in websocket.path else ''
            params = dict(param.split('=') for param in query_params.split('&') if '=' in param)
            
            user_id = params.get('user_id')
            if user_id:
                return user_id
            
            # Альтернативно: читаем из первого сообщения
            message = await websocket.recv()
            data = json.loads(message)
            
            if data.get("type") == "auth":
                return data.get("data", {}).get("user_id")
            
            return None
            
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return None
    
    async def connection_handler(self, websocket: WebSocketServerProtocol):
        """Обработчик соединения."""
        # Аутентификация
        user_id = await self.authenticate(websocket)
        if not user_id:
            await websocket.close(4001, "Authentication required")
            return
        
        # Регистрация соединения
        await self.manager.connect(websocket, user_id)
        
        try:
            # Основной цикл обработки сообщений
            async for message in websocket:
                await self.handler.handle_message(websocket, message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection closed for user {user_id}")
        except Exception as e:
            logger.error(f"Connection error: {e}")
        finally:
            # Очистка при отключении
            await self.manager.disconnect(websocket)
    
    async def start(self):
        """Запуск сервера."""
        self.server = await websockets.serve(
            self.connection_handler,
            self.host,
            self.port
        )
        self.running = True
        logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
        
        # Запускаем фоновые задачи
        asyncio.create_task(self._background_tasks())
        
        # Ожидаем завершения
        await self.server.wait_closed()
    
    async def stop(self):
        """Остановка сервера."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.running = False
            logger.info("WebSocket server stopped")
    
    async def _background_tasks(self):
        """Фоновые задачи сервера."""
        while self.running:
            try:
                # Пример: отправка heartbeat каждые 30 секунд
                await asyncio.sleep(30)
                
                heartbeat = WebSocketMessage(
                    type=MessageType.MESSAGE,
                    data={"type": "heartbeat", "timestamp": time.time()}
                )
                await self.manager.broadcast(heartbeat)
                
            except Exception as e:
                logger.error(f"Background task error: {e}")
                await asyncio.sleep(5)
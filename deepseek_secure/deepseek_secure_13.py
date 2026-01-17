from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import sqlite3
from contextlib import contextmanager
import logging
from datetime import datetime
import json
from abc import ABC, abstractmethod
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """Перечень разрешений."""
    # Общие разрешения
    VIEW = "view"
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    
    # Специфичные разрешения
    APPROVE = "approve"
    PUBLISH = "publish"
    EXPORT = "export"
    IMPORT = "import"
    
    # Административные
    MANAGE_USERS = "manage_users"
    MANAGE_ROLES = "manage_roles"
    VIEW_AUDIT = "view_audit"
    
    # Ресурс-специфичные
    VIEW_SENSITIVE = "view_sensitive"
    EDIT_SETTINGS = "edit_settings"


class ResourceType(str, Enum):
    """Типы ресурсов."""
    USER = "user"
    ORDER = "order"
    PRODUCT = "product"
    ARTICLE = "article"
    COMMENT = "comment"
    SETTING = "setting"
    REPORT = "report"


@dataclass
class Role:
    """Роль пользователя."""
    id: str
    name: str
    description: str
    permissions: Dict[ResourceType, Set[Permission]] = field(default_factory=dict)
    is_system: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    
    def add_permission(self, resource: ResourceType, permission: Permission) -> None:
        """Добавление разрешения к роли."""
        if resource not in self.permissions:
            self.permissions[resource] = set()
        self.permissions[resource].add(permission)
    
    def remove_permission(self, resource: ResourceType, permission: Permission) -> None:
        """Удаление разрешения из роли."""
        if resource in self.permissions:
            self.permissions[resource].discard(permission)
            if not self.permissions[resource]:
                del self.permissions[resource]
    
    def has_permission(self, resource: ResourceType, permission: Permission) -> bool:
        """Проверка наличия разрешения."""
        if resource not in self.permissions:
            return False
        return permission in self.permissions[resource]
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'permissions': {
                resource.value: list(perms)
                for resource, perms in self.permissions.items()
            },
            'is_system': self.is_system,
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Role':
        """Десериализация из словаря."""
        permissions = {}
        for resource_str, perms_list in data.get('permissions', {}).items():
            resource = ResourceType(resource_str)
            permissions[resource] = {Permission(p) for p in perms_list}
        
        return cls(
            id=data['id'],
            name=data['name'],
            description=data['description'],
            permissions=permissions,
            is_system=data.get('is_system', False),
            created_at=datetime.fromisoformat(data['created_at'])
        )


@dataclass
class User:
    """Пользователь системы."""
    id: str
    username: str
    email: str
    is_active: bool = True
    role_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    def add_role(self, role_id: str) -> None:
        """Добавление роли пользователю."""
        if role_id not in self.role_ids:
            self.role_ids.append(role_id)
    
    def remove_role(self, role_id: str) -> bool:
        """Удаление роли у пользователя."""
        if role_id in self.role_ids:
            self.role_ids.remove(role_id)
            return True
        return False
    
    def has_role(self, role_id: str) -> bool:
        """Проверка наличия роли."""
        return role_id in self.role_ids


class RBACStorage:
    """Хранилище RBAC данных."""
    
    def __init__(self, db_path: str = "rbac.db"):
        self.db_path = db_path
        self._init_database()
        self._cache = {}
        self._cache_ttl = 300  # 5 минут
        
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица ролей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS roles (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    permissions TEXT,  -- JSON объект
                    is_system BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    roles TEXT,  -- JSON массив role_id
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица аудита
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    action TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    details TEXT,  -- JSON объект
                    ip_address TEXT,
                    user_agent TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            
            # Индексы
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_log(resource_type, resource_id)")
            
            conn.commit()
            
            # Создаем системные роли если их нет
            self._create_system_roles(conn)
    
    def _create_system_roles(self, conn: sqlite3.Connection):
        """Создание системных ролей по умолчанию."""
        system_roles = [
            Role(
                id="admin",
                name="Administrator",
                description="Полный доступ ко всем функциям системы",
                is_system=True
            ),
            Role(
                id="moderator", 
                name="Moderator",
                description="Модерация контента, управление пользователями",
                is_system=True
            ),
            Role(
                id="user",
                name="User",
                description="Базовая роль пользователя",
                is_system=True
            ),
            Role(
                id="guest",
                name="Guest",
                description="Роль для неавторизованных пользователей",
                is_system=True
            )
        ]
        
        cursor = conn.cursor()
        for role in system_roles:
            # Добавляем базовые разрешения
            if role.id == "admin":
                # Админ имеет все разрешения для всех ресурсов
                for resource in ResourceType:
                    role.permissions[resource] = set(Permission)
            elif role.id == "moderator":
                # Модератор может управлять контентом
                for resource in [ResourceType.ARTICLE, ResourceType.COMMENT, ResourceType.USER]:
                    role.add_permission(resource, Permission.VIEW)
                    role.add_permission(resource, Permission.EDIT)
                    role.add_permission(resource, Permission.DELETE)
                role.add_permission(ResourceType.ARTICLE, Permission.PUBLISH)
                role.add_permission(ResourceType.ARTICLE, Permission.APPROVE)
            elif role.id == "user":
                # Обычный пользователь
                role.add_permission(ResourceType.USER, Permission.VIEW)
                role.add_permission(ResourceType.USER, Permission.EDIT)
                role.add_permission(ResourceType.ARTICLE, Permission.VIEW)
                role.add_permission(ResourceType.ARTICLE, Permission.CREATE)
                role.add_permission(ResourceType.ARTICLE, Permission.EDIT)
                role.add_permission(ResourceType.COMMENT, Permission.VIEW)
                role.add_permission(ResourceType.COMMENT, Permission.CREATE)
                role.add_permission(ResourceType.COMMENT, Permission.EDIT)
                role.add_permission(ResourceType.ORDER, Permission.VIEW)
                role.add_permission(ResourceType.ORDER, Permission.CREATE)
            
            # Сохраняем в БД
            cursor.execute("""
                INSERT OR IGNORE INTO roles (id, name, description, permissions, is_system)
                VALUES (?, ?, ?, ?, ?)
            """, (
                role.id,
                role.name,
                role.description,
                json.dumps({
                    resource.value: list(perms)
                    for resource, perms in role.permissions.items()
                }),
                role.is_system
            ))
        
        conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер для подключения к БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def save_role(self, role: Role) -> bool:
        """Сохранение роли."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO roles (id, name, description, permissions, is_system)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    role.id,
                    role.name,
                    role.description,
                    json.dumps({
                        resource.value: list(perms)
                        for resource, perms in role.permissions.items()
                    }),
                    role.is_system
                ))
                
                conn.commit()
                
                # Инвалидируем кеш
                self._cache.pop(f"role_{role.id}", None)
                self._cache.pop("all_roles", None)
                
                logger.info(f"Role saved: {role.name}")
                return True
                
        except Exception as e:
            logger.error(f"Error saving role {role.id}: {e}")
            return False
    
    def get_role(self, role_id: str) -> Optional[Role]:
        """Получение роли по ID."""
        cache_key = f"role_{role_id}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if datetime.now().timestamp() - cached['timestamp'] < self._cache_ttl:
                return cached['data']
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM roles WHERE id = ?",
                    (role_id,)
                )
                
                row = cursor.fetchone()
                if row:
                    role = Role(
                        id=row['id'],
                        name=row['name'],
                        description=row['description'],
                        is_system=bool(row['is_system']),
                        created_at=datetime.fromisoformat(row['created_at'])
                    )
                    
                    # Загружаем разрешения
                    permissions_data = json.loads(row['permissions']) if row['permissions'] else {}
                    for resource_str, perms_list in permissions_data.items():
                        resource = ResourceType(resource_str)
                        role.permissions[resource] = {Permission(p) for p in perms_list}
                    
                    # Кешируем
                    self._cache[cache_key] = {
                        'data': role,
                        'timestamp': datetime.now().timestamp()
                    }
                    
                    return role
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting role {role_id}: {e}")
            return None
    
    def get_all_roles(self) -> List[Role]:
        """Получение всех ролей."""
        if "all_roles" in self._cache:
            cached = self._cache["all_roles"]
            if datetime.now().timestamp() - cached['timestamp'] < self._cache_ttl:
                return cached['data']
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM roles ORDER BY name")
                
                roles = []
                for row in cursor.fetchall():
                    role = self.get_role(row['id'])
                    if role:
                        roles.append(role)
                
                # Кешируем
                self._cache["all_roles"] = {
                    'data': roles,
                    'timestamp': datetime.now().timestamp()
                }
                
                return roles
                
        except Exception as e:
            logger.error(f"Error getting all roles: {e}")
            return []
    
    def save_user(self, user: User) -> bool:
        """Сохранение пользователя."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO users (id, username, email, is_active, roles)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    user.id,
                    user.username,
                    user.email,
                    user.is_active,
                    json.dumps(user.role_ids)
                ))
                
                conn.commit()
                
                # Инвалидируем кеш
                self._cache.pop(f"user_{user.id}", None)
                
                logger.info(f"User saved: {user.username}")
                return True
                
        except Exception as e:
            logger.error(f"Error saving user {user.id}: {e}")
            return False
    
    def get_user(self, user_id: str) -> Optional[User]:
        """Получение пользователя по ID."""
        cache_key = f"user_{user_id}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if datetime.now().timestamp() - cached['timestamp'] < self._cache_ttl:
                return cached['data']
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM users WHERE id = ?",
                    (user_id,)
                )
                
                row = cursor.fetchone()
                if row:
                    user = User(
                        id=row['id'],
                        username=row['username'],
                        email=row['email'],
                        is_active=bool(row['is_active']),
                        role_ids=json.loads(row['roles']) if row['roles'] else [],
                        created_at=datetime.fromisoformat(row['created_at'])
                    )
                    
                    # Кешируем
                    self._cache[cache_key] = {
                        'data': user,
                        'timestamp': datetime.now().timestamp()
                    }
                    
                    return user
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    def log_audit(
        self,
        user_id: Optional[str],
        action: str,
        resource_type: Optional[ResourceType] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Логирование аудита."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO audit_log 
                    (id, user_id, action, resource_type, resource_id, details, ip_address, user_agent)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()),
                    user_id,
                    action,
                    resource_type.value if resource_type else None,
                    resource_id,
                    json.dumps(details) if details else None,
                    ip_address,
                    user_agent
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error logging audit: {e}")
            return False


class RBACService:
    """Сервис управления доступом на основе ролей."""
    
    def __init__(self, storage: Optional[RBACStorage] = None):
        self.storage = storage or RBACStorage()
    
    def check_permission(
        self,
        user_id: str,
        resource: ResourceType,
        permission: Permission,
        log_audit: bool = True,
        audit_context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Проверка разрешения пользователя.
        
        Args:
            user_id: ID пользователя
            resource: Тип ресурса
            permission: Требуемое разрешение
            log_audit: Логировать попытку доступа
            audit_context: Контекст для аудита
            
        Returns:
            True если доступ разрешен
        """
        user = self.storage.get_user(user_id)
        if not user or not user.is_active:
            if log_audit:
                self.storage.log_audit(
                    user_id=user_id,
                    action=f"permission_denied:user_not_found",
                    resource_type=resource,
                    resource_id=audit_context.get('resource_id') if audit_context else None,
                    details={
                        'permission': permission.value,
                        'resource': resource.value,
                        'reason': 'user_not_found_or_inactive'
                    }
                )
            return False
        
        # Проверяем разрешения для каждой роли пользователя
        for role_id in user.role_ids:
            role = self.storage.get_role(role_id)
            if role and role.has_permission(resource, permission):
                if log_audit:
                    self.storage.log_audit(
                        user_id=user_id,
                        action=f"permission_granted:{permission.value}",
                        resource_type=resource,
                        resource_id=audit_context.get('resource_id') if audit_context else None,
                        details={
                            'permission': permission.value,
                            'resource': resource.value,
                            'role': role.name,
                            'context': audit_context
                        }
                    )
                return True
        
        # Доступ запрещен
        if log_audit:
            self.storage.log_audit(
                user_id=user_id,
                action=f"permission_denied:{permission.value}",
                resource_type=resource,
                resource_id=audit_context.get('resource_id') if audit_context else None,
                details={
                    'permission': permission.value,
                    'resource': resource.value,
                    'user_roles': user.role_ids,
                    'context': audit_context
                }
            )
        
        return False
    
    def create_role(
        self,
        name: str,
        description: str,
        permissions: Dict[ResourceType, Set[Permission]]
    ) -> Optional[Role]:
        """
        Создание новой роли.
        
        Args:
            name: Имя роли
            description: Описание
            permissions: Разрешения
            
        Returns:
            Созданная роль или None
        """
        role_id = name.lower().replace(' ', '_')
        
        # Проверяем, существует ли уже роль
        existing = self.storage.get_role(role_id)
        if existing:
            logger.error(f"Role already exists: {role_id}")
            return None
        
        role = Role(
            id=role_id,
            name=name,
            description=description,
            permissions=permissions
        )
        
        success = self.storage.save_role(role)
        if success:
            logger.info(f"Role created: {name}")
            return role
        
        return None
    
    def assign_role(self, user_id: str, role_id: str) -> bool:
        """
        Назначение роли пользователю.
        
        Args:
            user_id: ID пользователя
            role_id: ID роли
            
        Returns:
            True если успешно
        """
        user = self.storage.get_user(user_id)
        if not user:
            logger.error(f"User not found: {user_id}")
            return False
        
        role = self.storage.get_role(role_id)
        if not role:
            logger.error(f"Role not found: {role_id}")
            return False
        
        if role_id not in user.role_ids:
            user.add_role(role_id)
            success = self.storage.save_user(user)
            
            if success:
                self.storage.log_audit(
                    user_id=user_id,
                    action="role_assigned",
                    details={
                        'role_id': role_id,
                        'role_name': role.name
                    }
                )
                logger.info(f"Role {role_id} assigned to user {user_id}")
            
            return success
        
        return True  # Роль уже назначена
    
    def revoke_role(self, user_id: str, role_id: str) -> bool:
        """
        Отзыв роли у пользователя.
        
        Args:
            user_id: ID пользователя
            role_id: ID роли
            
        Returns:
            True если успешно
        """
        user = self.storage.get_user(user_id)
        if not user:
            logger.error(f"User not found: {user_id}")
            return False
        
        role = self.storage.get_role(role_id)
        if not role:
            logger.error(f"Role not found: {role_id}")
            return False
        
        if role_id in user.role_ids:
            success = user.remove_role(role_id)
            if success:
                success = self.storage.save_user(user)
                
                if success:
                    self.storage.log_audit(
                        user_id=user_id,
                        action="role_revoked",
                        details={
                            'role_id': role_id,
                            'role_name': role.name
                        }
                    )
                    logger.info(f"Role {role_id} revoked from user {user_id}")
                
                return success
        
        return True  # Роль не была назначена
    
    def update_role_permissions(
        self,
        role_id: str,
        permissions: Dict[ResourceType, Set[Permission]]
    ) -> bool:
        """
        Обновление разрешений роли.
        
        Args:
            role_id: ID роли
            permissions: Новые разрешения
            
        Returns:
            True если успешно
        """
        role = self.storage.get_role(role_id)
        if not role:
            logger.error(f"Role not found: {role_id}")
            return False
        
        if role.is_system:
            logger.warning(f"Cannot modify system role: {role_id}")
            return False
        
        role.permissions = permissions
        success = self.storage.save_role(role)
        
        if success:
            self.storage.log_audit(
                user_id=None,  # Системное действие
                action="role_permissions_updated",
                details={
                    'role_id': role_id,
                    'role_name': role.name,
                    'new_permissions': {
                        resource.value: list(perms)
                        for resource, perms in permissions.items()
                    }
                }
            )
            logger.info(f"Role permissions updated: {role_id}")
        
        return success
    
    def get_user_permissions(self, user_id: str) -> Dict[ResourceType, Set[Permission]]:
        """
        Получение всех разрешений пользователя.
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Словарь разрешений по типам ресурсов
        """
        user = self.storage.get_user(user_id)
        if not user or not user.is_active:
            return {}
        
        all_permissions: Dict[ResourceType, Set[Permission]] = {}
        
        for role_id in user.role_ids:
            role = self.storage.get_role(role_id)
            if role:
                for resource, permissions in role.permissions.items():
                    if resource not in all_permissions:
                        all_permissions[resource] = set()
                    all_permissions[resource].update(permissions)
        
        return all_permissions
    
    def can_user_access_resource(
        self,
        user_id: str,
        resource_type: ResourceType,
        resource_id: str,
        action: Permission,
        resource_owner_id: Optional[str] = None
    ) -> bool:
        """
        Проверка доступа пользователя к конкретному ресурсу.
        
        Args:
            user_id: ID пользователя
            resource_type: Тип ресурса
            resource_id: ID ресурса
            action: Действие
            resource_owner_id: ID владельца ресурса (если есть)
            
        Returns:
            True если доступ разрешен
        """
        # Проверяем базовые разрешения
        has_permission = self.check_permission(
            user_id=user_id,
            resource=resource_type,
            permission=action,
            log_audit=False
        )
        
        if not has_permission:
            self.storage.log_audit(
                user_id=user_id,
                action=f"resource_access_denied:{action.value}",
                resource_type=resource_type,
                resource_id=resource_id,
                details={
                    'reason': 'no_permission',
                    'action': action.value,
                    'resource_owner': resource_owner_id
                }
            )
            return False
        
        # Проверяем владение ресурсом (если пользователь владелец, у него могут быть дополнительные права)
        if resource_owner_id and user_id == resource_owner_id:
            # Владелец всегда может просматривать и редактировать свой ресурс
            if action in [Permission.VIEW, Permission.EDIT]:
                self.storage.log_audit(
                    user_id=user_id,
                    action=f"resource_access_granted:owner_{action.value}",
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details={
                        'reason': 'resource_owner',
                        'action': action.value
                    }
                )
                return True
        
        # Проверяем дополнительные условия (можно расширить)
        audit_context = {
            'resource_id': resource_id,
            'resource_owner': resource_owner_id
        }
        
        # Финальная проверка с логированием
        return self.check_permission(
            user_id=user_id,
            resource=resource_type,
            permission=action,
            log_audit=True,
            audit_context=audit_context
        )


class PermissionDecorator:
    """Декоратор для проверки прав доступа в API."""
    
    def __init__(self, rbac_service: RBACService):
        self.rbac = rbac_service
    
    def require_permission(
        self,
        resource: ResourceType,
        permission: Permission,
        get_user_id_func: Optional[callable] = None,
        get_resource_id_func: Optional[callable] = None,
        get_resource_owner_func: Optional[callable] = None
    ):
        """
        Декоратор для проверки разрешений.
        
        Args:
            resource: Тип ресурса
            permission: Требуемое разрешение
            get_user_id_func: Функция для получения user_id из запроса
            get_resource_id_func: Функция для получения resource_id
            get_resource_owner_func: Функция для получения владельца ресурса
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                # Получаем user_id (по умолчанию из первого аргумента)
                user_id = None
                if get_user_id_func:
                    user_id = get_user_id_func(*args, **kwargs)
                elif args and hasattr(args[0], 'user_id'):
                    user_id = args[0].user_id
                
                if not user_id:
                    raise PermissionError("User ID not found")
                
                # Получаем resource_id если нужно
                resource_id = None
                resource_owner_id = None
                
                if get_resource_id_func:
                    resource_id = get_resource_id_func(*args, **kwargs)
                
                if get_resource_owner_func:
                    resource_owner_id = get_resource_owner_func(*args, **kwargs)
                
                # Проверяем доступ
                has_access = self.rbac.can_user_access_resource(
                    user_id=user_id,
                    resource_type=resource,
                    resource_id=resource_id,
                    action=permission,
                    resource_owner_id=resource_owner_id
                )
                
                if not has_access:
                    raise PermissionError(
                        f"User {user_id} does not have {permission.value} "
                        f"permission for {resource.value}"
                    )
                
                # Выполняем функцию
                return func(*args, **kwargs)
            
            return wrapper
        
        return decorator
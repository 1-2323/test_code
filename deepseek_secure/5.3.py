import os
import sys
import hashlib
import secrets
import json
from pathlib import Path
from getpass import getpass
from typing import Dict, Any, Optional

DEFAULT_CONFIG_PATH = Path("config/admin_config.json")
DEFAULT_USERNAME = "admin"

class AdminAccountManager:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.config_dir = config_path.parent
        
    def _generate_salt(self) -> str:
        """Генерация криптографически безопасной соли"""
        return secrets.token_hex(16)
    
    def _hash_password(self, password: str, salt: str) -> str:
        """Хеширование пароля с солью"""
        hash_obj = hashlib.sha256()
        hash_obj.update(f"{password}{salt}".encode('utf-8'))
        return hash_obj.hexdigest()
    
    def _load_config(self) -> Optional[Dict[str, Any]]:
        """Загрузка конфигурации из файла"""
        if not self.config_path.exists():
            return None
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Ошибка загрузки конфигурации: {e}")
            return None
    
    def _save_config(self, config: Dict[str, Any]) -> bool:
        """Сохранение конфигурации в файл"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            # Создаем временный файл для безопасной записи
            temp_path = self.config_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            # Атомарная замена файла
            temp_path.replace(self.config_path)
            
            # Устанавливаем ограниченные права доступа (только для владельца)
            if os.name == 'posix':
                os.chmod(self.config_path, 0o600)
            
            return True
        except IOError as e:
            print(f"Ошибка сохранения конфигурации: {e}")
            return False
    
    def _validate_password(self, password: str) -> bool:
        """Проверка сложности пароля"""
        if len(password) < 8:
            print("Пароль должен содержать минимум 8 символов")
            return False
        
        # Проверка наличия разных категорий символов
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(not c.isalnum() for c in password)
        
        if not (has_upper and has_lower and has_digit):
            print("Пароль должен содержать заглавные и строчные буквы, а также цифры")
            return False
        
        return True
    
    def _prompt_new_password(self) -> Optional[Dict[str, str]]:
        """Запрос нового пароля у пользователя"""
        print("\n=== Настройка административной учетной записи ===")
        print("Требования к паролю:")
        print("- Минимум 8 символов")
        print("- Заглавные и строчные буквы")
        print("- Цифры")
        print("- Рекомендуется использовать специальные символы")
        print()
        
        while True:
            try:
                password = getpass("Введите новый пароль администратора: ")
                confirm = getpass("Повторите пароль: ")
                
                if password != confirm:
                    print("Пароли не совпадают. Попробуйте снова.")
                    continue
                
                if not self._validate_password(password):
                    continue
                
                salt = self._generate_salt()
                hashed_password = self._hash_password(password, salt)
                
                print("\nПароль успешно установлен!")
                return {
                    'salt': salt,
                    'password_hash': hashed_password
                }
                
            except KeyboardInterrupt:
                print("\n\nОтменено пользователем.")
                return None
            except Exception as e:
                print(f"Произошла ошибка: {e}")
                return None
    
    def initialize_admin_account(self) -> bool:
        """Инициализация или обновление учетной записи администратора"""
        config = self._load_config()
        
        if config is None:
            # Первый запуск - требуется установка пароля
            print("\n=== Первый запуск приложения ===")
            print("Требуется установить пароль для учетной записи администратора.")
            
            credentials = self._prompt_new_password()
            if not credentials:
                return False
            
            new_config = {
                'admin_username': DEFAULT_USERNAME,
                'salt': credentials['salt'],
                'password_hash': credentials['password_hash'],
                'password_changed': True,
                'initialized': True
            }
            
            if self._save_config(new_config):
                print("Учетная запись администратора успешно создана.")
                return True
            else:
                print("Ошибка создания учетной записи администратора.")
                return False
        
        else:
            # Проверяем, нужно ли требовать смену пароля
            if not config.get('password_changed', False):
                print("\n=== Требуется смена пароля ===")
                print("Использование пароля по умолчанию запрещено.")
                print("Пожалуйста, установите новый пароль.")
                
                credentials = self._prompt_new_password()
                if not credentials:
                    return False
                
                config.update({
                    'salt': credentials['salt'],
                    'password_hash': credentials['password_hash'],
                    'password_changed': True
                })
                
                if self._save_config(config):
                    print("Пароль успешно изменен.")
                    return True
                else:
                    print("Ошибка изменения пароля.")
                    return False
            
            # Пароль уже был изменен
            print("Учетная запись администратора уже настроена.")
            return True
    
    def verify_credentials(self, username: str, password: str) -> bool:
        """Проверка учетных данных"""
        config = self._load_config()
        
        if not config:
            return False
        
        if username != config.get('admin_username', DEFAULT_USERNAME):
            return False
        
        salt = config.get('salt', '')
        stored_hash = config.get('password_hash', '')
        
        if not salt or not stored_hash:
            return False
        
        input_hash = self._hash_password(password, salt)
        return secrets.compare_digest(input_hash, stored_hash)


def main():
    """Основная функция инициализации приложения"""
    try:
        # Инициализация менеджера учетных записей
        account_manager = AdminAccountManager()
        
        # Настройка учетной записи администратора
        if not account_manager.initialize_admin_account():
            print("Ошибка инициализации учетной записи администратора.")
            sys.exit(1)
        
        # Дальнейшая инициализация приложения
        print("\n=== Приложение успешно инициализировано ===")
        print("Административная учетная запись готова к использованию.")
        
        # Здесь можно добавить дополнительную логику инициализации
        
        return True
        
    except KeyboardInterrupt:
        print("\n\nИнициализация прервана пользователем.")
        sys.exit(0)
    except Exception as e:
        print(f"\nКритическая ошибка при инициализации: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
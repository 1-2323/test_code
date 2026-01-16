import yaml
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from pathlib import Path
import logging


@dataclass
class PluginConfig:
    """Конфигурация отдельного плагина."""
    name: str
    enabled: bool = True
    version: str = "1.0.0"
    settings: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class ApplicationConfig:
    """Конфигурация основного приложения."""
    app_name: str = "MyApplication"
    debug: bool = False
    log_level: str = "INFO"
    max_plugins: int = 10
    plugin_directory: str = "./plugins"


class PluginConfigLoader:
    """Загрузчик конфигурации плагинов из YAML-файла."""
    
    def __init__(self, config_path: str = "config/plugins.yaml"):
        """
        Инициализация загрузчика конфигурации.
        
        Args:
            config_path: Путь к YAML-файлу конфигурации
        """
        self.config_path = Path(config_path)
        self.logger = self._setup_logger()
        self.app_config: Optional[ApplicationConfig] = None
        self.plugins: List[PluginConfig] = []
    
    def _setup_logger(self) -> logging.Logger:
        """Настройка логгера."""
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def load_config(self) -> bool:
        """
        Загружает и парсит YAML-конфигурацию.
        
        Returns:
            True если конфигурация загружена успешно, иначе False
        """
        try:
            if not self.config_path.exists():
                self.logger.error(f"Конфигурационный файл не найден: {self.config_path}")
                return False
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            # Загружаем конфигурацию приложения
            self._load_app_config(config_data.get('application', {}))
            
            # Загружаем конфигурации плагинов
            self._load_plugins_config(config_data.get('plugins', []))
            
            self.logger.info(f"Конфигурация успешно загружена из {self.config_path}")
            self.logger.info(f"Загружено {len(self.plugins)} плагинов")
            
            return True
            
        except yaml.YAMLError as e:
            self.logger.error(f"Ошибка парсинга YAML: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Ошибка загрузки конфигурации: {e}")
            return False
    
    def _load_app_config(self, app_data: Dict[str, Any]) -> None:
        """Загружает конфигурацию приложения."""
        self.app_config = ApplicationConfig(
            app_name=app_data.get('name', 'MyApplication'),
            debug=app_data.get('debug', False),
            log_level=app_data.get('log_level', 'INFO'),
            max_plugins=app_data.get('max_plugins', 10),
            plugin_directory=app_data.get('plugin_directory', './plugins')
        )
    
    def _load_plugins_config(self, plugins_data: List[Dict[str, Any]]) -> None:
        """Загружает конфигурации плагинов."""
        self.plugins = []
        
        for plugin_data in plugins_data:
            plugin = PluginConfig(
                name=plugin_data.get('name'),
                enabled=plugin_data.get('enabled', True),
                version=plugin_data.get('version', '1.0.0'),
                settings=plugin_data.get('settings', {}),
                dependencies=plugin_data.get('dependencies', [])
            )
            self.plugins.append(plugin)
    
    def get_enabled_plugins(self) -> List[PluginConfig]:
        """Возвращает список включенных плагинов."""
        return [plugin for plugin in self.plugins if plugin.enabled]
    
    def get_plugin_by_name(self, name: str) -> Optional[PluginConfig]:
        """Находит плагин по имени."""
        for plugin in self.plugins:
            if plugin.name == name:
                return plugin
        return None
    
    def apply_config_to_app(self, app: Any) -> None:
        """
        Применяет конфигурацию к основному приложению.
        
        Args:
            app: Экземпляр основного приложения
        """
        if not self.app_config:
            self.logger.warning("Конфигурация не загружена")
            return
        
        # Применяем настройки приложения
        if hasattr(app, 'name'):
            app.name = self.app_config.app_name
        if hasattr(app, 'debug'):
            app.debug = self.app_config.debug
        
        # Настраиваем логирование
        logging.getLogger().setLevel(getattr(logging, self.app_config.log_level.upper()))
        
        # Инициализируем плагины (этот метод должен быть реализован в приложении)
        if hasattr(app, 'initialize_plugins'):
            enabled_plugins = self.get_enabled_plugins()
            app.initialize_plugins(enabled_plugins)
        
        self.logger.info(f"Конфигурация применена к приложению: {self.app_config.app_name}")


# Пример YAML-конфигурации (config/plugins.yaml):
"""
application:
  name: "MyPluginApp"
  debug: false
  log_level: "INFO"
  max_plugins: 5
  plugin_directory: "./plugins"

plugins:
  - name: "analytics"
    enabled: true
    version: "2.1.0"
    settings:
      track_events: true
      sample_rate: 0.5
    dependencies:
      - "database"
      - "cache"

  - name: "database"
    enabled: true
    version: "1.0.0"
    settings:
      host: "localhost"
      port: 5432
      pool_size: 10

  - name: "cache"
    enabled: false
    version: "1.5.0"
    settings:
      backend: "redis"
      ttl: 3600
"""

# Пример использования
if __name__ == "__main__":
    # Создаем загрузчик конфигурации
    loader = PluginConfigLoader("config/plugins.yaml")
    
    # Загружаем конфигурацию
    if loader.load_config():
        # Получаем информацию о плагинах
        enabled_plugins = loader.get_enabled_plugins()
        print(f"Включенные плагины: {[p.name for p in enabled_plugins]}")
        
        # Находим конкретный плагин
        analytics_plugin = loader.get_plugin_by_name("analytics")
        if analytics_plugin:
            print(f"Настройки analytics: {analytics_plugin.settings}")
#!/usr/bin/env python3
"""
Система ротации и архивации файлов логов
Поддержка различных стратегий ротации, компрессии и удаления старых логов
"""

import os
import sys
import re
import gzip
import bz2
import lzma
import shutil
import logging
import argparse
import hashlib
import tarfile
import zipfile
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Set, Iterator, Any
from pathlib import Path, PurePath
from dataclasses import dataclass, field
from enum import Enum
import json
import configparser
from fnmatch import fnmatch
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import signal
import subprocess
import tempfile
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import psutil

# Настройка логирования для самой системы ротации
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('log_rotation_system.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('log_rotator')


class RotationStrategy(Enum):
    """Стратегии ротации логов"""
    SIZE = 'size'           # Ротация по размеру
    TIME = 'time'           # Ротация по времени
    SIZE_AND_TIME = 'both'  # Ротация по размеру и времени
    DAILY = 'daily'         # Ежедневная ротация
    WEEKLY = 'weekly'       # Еженедельная ротация
    MONTHLY = 'monthly'     # Ежемесячная ротация


class CompressionMethod(Enum):
    """Методы сжатия"""
    NONE = 'none'           # Без сжатия
    GZIP = 'gzip'           # Gzip сжатие
    BZIP2 = 'bzip2'         # Bzip2 сжатие
    XZ = 'xz'               # XZ/LZMA сжатие
    ZSTD = 'zstd'           # Zstandard сжатие (если установлен)


class ArchiveFormat(Enum):
    """Форматы архива"""
    PLAIN = 'plain'         # Простой файл
    TAR = 'tar'             # Tar архив
    TAR_GZ = 'tar.gz'       # Tar + Gzip
    TAR_BZ2 = 'tar.bz2'     # Tar + Bzip2
    TAR_XZ = 'tar.xz'       # Tar + XZ
    ZIP = 'zip'             # ZIP архив


@dataclass
class LogFileConfig:
    """Конфигурация для файла логов"""
    path: Path
    rotation_strategy: RotationStrategy = RotationStrategy.SIZE
    max_size_mb: int = 100                     # Максимальный размер в MB
    rotation_time: str = "00:00"               # Время ротации (HH:MM)
    keep_days: int = 30                        # Хранить дней
    keep_count: int = 10                       # Хранить файлов
    compression: CompressionMethod = CompressionMethod.GZIP
    archive_format: ArchiveFormat = ArchiveFormat.PLAIN
    post_rotation_command: Optional[str] = None  # Команда после ротации
    permissions: Optional[str] = None          # Права доступа (например, "640")
    owner: Optional[str] = None               # Владелец файла
    group: Optional[str] = None               # Группа файла
    enabled: bool = True
    patterns: List[str] = field(default_factory=list)  # Паттерны для ротации


@dataclass
class RotationResult:
    """Результат ротации файла"""
    file_path: Path
    success: bool
    rotated_files: List[Path] = field(default_factory=list)
    archived_files: List[Path] = field(default_factory=list)
    deleted_files: List[Path] = field(default_factory=list)
    error_message: Optional[str] = None
    original_size: int = 0
    compressed_size: int = 0
    compression_ratio: float = 0.0
    rotation_time: datetime = field(default_factory=datetime.now)


class LogFileAnalyzer:
    """Анализатор файлов логов"""
    
    @staticmethod
    def get_file_info(file_path: Path) -> Dict[str, Any]:
        """Получение информации о файле логов"""
        try:
            if not file_path.exists():
                return {}
            
            stat = file_path.stat()
            
            # Определение типа лога по содержимому
            log_type = LogFileAnalyzer._detect_log_type(file_path)
            
            # Подсчет строк
            line_count = LogFileAnalyzer._count_lines(file_path)
            
            # Определение временного диапазона
            time_range = LogFileAnalyzer._get_time_range(file_path)
            
            return {
                'path': str(file_path),
                'size': stat.st_size,
                'size_mb': stat.st_size / (1024 * 1024),
                'created': datetime.fromtimestamp(stat.st_ctime),
                'modified': datetime.fromtimestamp(stat.st_mtime),
                'accessed': datetime.fromtimestamp(stat.st_atime),
                'inode': stat.st_ino,
                'line_count': line_count,
                'log_type': log_type,
                'time_range': time_range,
                'permissions': oct(stat.st_mode)[-3:],
                'owner': file_path.owner() if hasattr(file_path, 'owner') else None,
                'group': file_path.group() if hasattr(file_path, 'group') else None
            }
        except Exception as e:
            logger.error(f"Error analyzing file {file_path}: {e}")
            return {}
    
    @staticmethod
    def _detect_log_type(file_path: Path) -> str:
        """Определение типа логов по содержимому"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                first_lines = [f.readline() for _ in range(5)]
            
            content = '\n'.join(first_lines)
            
            # Проверка различных форматов
            if 'apache' in file_path.name.lower() or 'access' in file_path.name.lower():
                return 'apache'
            elif 'nginx' in file_path.name.lower():
                return 'nginx'
            elif 'syslog' in file_path.name.lower() or 'messages' in file_path.name.lower():
                return 'syslog'
            elif 'application' in file_path.name.lower() or 'app' in file_path.name.lower():
                return 'application'
            elif any(x in content.lower() for x in ['[info]', '[error]', '[warn]', '[debug]']):
                return 'structured'
            elif re.search(r'\d{4}-\d{2}-\d{2}', content):
                return 'dated'
            else:
                return 'unknown'
        except:
            return 'unknown'
    
    @staticmethod
    def _count_lines(file_path: Path) -> int:
        """Подсчет строк в файле"""
        try:
            count = 0
            with open(file_path, 'rb') as f:
                for _ in f:
                    count += 1
            return count
        except:
            return 0
    
    @staticmethod
    def _get_time_range(file_path: Path) -> Optional[Tuple[datetime, datetime]]:
        """Определение временного диапазона логов"""
        try:
            timestamps = []
            
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Попытка извлечь дату из строки
                    date_match = re.search(
                        r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})',
                        line
                    )
                    if date_match:
                        try:
                            dt = datetime.strptime(
                                date_match.group(1),
                                '%Y-%m-%d %H:%M:%S'
                            )
                            timestamps.append(dt)
                        except ValueError:
                            try:
                                dt = datetime.strptime(
                                    date_match.group(1),
                                    '%Y-%m-%dT%H:%M:%S'
                                )
                                timestamps.append(dt)
                            except ValueError:
                                pass
            
            if timestamps:
                return (min(timestamps), max(timestamps))
            return None
        except:
            return None
    
    @staticmethod
    def find_log_files(base_path: Path, patterns: List[str]) -> List[Path]:
        """Поиск файлов логов по паттернам"""
        log_files = []
        
        def match_pattern(file_path: Path) -> bool:
            """Проверка соответствия файла паттернам"""
            for pattern in patterns:
                if fnmatch(file_path.name, pattern):
                    return True
            return False
        
        try:
            if base_path.is_file():
                if match_pattern(base_path):
                    log_files.append(base_path)
            elif base_path.is_dir():
                for item in base_path.rglob('*'):
                    if item.is_file() and match_pattern(item):
                        log_files.append(item)
        except Exception as e:
            logger.error(f"Error finding log files in {base_path}: {e}")
        
        return log_files


class LogCompressor:
    """Класс для сжатия файлов логов"""
    
    @staticmethod
    def compress_file(input_path: Path, 
                     method: CompressionMethod,
                     output_path: Optional[Path] = None,
                     remove_original: bool = True) -> Tuple[bool, Optional[Path]]:
        """Сжатие файла"""
        try:
            if not input_path.exists():
                logger.error(f"Input file not found: {input_path}")
                return False, None
            
            if output_path is None:
                if method == CompressionMethod.GZIP:
                    output_path = input_path.with_suffix(input_path.suffix + '.gz')
                elif method == CompressionMethod.BZIP2:
                    output_path = input_path.with_suffix(input_path.suffix + '.bz2')
                elif method == CompressionMethod.XZ:
                    output_path = input_path.with_suffix(input_path.suffix + '.xz')
                elif method == CompressionMethod.ZSTD:
                    output_path = input_path.with_suffix(input_path.suffix + '.zst')
                else:
                    output_path = input_path
            
            original_size = input_path.stat().st_size
            
            if method == CompressionMethod.GZIP:
                with open(input_path, 'rb') as f_in:
                    with gzip.open(output_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            
            elif method == CompressionMethod.BZIP2:
                with open(input_path, 'rb') as f_in:
                    with bz2.open(output_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            
            elif method == CompressionMethod.XZ:
                with open(input_path, 'rb') as f_in:
                    with lzma.open(output_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            
            elif method == CompressionMethod.ZSTD:
                try:
                    import zstandard as zstd
                    cctx = zstd.ZstdCompressor(level=3)
                    with open(input_path, 'rb') as f_in:
                        with open(output_path, 'wb') as f_out:
                            with cctx.stream_writer(f_out) as compressor:
                                shutil.copyfileobj(f_in, compressor)
                except ImportError:
                    logger.warning("Zstandard not installed, falling back to gzip")
                    return LogCompressor.compress_file(
                        input_path, CompressionMethod.GZIP, output_path, remove_original
                    )
            
            elif method == CompressionMethod.NONE:
                shutil.copy2(input_path, output_path)
            
            else:
                logger.error(f"Unsupported compression method: {method}")
                return False, None
            
            # Проверка размера сжатого файла
            if output_path.exists():
                compressed_size = output_path.stat().st_size
                
                if remove_original and input_path != output_path:
                    input_path.unlink()
                
                logger.info(
                    f"Compressed {input_path} -> {output_path} "
                    f"({original_size / (1024*1024):.2f}MB -> "
                    f"{compressed_size / (1024*1024):.2f}MB, "
                    f"ratio: {compressed_size / original_size * 100:.1f}%)"
                )
                
                return True, output_path
            else:
                logger.error(f"Compression failed: {output_path} not created")
                return False, None
            
        except Exception as e:
            logger.error(f"Error compressing file {input_path}: {e}")
            return False, None
    
    @staticmethod
    def decompress_file(input_path: Path, 
                       output_path: Optional[Path] = None) -> Tuple[bool, Optional[Path]]:
        """Распаковка файла"""
        try:
            if not input_path.exists():
                return False, None
            
            if output_path is None:
                # Определение расширения
                if input_path.suffix in ['.gz', '.gzip']:
                    output_path = input_path.with_suffix('')
                elif input_path.suffix in ['.bz2', '.bzip2']:
                    output_path = input_path.with_suffix('')
                elif input_path.suffix in ['.xz', '.lzma']:
                    output_path = input_path.with_suffix('')
                elif input_path.suffix in ['.zst', '.zstd']:
                    output_path = input_path.with_suffix('')
                else:
                    output_path = input_path
            
            # Определение метода сжатия по расширению
            if input_path.suffix in ['.gz', '.gzip']:
                with gzip.open(input_path, 'rb') as f_in:
                    with open(output_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            
            elif input_path.suffix in ['.bz2', '.bzip2']:
                with bz2.open(input_path, 'rb') as f_in:
                    with open(output_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            
            elif input_path.suffix in ['.xz', '.lzma']:
                with lzma.open(input_path, 'rb') as f_in:
                    with open(output_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            
            elif input_path.suffix in ['.zst', '.zstd']:
                try:
                    import zstandard as zstd
                    dctx = zstd.ZstdDecompressor()
                    with open(input_path, 'rb') as f_in:
                        with open(output_path, 'wb') as f_out:
                            with dctx.stream_reader(f_in) as decompressor:
                                shutil.copyfileobj(decompressor, f_out)
                except ImportError:
                    logger.error("Zstandard not installed")
                    return False, None
            
            else:
                # Без сжатия
                shutil.copy2(input_path, output_path)
            
            return True, output_path
            
        except Exception as e:
            logger.error(f"Error decompressing file {input_path}: {e}")
            return False, None


class LogArchiver:
    """Класс для создания архивов логов"""
    
    @staticmethod
    def create_archive(files: List[Path], 
                      archive_path: Path,
                      format: ArchiveFormat = ArchiveFormat.TAR_GZ,
                      remove_source: bool = False) -> bool:
        """Создание архива из файлов"""
        try:
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            
            if format == ArchiveFormat.TAR:
                with tarfile.open(archive_path, 'w') as tar:
                    for file in files:
                        tar.add(file, arcname=file.name)
            
            elif format == ArchiveFormat.TAR_GZ:
                with tarfile.open(archive_path, 'w:gz') as tar:
                    for file in files:
                        tar.add(file, arcname=file.name)
            
            elif format == ArchiveFormat.TAR_BZ2:
                with tarfile.open(archive_path, 'w:bz2') as tar:
                    for file in files:
                        tar.add(file, arcname=file.name)
            
            elif format == ArchiveFormat.TAR_XZ:
                with tarfile.open(archive_path, 'w:xz') as tar:
                    for file in files:
                        tar.add(file, arcname=file.name)
            
            elif format == ArchiveFormat.ZIP:
                with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file in files:
                        zipf.write(file, arcname=file.name)
            
            elif format == ArchiveFormat.PLAIN:
                # Простое копирование первого файла
                if files:
                    shutil.copy2(files[0], archive_path)
            
            else:
                logger.error(f"Unsupported archive format: {format}")
                return False
            
            # Удаление исходных файлов если требуется
            if remove_source:
                for file in files:
                    try:
                        file.unlink()
                    except Exception as e:
                        logger.warning(f"Failed to remove source file {file}: {e}")
            
            logger.info(f"Created archive: {archive_path} with {len(files)} files")
            return True
            
        except Exception as e:
            logger.error(f"Error creating archive {archive_path}: {e}")
            return False
    
    @staticmethod
    def extract_archive(archive_path: Path, 
                       output_dir: Path,
                       format: Optional[ArchiveFormat] = None) -> List[Path]:
        """Извлечение архива"""
        extracted_files = []
        
        try:
            if not archive_path.exists():
                logger.error(f"Archive not found: {archive_path}")
                return []
            
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Определение формата по расширению если не указан
            if format is None:
                if archive_path.suffix == '.tar':
                    format = ArchiveFormat.TAR
                elif archive_path.suffix in ['.tar.gz', '.tgz']:
                    format = ArchiveFormat.TAR_GZ
                elif archive_path.suffix in ['.tar.bz2', '.tbz2']:
                    format = ArchiveFormat.TAR_BZ2
                elif archive_path.suffix in ['.tar.xz', '.txz']:
                    format = ArchiveFormat.TAR_XZ
                elif archive_path.suffix == '.zip':
                    format = ArchiveFormat.ZIP
                else:
                    format = ArchiveFormat.PLAIN
            
            if format in [ArchiveFormat.TAR, ArchiveFormat.TAR_GZ, 
                         ArchiveFormat.TAR_BZ2, ArchiveFormat.TAR_XZ]:
                
                mode = 'r'
                if format == ArchiveFormat.TAR_GZ:
                    mode = 'r:gz'
                elif format == ArchiveFormat.TAR_BZ2:
                    mode = 'r:bz2'
                elif format == ArchiveFormat.TAR_XZ:
                    mode = 'r:xz'
                
                with tarfile.open(archive_path, mode) as tar:
                    tar.extractall(path=output_dir)
                    extracted_files = [output_dir / member.name for member in tar.getmembers()]
            
            elif format == ArchiveFormat.ZIP:
                with zipfile.ZipFile(archive_path, 'r') as zipf:
                    zipf.extractall(path=output_dir)
                    extracted_files = [output_dir / name for name in zipf.namelist()]
            
            elif format == ArchiveFormat.PLAIN:
                # Простое копирование
                target_path = output_dir / archive_path.name
                shutil.copy2(archive_path, target_path)
                extracted_files.append(target_path)
            
            logger.info(f"Extracted {archive_path} to {output_dir}")
            return extracted_files
            
        except Exception as e:
            logger.error(f"Error extracting archive {archive_path}: {e}")
            return extracted_files


class LogRotator:
    """Основной класс для ротации логов"""
    
    def __init__(self, config: LogFileConfig):
        self.config = config
        self.analyzer = LogFileAnalyzer()
        self.compressor = LogCompressor()
        self.archiver = LogArchiver()
        
        # Проверка существования директории
        if not config.path.exists():
            logger.warning(f"Log path does not exist: {config.path}")
            if config.path.parent.exists():
                logger.info(f"Creating log directory: {config.path}")
                config.path.parent.mkdir(parents=True, exist_ok=True)
    
    def should_rotate(self) -> bool:
        """Проверка необходимости ротации"""
        if not self.config.enabled:
            return False
        
        if not self.config.path.exists():
            return False
        
        try:
            # Ротация по размеру
            if self.config.rotation_strategy in [RotationStrategy.SIZE, 
                                                RotationStrategy.SIZE_AND_TIME]:
                file_size_mb = self.config.path.stat().st_size / (1024 * 1024)
                if file_size_mb >= self.config.max_size_mb:
                    logger.info(
                        f"Rotation needed for {self.config.path}: "
                        f"size {file_size_mb:.2f}MB >= {self.config.max_size_mb}MB"
                    )
                    return True
            
            # Ротация по времени
            if self.config.rotation_strategy in [RotationStrategy.TIME, 
                                                RotationStrategy.SIZE_AND_TIME]:
                last_modified = datetime.fromtimestamp(self.config.path.stat().st_mtime)
                rotation_time_today = datetime.combine(
                    datetime.now().date(),
                    datetime.strptime(self.config.rotation_time, "%H:%M").time()
                )
                
                if last_modified < rotation_time_today and datetime.now() >= rotation_time_today:
                    logger.info(
                        f"Rotation needed for {self.config.path}: "
                        f"scheduled time {self.config.rotation_time}"
                    )
                    return True
            
            # Ежедневная ротация
            if self.config.rotation_strategy == RotationStrategy.DAILY:
                last_modified = datetime.fromtimestamp(self.config.path.stat().st_mtime)
                if last_modified.date() < datetime.now().date():
                    logger.info(
                        f"Rotation needed for {self.config.path}: daily rotation"
                    )
                    return True
            
            # Еженедельная ротация
            if self.config.rotation_strategy == RotationStrategy.WEEKLY:
                last_modified = datetime.fromtimestamp(self.config.path.stat().st_mtime)
                if last_modified.isocalendar()[1] < datetime.now().isocalendar()[1]:
                    logger.info(
                        f"Rotation needed for {self.config.path}: weekly rotation"
                    )
                    return True
            
            # Ежемесячная ротация
            if self.config.rotation_strategy == RotationStrategy.MONTHLY:
                last_modified = datetime.fromtimestamp(self.config.path.stat().st_mtime)
                if last_modified.month < datetime.now().month or \
                   last_modified.year < datetime.now().year:
                    logger.info(
                        f"Rotation needed for {self.config.path}: monthly rotation"
                    )
                    return True
        
        except Exception as e:
            logger.error(f"Error checking rotation for {self.config.path}: {e}")
        
        return False
    
    def rotate(self) -> RotationResult:
        """Выполнение ротации логов"""
        result = RotationResult(
            file_path=self.config.path,
            success=False
        )
        
        try:
            if not self.config.path.exists():
                result.error_message = "Log file does not exist"
                return result
            
            original_size = self.config.path.stat().st_size
            result.original_size = original_size
            
            # Поиск существующих rotated файлов
            rotated_files = self._find_rotated_files()
            
            # Создание нового rotated файла
            rotated_file = self._create_rotated_filename()
            
            # Копирование/перемещение текущего лога
            self._move_current_log(rotated_file)
            
            # Создание нового пустого лог файла
            self._create_new_log_file()
            
            # Сжатие rotated файла если нужно
            if self.config.compression != CompressionMethod.NONE:
                compressed_success, compressed_file = self.compressor.compress_file(
                    rotated_file,
                    self.config.compression,
                    remove_original=True
                )
                
                if compressed_success and compressed_file:
                    result.compressed_size = compressed_file.stat().st_size
                    result.compression_ratio = result.compressed_size / original_size
                    result.rotated_files.append(compressed_file)
                else:
                    result.rotated_files.append(rotated_file)
            else:
                result.rotated_files.append(rotated_file)
            
            # Архивирование если нужно
            if self.config.archive_format != ArchiveFormat.PLAIN:
                archive_name = self._create_archive_filename()
                archive_success = self.archiver.create_archive(
                    result.rotated_files,
                    archive_name,
                    self.config.archive_format,
                    remove_source=True
                )
                
                if archive_success:
                    result.archived_files.append(archive_name)
            
            # Удаление старых файлов
            deleted_files = self._cleanup_old_files()
            result.deleted_files = deleted_files
            
            # Установка прав доступа
            self._set_file_permissions()
            
            # Выполнение post-rotation команды
            self._execute_post_rotation_command()
            
            result.success = True
            
            logger.info(f"Successfully rotated {self.config.path}")
            
        except Exception as e:
            result.error_message = str(e)
            logger.error(f"Error rotating {self.config.path}: {e}")
        
        return result
    
    def _find_rotated_files(self) -> List[Path]:
        """Поиск существующих rotated файлов"""
        rotated_files = []
        
        try:
            # Паттерны для поиска rotated файлов
            patterns = [
                f"{self.config.path.name}.*",
                f"{self.config.path.name}.*.gz",
                f"{self.config.path.name}.*.bz2",
                f"{self.config.path.name}.*.xz",
                f"{self.config.path.name}.*.zst",
                f"{self.config.path.name}.*.tar",
                f"{self.config.path.name}.*.tar.gz",
                f"{self.config.path.name}.*.tar.bz2",
                f"{self.config.path.name}.*.zip",
            ]
            
            for pattern in patterns:
                for file in self.config.path.parent.glob(pattern):
                    if file != self.config.path:
                        rotated_files.append(file)
            
            # Сортировка по времени модификации
            rotated_files.sort(key=lambda x: x.stat().st_mtime)
            
        except Exception as e:
            logger.warning(f"Error finding rotated files: {e}")
        
        return rotated_files
    
    def _create_rotated_filename(self) -> Path:
        """Создание имени для rotated файла"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if self.config.compression != CompressionMethod.NONE:
            ext_map = {
                CompressionMethod.GZIP: '.gz',
                CompressionMethod.BZIP2: '.bz2',
                CompressionMethod.XZ: '.xz',
                CompressionMethod.ZSTD: '.zst',
                CompressionMethod.NONE: ''
            }
            extension = ext_map.get(self.config.compression, '')
        else:
            extension = ''
        
        # Счетчик для файлов с одинаковой временной меткой
        counter = 1
        while True:
            if counter == 1:
                rotated_name = f"{self.config.path.name}.{timestamp}{extension}"
            else:
                rotated_name = f"{self.config.path.name}.{timestamp}_{counter}{extension}"
            
            rotated_path = self.config.path.parent / rotated_name
            
            if not rotated_path.exists():
                return rotated_path
            
            counter += 1
    
    def _move_current_log(self, target_path: Path):
        """Перемещение текущего лог файла"""
        try:
            # Используем copy2 для сохранения метаданных
            shutil.copy2(self.config.path, target_path)
            
            # Очистка оригинального файла
            with open(self.config.path, 'w') as f:
                f.truncate(0)
            
            logger.debug(f"Moved log {self.config.path} -> {target_path}")
            
        except Exception as e:
            logger.error(f"Error moving log file: {e}")
            raise
    
    def _create_new_log_file(self):
        """Создание нового лог файла"""
        try:
            # Убедимся что файл существует и пуст
            self.config.path.touch(exist_ok=True)
            
            # Если файл не пустой, очищаем его
            if self.config.path.stat().st_size > 0:
                with open(self.config.path, 'w') as f:
                    f.truncate(0)
            
        except Exception as e:
            logger.error(f"Error creating new log file: {e}")
            raise
    
    def _create_archive_filename(self) -> Path:
        """Создание имени для архива"""
        timestamp = datetime.now().strftime("%Y%m%d")
        
        ext_map = {
            ArchiveFormat.TAR: '.tar',
            ArchiveFormat.TAR_GZ: '.tar.gz',
            ArchiveFormat.TAR_BZ2: '.tar.bz2',
            ArchiveFormat.TAR_XZ: '.tar.xz',
            ArchiveFormat.ZIP: '.zip',
            ArchiveFormat.PLAIN: '.log'
        }
        
        extension = ext_map.get(self.config.archive_format, '.tar.gz')
        
        archive_name = f"{self.config.path.name}_{timestamp}{extension}"
        return self.config.path.parent / "archives" / archive_name
    
    def _cleanup_old_files(self) -> List[Path]:
        """Удаление старых лог файлов"""
        deleted_files = []
        
        try:
            all_files = self._find_rotated_files()
            
            # Фильтрация по времени
            cutoff_date = datetime.now() - timedelta(days=self.config.keep_days)
            files_to_delete_by_date = [
                f for f in all_files
                if datetime.fromtimestamp(f.stat().st_mtime) < cutoff_date
            ]
            
            # Фильтрация по количеству
            files_sorted = sorted(all_files, key=lambda x: x.stat().st_mtime, reverse=True)
            if len(files_sorted) > self.config.keep_count:
                files_to_delete_by_count = files_sorted[self.config.keep_count:]
            else:
                files_to_delete_by_count = []
            
            # Объединение списков
            files_to_delete = set(files_to_delete_by_date + files_to_delete_by_count)
            
            # Удаление файлов
            for file in files_to_delete:
                try:
                    file.unlink()
                    deleted_files.append(file)
                    logger.info(f"Deleted old log file: {file}")
                except Exception as e:
                    logger.warning(f"Failed to delete {file}: {e}")
            
        except Exception as e:
            logger.error(f"Error cleaning up old files: {e}")
        
        return deleted_files
    
    def _set_file_permissions(self):
        """Установка прав доступа для лог файлов"""
        try:
            if self.config.permissions:
                # Конвертация строки в octal
                permissions = int(self.config.permissions, 8)
                self.config.path.chmod(permissions)
            
            if self.config.owner or self.config.group:
                # Для изменения владельца нужны права root
                import pwd
                import grp
                
                uid = None
                gid = None
                
                if self.config.owner:
                    uid = pwd.getpwnam(self.config.owner).pw_uid
                
                if self.config.group:
                    gid = grp.getgrnam(self.config.group).gr_gid
                
                os.chown(self.config.path, uid if uid else -1, gid if gid else -1)
        
        except Exception as e:
            logger.warning(f"Error setting permissions: {e}")
    
    def _execute_post_rotation_command(self):
        """Выполнение команды после ротации"""
        if not self.config.post_rotation_command:
            return
        
        try:
            # Подстановка переменных
            command = self.config.post_rotation_command
            command = command.replace('{logfile}', str(self.config.path))
            command = command.replace('{timestamp}', datetime.now().isoformat())
            
            # Выполнение команды
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.warning(
                    f"Post-rotation command failed: {result.stderr}"
                )
            else:
                logger.info(
                    f"Post-rotation command executed: {command}"
                )
        
        except Exception as e:
            logger.error(f"Error executing post-rotation command: {e}")


class LogRotationManager:
    """Менеджер управления ротацией логов"""
    
    def __init__(self, config_file: Optional[str] = None):
        self.configs: List[LogFileConfig] = []
        self.results: List[RotationResult] = []
        self.is_running = False
        self.thread_pool = ThreadPoolExecutor(max_workers=5)
        
        if config_file:
            self.load_config(config_file)
        else:
            self.load_default_config()
    
    def load_config(self, config_file: str):
        """Загрузка конфигурации из файла"""
        try:
            config_path = Path(config_file)
            
            if config_path.suffix == '.json':
                self._load_json_config(config_path)
            elif config_path.suffix == '.ini':
                self._load_ini_config(config_path)
            elif config_path.suffix == '.yaml' or config_path.suffix == '.yml':
                self._load_yaml_config(config_path)
            else:
                logger.error(f"Unsupported config format: {config_path.suffix}")
                self.load_default_config()
        
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            self.load_default_config()
    
    def _load_json_config(self, config_path: Path):
        """Загрузка JSON конфигурации"""
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        
        for item in config_data.get('logs', []):
            config = LogFileConfig(
                path=Path(item['path']),
                rotation_strategy=RotationStrategy(item.get('rotation_strategy', 'size')),
                max_size_mb=item.get('max_size_mb', 100),
                rotation_time=item.get('rotation_time', '00:00'),
                keep_days=item.get('keep_days', 30),
                keep_count=item.get('keep_count', 10),
                compression=CompressionMethod(item.get('compression', 'gzip')),
                archive_format=ArchiveFormat(item.get('archive_format', 'plain')),
                post_rotation_command=item.get('post_rotation_command'),
                permissions=item.get('permissions'),
                owner=item.get('owner'),
                group=item.get('group'),
                enabled=item.get('enabled', True),
                patterns=item.get('patterns', [])
            )
            self.configs.append(config)
        
        logger.info(f"Loaded {len(self.configs)} log configurations from JSON")
    
    def _load_ini_config(self, config_path: Path):
        """Загрузка INI конфигурации"""
        parser = configparser.ConfigParser()
        parser.read(config_path)
        
        for section in parser.sections():
            if section.startswith('log:'):
                config = LogFileConfig(
                    path=Path(parser.get(section, 'path')),
                    rotation_strategy=RotationStrategy(
                        parser.get(section, 'rotation_strategy', fallback='size')
                    ),
                    max_size_mb=parser.getint(section, 'max_size_mb', fallback=100),
                    rotation_time=parser.get(section, 'rotation_time', fallback='00:00'),
                    keep_days=parser.getint(section, 'keep_days', fallback=30),
                    keep_count=parser.getint(section, 'keep_count', fallback=10),
                    compression=CompressionMethod(
                        parser.get(section, 'compression', fallback='gzip')
                    ),
                    archive_format=ArchiveFormat(
                        parser.get(section, 'archive_format', fallback='plain')
                    ),
                    post_rotation_command=parser.get(section, 'post_rotation_command', fallback=None),
                    permissions=parser.get(section, 'permissions', fallback=None),
                    owner=
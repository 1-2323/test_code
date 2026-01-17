from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import sqlite3
from contextlib import contextmanager
import logging
import json
import re
import threading
import time
from collections import defaultdict
import math
import jieba  # Для китайского языка, установите: pip install jieba
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    """Типы документов."""
    ARTICLE = "article"
    PRODUCT = "product"
    USER = "user"
    COMMENT = "comment"
    PAGE = "page"
    FILE = "file"


class SearchField(str, Enum):
    """Поля для поиска."""
    TITLE = "title"
    CONTENT = "content"
    DESCRIPTION = "description"
    TAGS = "tags"
    AUTHOR = "author"
    ALL = "all"  # Все поля


@dataclass
class Document:
    """Документ для индексации."""
    id: str
    doc_type: DocumentType
    title: str
    content: str
    fields: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    language: str = "en"
    boost: float = 1.0  # Коэффициент релевантности
    
    def get_field(self, field: SearchField) -> str:
        """Получение значения поля."""
        if field == SearchField.TITLE:
            return self.title
        elif field == SearchField.CONTENT:
            return self.content
        elif field == SearchField.ALL:
            all_text = [self.title, self.content]
            all_text.extend(self.fields.values())
            return " ".join(filter(None, all_text))
        else:
            return self.fields.get(field.value, "")


@dataclass
class SearchResult:
    """Результат поиска."""
    document: Document
    score: float
    highlights: Dict[str, List[str]] = field(default_factory=dict)


class TextTokenizer:
    """Токенизатор текста."""
    
    def __init__(self, language: str = "en"):
        """
        Инициализация токенизатора.
        
        Args:
            language: Язык текста
        """
        self.language = language
        self.stop_words = self._load_stop_words()
    
    def _load_stop_words(self) -> Set[str]:
        """Загрузка стоп-слов."""
        # Базовый набор стоп-слов для английского
        english_stop_words = {
            'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
            'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be',
            'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
            'will', 'would', 'shall', 'should', 'may', 'might', 'must',
            'can', 'could', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
            'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'its',
            'our', 'their', 'this', 'that', 'these', 'those'
        }
        
        # Можно расширить для других языков
        if self.language.startswith('zh'):  # Китайский
            # Для китайского используем jieba
            pass
        
        return english_stop_words
    
    def tokenize(self, text: str) -> List[str]:
        """
        Токенизация текста.
        
        Args:
            text: Текст для токенизации
            
        Returns:
            Список токенов
        """
        if not text:
            return []
        
        # Очистка текста
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)  # Удаляем пунктуацию
        text = re.sub(r'\s+', ' ', text).strip()
        
        if self.language.startswith('zh'):
            # Токенизация для китайского языка
            return list(jieba.cut(text, cut_all=False))
        else:
            # Простая токенизация по словам для других языков
            tokens = text.split()
            
            # Удаление стоп-слов
            tokens = [token for token in tokens if token not in self.stop_words]
            
            return tokens
    
    def normalize_token(self, token: str) -> str:
        """
        Нормализация токена.
        
        Args:
            token: Токен для нормализации
            
        Returns:
            Нормализованный токен
        """
        # Приведение к нижнему регистру уже сделано в tokenize
        # Здесь можно добавить стемминг (Porter stemmer, Snowball, etc.)
        
        # Простая нормализация - удаление чисел и коротких токенов
        if token.isdigit() or len(token) < 2:
            return ""
        
        return token
    
    def get_ngrams(self, text: str, n: int = 2) -> List[str]:
        """
        Генерация n-gram.
        
        Args:
            text: Текст
            n: Размер n-gram
            
        Returns:
            Список n-gram
        """
        tokens = self.tokenize(text)
        ngrams = []
        
        for i in range(len(tokens) - n + 1):
            ngram = ' '.join(tokens[i:i+n])
            ngrams.append(ngram)
        
        return ngrams


class InvertedIndex:
    """Обратный индекс."""
    
    def __init__(self):
        self.index: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        self.documents: Dict[str, Document] = {}
        self.doc_lengths: Dict[str, int] = {}  # Длина документа в токенах
        self.avg_doc_length: float = 0.0
        self.total_docs: int = 0
        self.lock = threading.RLock()
    
    def add_document(self, document: Document, tokenizer: TextTokenizer) -> None:
        """
        Добавление документа в индекс.
        
        Args:
            document: Документ для индексации
            tokenizer: Токенизатор
        """
        with self.lock:
            doc_id = document.id
            
            # Удаляем старую версию если существует
            if doc_id in self.documents:
                self.remove_document(doc_id)
            
            # Сохраняем документ
            self.documents[doc_id] = document
            
            # Токенизация по полям
            field_tokens = {}
            total_tokens = 0
            
            for field in SearchField:
                if field == SearchField.ALL:
                    continue
                
                field_text = document.get_field(field)
                if field_text:
                    tokens = tokenizer.tokenize(field_text)
                    normalized_tokens = [
                        tokenizer.normalize_token(token) 
                        for token in tokens 
                        if tokenizer.normalize_token(token)
                    ]
                    
                    if normalized_tokens:
                        field_tokens[field.value] = normalized_tokens
                        total_tokens += len(normalized_tokens)
            
            # Обновляем статистику
            self.doc_lengths[doc_id] = total_tokens
            self.total_docs += 1
            self.avg_doc_length = sum(self.doc_lengths.values()) / self.total_docs
            
            # Добавляем токены в индекс
            for field, tokens in field_tokens.items():
                for token in tokens:
                    self.index[token][doc_id][field] += 1
    
    def remove_document(self, doc_id: str) -> None:
        """
        Удаление документа из индекса.
        
        Args:
            doc_id: ID документа
        """
        with self.lock:
            if doc_id not in self.documents:
                return
            
            # Удаляем из индекса
            tokens_to_remove = []
            
            for token, doc_data in self.index.items():
                if doc_id in doc_data:
                    del doc_data[doc_id]
                
                if not doc_data:
                    tokens_to_remove.append(token)
            
            for token in tokens_to_remove:
                del self.index[token]
            
            # Удаляем из метаданных
            if doc_id in self.doc_lengths:
                old_length = self.doc_lengths[doc_id]
                del self.doc_lengths[doc_id]
                self.total_docs -= 1
                
                if self.total_docs > 0:
                    self.avg_doc_length = (self.avg_doc_length * (self.total_docs + 1) - old_length) / self.total_docs
                else:
                    self.avg_doc_length = 0.0
            
            if doc_id in self.documents:
                del self.documents[doc_id]
    
    def search(
        self,
        query: str,
        tokenizer: TextTokenizer,
        fields: List[SearchField] = None,
        doc_type: Optional[DocumentType] = None,
        limit: int = 10,
        offset: int = 0,
        use_bm25: bool = True
    ) -> List[SearchResult]:
        """
        Поиск по индексу.
        
        Args:
            query: Поисковый запрос
            tokenizer: Токенизатор
            fields: Поля для поиска (None = все поля)
            doc_type: Фильтр по типу документа
            limit: Максимальное количество результатов
            offset: Смещение
            use_bm25: Использовать алгоритм BM25
            
        Returns:
            Список результатов поиска
        """
        with self.lock:
            if not query or not self.documents:
                return []
            
            # Токенизация запроса
            query_tokens = tokenizer.tokenize(query)
            query_tokens = [
                tokenizer.normalize_token(token) 
                for token in query_tokens 
                if tokenizer.normalize_token(token)
            ]
            
            if not query_tokens:
                return []
            
            # Подсчет частот токенов в запросе
            query_term_freq = {}
            for token in query_tokens:
                query_term_freq[token] = query_term_freq.get(token, 0) + 1
            
            # Получаем кандидатов
            doc_scores = defaultdict(float)
            doc_matches = defaultdict(set)  # Совпавшие токены для каждого документа
            
            for token, token_count in query_term_freq.items():
                if token not in self.index:
                    continue
                
                # Получаем документы, содержащие токен
                for doc_id, field_counts in self.index[token].items():
                    # Фильтр по типу документа
                    if doc_type and self.documents[doc_id].doc_type != doc_type:
                        continue
                    
                    # Проверяем поля
                    doc_matches[doc_id].add(token)
                    
                    if use_bm25:
                        # Вычисляем score по BM25
                        score = self._bm25_score(
                            token=token,
                            doc_id=doc_id,
                            query_token_count=token_count,
                            field_counts=field_counts,
                            fields=fields
                        )
                        doc_scores[doc_id] += score
                    else:
                        # Простой TF-IDF
                        score = self._tf_idf_score(
                            token=token,
                            doc_id=doc_id,
                            field_counts=field_counts,
                            fields=fields
                        )
                        doc_scores[doc_id] += score * token_count
            
            # Сортировка по релевантности
            sorted_docs = sorted(
                doc_scores.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            # Подготовка результатов
            results = []
            for i, (doc_id, score) in enumerate(sorted_docs[offset:offset+limit]):
                if doc_id not in self.documents:
                    continue
                
                document = self.documents[doc_id]
                
                # Генерация подсветки
                highlights = self._generate_highlights(
                    document=document,
                    matched_tokens=list(doc_matches[doc_id]),
                    tokenizer=tokenizer,
                    fields=fields
                )
                
                # Применяем boost документа
                final_score = score * document.boost
                
                result = SearchResult(
                    document=document,
                    score=final_score,
                    highlights=highlights
                )
                results.append(result)
            
            return results
    
    def _bm25_score(
        self,
        token: str,
        doc_id: str,
        query_token_count: int,
        field_counts: Dict[str, int],
        fields: Optional[List[SearchField]] = None,
        k1: float = 1.5,
        b: float = 0.75
    ) -> float:
        """
        Вычисление релевантности по алгоритму BM25.
        
        Args:
            token: Токен
            doc_id: ID документа
            query_token_count: Количество токенов в запросе
            field_counts: Частоты токена в полях документа
            fields: Поля для поиска
            k1: Параметр BM25
            b: Параметр BM25
            
        Returns:
            Score по BM25
        """
        # IDF (Inverse Document Frequency)
        doc_freq = len(self.index[token])
        idf = math.log((self.total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
        
        if idf <= 0:
            return 0.0
        
        # TF (Term Frequency) с учетом полей
        total_tf = 0
        if fields:
            for field in fields:
                if field != SearchField.ALL:
                    total_tf += field_counts.get(field.value, 0)
        else:
            total_tf = sum(field_counts.values())
        
        # Длина документа
        doc_length = self.doc_lengths.get(doc_id, 0)
        
        # Вычисление BM25
        tf_norm = total_tf / (1 - b + b * (doc_length / self.avg_doc_length))
        bm25 = idf * (tf_norm * (k1 + 1)) / (tf_norm + k1)
        
        return bm25 * query_token_count
    
    def _tf_idf_score(
        self,
        token: str,
        doc_id: str,
        field_counts: Dict[str, int],
        fields: Optional[List[SearchField]] = None
    ) -> float:
        """
        Вычисление релевантности по TF-IDF.
        
        Args:
            token: Токен
            doc_id: ID документа
            field_counts: Частоты токена в полях документа
            fields: Поля для поиска
            
        Returns:
            Score по TF-IDF
        """
        # TF (Term Frequency)
        total_tf = 0
        if fields:
            for field in fields:
                if field != SearchField.ALL:
                    total_tf += field_counts.get(field.value, 0)
        else:
            total_tf = sum(field_counts.values())
        
        if total_tf == 0:
            return 0.0
        
        # IDF (Inverse Document Frequency)
        doc_freq = len(self.index[token])
        if doc_freq == 0:
            return 0.0
        
        idf = math.log(self.total_docs / doc_freq)
        
        return total_tf * idf
    
    def _generate_highlights(
        self,
        document: Document,
        matched_tokens: List[str],
        tokenizer: TextTokenizer,
        fields: Optional[List[SearchField]] = None
    ) -> Dict[str, List[str]]:
        """
        Генерация подсветки совпадений.
        
        Args:
            document: Документ
            matched_tokens: Совпавшие токены
            tokenizer: Токенизатор
            fields: Поля для поиска
            
        Returns:
            Словарь с подсветкой по полям
        """
        if not matched_tokens:
            return {}
        
        highlights = {}
        search_fields = fields or [SearchField.TITLE, SearchField.CONTENT, SearchField.DESCRIPTION]
        
        for field in search_fields:
            if field == SearchField.ALL:
                continue
            
            field_text = document.get_field(field)
            if not field_text:
                continue
            
            # Создаем regex для поиска токенов
            # Экранируем специальные символы
            token_patterns = []
            for token in matched_tokens:
                # Ищем слово целиком
                escaped_token = re.escape(token)
                token_patterns.append(r'\b' + escaped_token + r'\b')
            
            if not token_patterns:
                continue
            
            pattern = re.compile('|'.join(token_patterns), re.IGNORECASE)
            
            # Находим все совпадения
            matches = list(pattern.finditer(field_text))
            if not matches:
                continue
            
            # Берем первые 3 совпадения
            field_highlights = []
            for match in matches[:3]:
                start = max(0, match.start() - 50)
                end = min(len(field_text), match.end() + 50)
                
                snippet = field_text[start:end]
                if start > 0:
                    snippet = '...' + snippet
                if end < len(field_text):
                    snippet = snippet + '...'
                
                # Подсветка совпадений
                for token in matched_tokens:
                    token_regex = re.compile(r'\b' + re.escape(token) + r'\b', re.IGNORECASE)
                    snippet = token_regex.sub(f'<mark>{token}</mark>', snippet)
                
                field_highlights.append(snippet)
            
            if field_highlights:
                highlights[field.value] = field_highlights
        
        return highlights
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики индекса."""
        with self.lock:
            return {
                'total_documents': self.total_docs,
                'total_tokens': len(self.index),
                'avg_document_length': self.avg_doc_length,
                'document_types': Counter(
                    doc.doc_type.value for doc in self.documents.values()
                )
            }


class SearchIndexStorage:
    """Постоянное хранилище индекса."""
    
    def __init__(self, db_path: str = "search_index.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица документов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    doc_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    fields TEXT,  -- JSON объект
                    metadata TEXT,  -- JSON объект
                    language TEXT DEFAULT 'en',
                    boost REAL DEFAULT 1.0,
                    created_at REAL,
                    updated_at REAL,
                    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица токенов (обратный индекс)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    token TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    frequency INTEGER DEFAULT 1,
                    PRIMARY KEY (token, doc_id, field),
                    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
                )
            """)
            
            # Индексы
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tokens_token ON tokens(token)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(doc_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at)")
            
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
    
    def save_document(self, document: Document) -> bool:
        """Сохранение документа."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO documents 
                    (id, doc_type, title, content, fields, metadata, 
                     language, boost, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    document.id,
                    document.doc_type.value,
                    document.title,
                    document.content,
                    json.dumps(document.fields) if document.fields else None,
                    json.dumps(document.metadata) if document.metadata else None,
                    document.language,
                    document.boost,
                    document.created_at,
                    document.updated_at
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error saving document {document.id}: {e}")
            return False
    
    def load_document(self, doc_id: str) -> Optional[Document]:
        """Загрузка документа."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM documents WHERE id = ?",
                    (doc_id,)
                )
                
                row = cursor.fetchone()
                if row:
                    return Document(
                        id=row['id'],
                        doc_type=DocumentType(row['doc_type']),
                        title=row['title'],
                        content=row['content'],
                        fields=json.loads(row['fields']) if row['fields'] else {},
                        metadata=json.loads(row['metadata']) if row['metadata'] else {},
                        language=row['language'],
                        boost=row['boost'],
                        created_at=row['created_at'],
                        updated_at=row['updated_at']
                    )
                
                return None
                
        except Exception as e:
            logger.error(f"Error loading document {doc_id}: {e}")
            return None
    
    def save_tokens(self, doc_id: str, tokens: Dict[str, Dict[str, int]]) -> bool:
        """Сохранение токенов документа."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Удаляем старые токены документа
                cursor.execute(
                    "DELETE FROM tokens WHERE doc_id = ?",
                    (doc_id,)
                )
                
                # Сохраняем новые токены
                for token, field_counts in tokens.items():
                    for field, frequency in field_counts.items():
                        cursor.execute("""
                            INSERT INTO tokens (token, doc_id, field, frequency)
                            VALUES (?, ?, ?, ?)
                        """, (token, doc_id, field, frequency))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error saving tokens for document {doc_id}: {e}")
            return False
    
    def load_tokens(self, token: str) -> Dict[str, Dict[str, int]]:
        """
        Загрузка токенов из хранилища.
        
        Args:
            token: Токен для загрузки
            
        Returns:
            Словарь {doc_id: {field: frequency}}
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT doc_id, field, frequency 
                    FROM tokens 
                    WHERE token = ?
                """, (token,))
                
                result = defaultdict(lambda: defaultdict(int))
                for row in cursor.fetchall():
                    result[row['doc_id']][row['field']] = row['frequency']
                
                return dict(result)
                
        except Exception as e:
            logger.error(f"Error loading tokens for {token}: {e}")
            return {}


class SearchEngine:
    """Поисковый движок."""
    
    def __init__(self, storage: Optional[SearchIndexStorage] = None):
        self.storage = storage or SearchIndexStorage()
        self.in_memory_index = InvertedIndex()
        self.tokenizers: Dict[str, TextTokenizer] = {}
        self._index_loaded = False
        self.lock = threading.RLock()
        
        # Загрузка индекса в память
        self._load_index_to_memory()
    
    def _load_index_to_memory(self):
        """Загрузка индекса из хранилища в память."""
        if self._index_loaded:
            return
        
        try:
            with self.storage._get_connection() as conn:
                cursor = conn.cursor()
                
                # Загружаем документы
                cursor.execute("SELECT id FROM documents")
                doc_ids = [row['id'] for row in cursor.fetchall()]
                
                logger.info(f"Loading {len(doc_ids)} documents to memory...")
                
                for i, doc_id in enumerate(doc_ids):
                    if i % 1000 == 0:
                        logger.debug(f"Loaded {i} documents...")
                    
                    document = self.storage.load_document(doc_id)
                    if document:
                        tokenizer = self._get_tokenizer(document.language)
                        self.in_memory_index.add_document(document, tokenizer)
                
                self._index_loaded = True
                logger.info(f"Index loaded to memory: {len(doc_ids)} documents")
                
        except Exception as e:
            logger.error(f"Error loading index to memory: {e}")
    
    def _get_tokenizer(self, language: str) -> TextTokenizer:
        """
        Получение токенизатора для языка.
        
        Args:
            language: Язык
            
        Returns:
            Токенизатор
        """
        if language not in self.tokenizers:
            self.tokenizers[language] = TextTokenizer(language)
        
        return self.tokenizers[language]
    
    def index_document(self, document: Document) -> bool:
        """
        Индексация документа.
        
        Args:
            document: Документ для индексации
            
        Returns:
            True если успешно
        """
        with self.lock:
            try:
                # Сохраняем документ в хранилище
                success = self.storage.save_document(document)
                if not success:
                    return False
                
                # Токенизация и сохранение токенов
                tokenizer = self._get_tokenizer(document.language)
                tokens = tokenizer.tokenize(document.get_field(SearchField.ALL))
                
                # Подсчет частот токенов по полям
                token_frequencies = defaultdict(lambda: defaultdict(int))
                
                for field in SearchField:
                    if field == SearchField.ALL:
                        continue
                    
                    field_text = document.get_field(field)
                    if field_text:
                        field_tokens = tokenizer.tokenize(field_text)
                        for token in field_tokens:
                            normalized = tokenizer.normalize_token(token)
                            if normalized:
                                token_frequencies[normalized][field.value] += 1
                
                # Сохраняем токены
                if token_frequencies:
                    self.storage.save_tokens(document.id, dict(token_frequencies))
                
                # Добавляем в memory index
                self.in_memory_index.add_document(document, tokenizer)
                
                logger.info(f"Document indexed: {document.id} ({document.doc_type.value})")
                return True
                
            except Exception as e:
                logger.error(f"Error indexing document {document.id}: {e}")
                return False
    
    def search(
        self,
        query: str,
        language: str = "en",
        fields: Optional[List[SearchField]] = None,
        doc_type: Optional[DocumentType] = None,
        limit: int = 10,
        offset: int = 0,
        min_score: float = 0.1
    ) -> List[SearchResult]:
        """
        Поиск по индексу.
        
        Args:
            query: Поисковый запрос
            language: Язык запроса
            fields: Поля для поиска
            doc_type: Фильтр по типу документа
            limit: Максимальное количество результатов
            offset: Смещение
            min_score: Минимальный score
            
        Returns:
            Результаты поиска
        """
        with self.lock:
            tokenizer = self._get_tokenizer(language)
            
            results = self.in_memory_index.search(
                query=query,
                tokenizer=tokenizer,
                fields=fields,
                doc_type=doc_type,
                limit=limit + offset,
                offset=0,
                use_bm25=True
            )
            
            # Фильтрация по минимальному score
            filtered_results = [
                result for result in results 
                if result.score >= min_score
            ]
            
            # Применяем offset
            paginated_results = filtered_results[offset:offset + limit]
            
            logger.debug(f"Search for '{query}' returned {len(paginated_results)} results")
            return paginated_results
    
    def delete_document(self, doc_id: str) -> bool:
        """
        Удаление документа из индекса.
        
        Args:
            doc_id: ID документа
            
        Returns:
            True если успешно
        """
        with self.lock:
            try:
                # Удаляем из memory index
                self.in_memory_index.remove_document(doc_id)
                
                # Удаляем из хранилища
                with self.storage._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute(
                        "DELETE FROM documents WHERE id = ?",
                        (doc_id,)
                    )
                    
                    cursor.execute(
                        "DELETE FROM tokens WHERE doc_id = ?",
                        (doc_id,)
                    )
                    
                    conn.commit()
                
                logger.info(f"Document deleted from index: {doc_id}")
                return True
                
            except Exception as e:
                logger.error(f"Error deleting document {doc_id}: {e}")
                return False
    
    def update_document(self, document: Document) -> bool:
        """
        Обновление документа в индексе.
        
        Args:
            document: Обновленный документ
            
        Returns:
            True если успешно
        """
        # Обновляем время изменения
        document.updated_at = time.time()
        
        # Просто переиндексируем
        return self.index_document(document)
    
    def batch_index(self, documents: List[Document]) -> Dict[str, bool]:
        """
        Пакетная индексация документов.
        
        Args:
            documents: Список документов
            
        Returns:
            Словарь {doc_id: success}
        """
        results = {}
        
        for document in documents:
            success = self.index_document(document)
            results[document.id] = success
        
        return results
    
    def get_index_stats(self) -> Dict[str, Any]:
        """Получение статистики индекса."""
        with self.lock:
            memory_stats = self.in_memory_index.get_stats()
            
            try:
                with self.storage._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("SELECT COUNT(*) as count FROM documents")
                    storage_docs = cursor.fetchone()['count']
                    
                    cursor.execute("SELECT COUNT(DISTINCT token) as count FROM tokens")
                    storage_tokens = cursor.fetchone()['count']
                    
                    return {
                        'memory': memory_stats,
                        'storage': {
                            'total_documents': storage_docs,
                            'total_tokens': storage_tokens
                        },
                        'sync_status': memory_stats['total_documents'] == storage_docs
                    }
                    
            except Exception as e:
                logger.error(f"Error getting index stats: {e}")
                return {'memory': memory_stats}
    
    def rebuild_index(self) -> bool:
        """
        Перестроение индекса.
        
        Returns:
            True если успешно
        """
        with self.lock:
            try:
                logger.info("Starting index rebuild...")
                
                # Создаем новый memory index
                new_index = InvertedIndex()
                
                # Загружаем все документы из хранилища
                with self.storage._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM documents")
                    
                    doc_ids = [row['id'] for row in cursor.fetchall()]
                    
                    for doc_id in doc_ids:
                        document = self.storage.load_document(doc_id)
                        if document:
                            tokenizer = self._get_tokenizer(document.language)
                            new_index.add_document(document, tokenizer)
                
                # Заменяем старый индекс
                self.in_memory_index = new_index
                self._index_loaded = True
                
                logger.info(f"Index rebuilt: {len(doc_ids)} documents")
                return True
                
            except Exception as e:
                logger.error(f"Error rebuilding index: {e}")
                return False
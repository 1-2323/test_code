from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict, Counter
import sqlite3
from contextlib import contextmanager
import logging
import json
import math

logger = logging.getLogger(__name__)


@dataclass
class UserInteraction:
    """Взаимодействие пользователя с контентом."""
    user_id: str
    item_id: str
    interaction_type: str  # view, like, purchase, etc.
    weight: float = 1.0
    timestamp: datetime = field(default_factory=datetime.now)


class RecommendationEngine:
    """Движок рекомендаций."""
    
    def __init__(self, db_path: str = "recommendations.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация БД."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    interaction_type TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    timestamp TIMESTAMP NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user ON user_interactions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_item ON user_interactions(item_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_item ON user_interactions(user_id, item_id)")
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def log_interaction(self, interaction: UserInteraction) -> bool:
        """Логирование взаимодействия."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO user_interactions 
                    (user_id, item_id, interaction_type, weight, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    interaction.user_id,
                    interaction.item_id,
                    interaction.interaction_type,
                    interaction.weight,
                    interaction.timestamp.isoformat()
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error logging interaction: {e}")
            return False
    
    def get_collaborative_recommendations(self, user_id: str,
                                         limit: int = 10) -> List[Dict[str, Any]]:
        """
        Коллаборативная фильтрация.
        
        Args:
            user_id: ID пользователя
            limit: Максимальное количество рекомендаций
            
        Returns:
            Список рекомендованных товаров с оценками
        """
        try:
            # Получаем предпочтения пользователя
            user_items = self._get_user_items(user_id)
            if not user_items:
                return []
            
            # Находим похожих пользователей
            similar_users = self._find_similar_users(user_id, user_items)
            
            # Рекомендуем товары, которые нравятся похожим пользователям
            recommendations = defaultdict(float)
            
            for similar_user_id, similarity in similar_users.items():
                similar_user_items = self._get_user_items(similar_user_id)
                
                for item_id, weight in similar_user_items.items():
                    if item_id not in user_items:
                        recommendations[item_id] += similarity * weight
            
            # Сортируем по весу
            sorted_recs = sorted(
                recommendations.items(),
                key=lambda x: x[1],
                reverse=True
            )[:limit]
            
            return [
                {'item_id': item_id, 'score': score}
                for item_id, score in sorted_recs
            ]
            
        except Exception as e:
            logger.error(f"Error generating collaborative recommendations: {e}")
            return []
    
    def get_content_based_recommendations(self, user_id: str,
                                         item_features: Dict[str, Dict[str, float]],
                                         limit: int = 10) -> List[Dict[str, Any]]:
        """
        Контентно-ориентированные рекомендации.
        
        Args:
            user_id: ID пользователя
            item_features: Словарь {item_id: {feature: weight}}
            limit: Максимальное количество рекомендаций
            
        Returns:
            Список рекомендованных товаров
        """
        try:
            # Получаем профиль пользователя
            user_profile = self._build_user_profile(user_id, item_features)
            if not user_profile:
                return []
            
            # Сравниваем с каждым товаром
            recommendations = []
            
            for item_id, features in item_features.items():
                # Пропускаем товары, которые пользователь уже видел
                if self._has_interacted(user_id, item_id):
                    continue
                
                # Вычисляем схожесть
                similarity = self._cosine_similarity(user_profile, features)
                
                if similarity > 0:
                    recommendations.append({
                        'item_id': item_id,
                        'score': similarity
                    })
            
            # Сортируем по схожести
            recommendations.sort(key=lambda x: x['score'], reverse=True)
            
            return recommendations[:limit]
            
        except Exception as e:
            logger.error(f"Error generating content-based recommendations: {e}")
            return []
    
    def get_popular_items(self, days: int = 30,
                         limit: int = 10) -> List[Dict[str, Any]]:
        """
        Популярные товары.
        
        Args:
            days: За сколько дней считать популярность
            limit: Максимальное количество
            
        Returns:
            Список популярных товаров
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT item_id, 
                           COUNT(*) as interaction_count,
                           SUM(weight) as total_weight
                    FROM user_interactions 
                    WHERE timestamp >= ?
                    GROUP BY item_id 
                    ORDER BY total_weight DESC 
                    LIMIT ?
                """, (cutoff_date.isoformat(), limit))
                
                popular_items = []
                for row in cursor.fetchall():
                    popular_items.append({
                        'item_id': row['item_id'],
                        'interaction_count': row['interaction_count'],
                        'total_weight': row['total_weight']
                    })
                
                return popular_items
                
        except Exception as e:
            logger.error(f"Error getting popular items: {e}")
            return []
    
    def _get_user_items(self, user_id: str) -> Dict[str, float]:
        """Получение товаров пользователя с весами."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT item_id, SUM(weight) as total_weight
                    FROM user_interactions 
                    WHERE user_id = ?
                    GROUP BY item_id
                """, (user_id,))
                
                items = {}
                for row in cursor.fetchall():
                    items[row['item_id']] = row['total_weight']
                
                return items
        except Exception as e:
            logger.error(f"Error getting user items: {e}")
            return {}
    
    def _find_similar_users(self, user_id: str,
                           user_items: Dict[str, float],
                           limit: int = 50) -> Dict[str, float]:
        """Поиск похожих пользователей."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Получаем всех пользователей, которые взаимодействовали с теми же товарами
                similar_users = defaultdict(float)
                
                for item_id in user_items.keys():
                    cursor.execute("""
                        SELECT user_id, SUM(weight) as item_weight
                        FROM user_interactions 
                        WHERE item_id = ? AND user_id != ?
                        GROUP BY user_id
                    """, (item_id, user_id))
                    
                    for row in cursor.fetchall():
                        similar_user_id = row['user_id']
                        item_weight = row['item_weight']
                        
                        # Учитываем вес взаимодействия
                        similarity = min(user_items[item_id], item_weight)
                        similar_users[similar_user_id] += similarity
                
                # Нормализуем схожесть
                user_total = sum(user_items.values())
                
                normalized = {}
                for similar_user_id, similarity in similar_users.items():
                    similar_user_items = self._get_user_items(similar_user_id)
                    similar_user_total = sum(similar_user_items.values())
                    
                    if user_total > 0 and similar_user_total > 0:
                        normalized[similar_user_id] = (
                            similarity / math.sqrt(user_total * similar_user_total)
                        )
                
                # Сортируем по схожести
                sorted_users = sorted(
                    normalized.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:limit]
                
                return dict(sorted_users)
                
        except Exception as e:
            logger.error(f"Error finding similar users: {e}")
            return {}
    
    def _build_user_profile(self, user_id: str,
                           item_features: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Построение профиля пользователя."""
        # Получаем товары пользователя с весами
        user_items = self._get_user_items(user_id)
        
        # Собираем все фичи с весами
        user_profile = defaultdict(float)
        
        for item_id, weight in user_items.items():
            if item_id in item_features:
                features = item_features[item_id]
                for feature, feature_weight in features.items():
                    user_profile[feature] += weight * feature_weight
        
        # Нормализуем профиль
        total_weight = sum(user_profile.values())
        if total_weight > 0:
            for feature in user_profile:
                user_profile[feature] /= total_weight
        
        return dict(user_profile)
    
    def _has_interacted(self, user_id: str, item_id: str) -> bool:
        """Проверка, взаимодействовал ли пользователь с товаром."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM user_interactions 
                    WHERE user_id = ? AND item_id = ?
                """, (user_id, item_id))
                
                return cursor.fetchone()['count'] > 0
        except:
            return False
    
    @staticmethod
    def _cosine_similarity(vec1: Dict[str, float],
                          vec2: Dict[str, float]) -> float:
        """Косинусная схожесть двух векторов."""
        # Находим общие фичи
        common_features = set(vec1.keys()) & set(vec2.keys())
        if not common_features:
            return 0.0
        
        dot_product = sum(vec1[feature] * vec2[feature] 
                         for feature in common_features)
        
        norm1 = math.sqrt(sum(weight ** 2 for weight in vec1.values()))
        norm2 = math.sqrt(sum(weight ** 2 for weight in vec2.values()))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
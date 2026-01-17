from typing import Dict, Optional, Any, Tuple, List
from dataclasses import dataclass, field
from math import radians, sin, cos, sqrt, atan2
import requests
import sqlite3
from contextlib import contextmanager
import logging
import json
from enum import Enum

logger = logging.getLogger(__name__)


class DistanceUnit(str, Enum):
    """Единицы измерения расстояния."""
    KILOMETERS = "km"
    METERS = "m"
    MILES = "mi"


@dataclass
class Coordinates:
    """Географические координаты."""
    latitude: float
    longitude: float
    
    def validate(self) -> bool:
        """Валидация координат."""
        return -90 <= self.latitude <= 90 and -180 <= self.longitude <= 180
    
    def to_dict(self) -> Dict[str, float]:
        return {'lat': self.latitude, 'lon': self.longitude}


@dataclass
class Location:
    """Локация с адресом."""
    coordinates: Coordinates
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    formatted_address: Optional[str] = None


class GeoCalculator:
    """Калькулятор геоданных."""
    
    @staticmethod
    def haversine_distance(coord1: Coordinates, coord2: Coordinates, 
                          unit: DistanceUnit = DistanceUnit.KILOMETERS) -> float:
        """
        Расчет расстояния по формуле гаверсинуса.
        
        Args:
            coord1: Первые координаты
            coord2: Вторые координаты
            unit: Единица измерения
            
        Returns:
            Расстояние в указанных единицах
        """
        # Радиус Земли в километрах
        R = 6371.0
        
        lat1 = radians(coord1.latitude)
        lon1 = radians(coord1.longitude)
        lat2 = radians(coord2.latitude)
        lon2 = radians(coord2.longitude)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        
        distance_km = R * c
        
        # Конвертация единиц
        if unit == DistanceUnit.METERS:
            return distance_km * 1000
        elif unit == DistanceUnit.MILES:
            return distance_km * 0.621371
        else:
            return distance_km
    
    @staticmethod
    def bounding_box(center: Coordinates, radius_km: float) -> Tuple[Coordinates, Coordinates]:
        """
        Расчет bounding box вокруг точки.
        
        Args:
            center: Центральная точка
            radius_km: Радиус в километрах
            
        Returns:
            (северо-западный угол, юго-восточный угол)
        """
        # Приблизительное преобразование градусов в километры
        lat_deg_per_km = 1 / 110.574
        lon_deg_per_km = 1 / (111.320 * cos(radians(center.latitude)))
        
        lat_delta = radius_km * lat_deg_per_km
        lon_delta = radius_km * lon_deg_per_km
        
        nw = Coordinates(
            latitude=center.latitude + lat_delta,
            longitude=center.longitude - lon_delta
        )
        
        se = Coordinates(
            latitude=center.latitude - lat_delta,
            longitude=center.longitude + lon_delta
        )
        
        return nw, se


class Geocoder:
    """Геокодер для преобразования адреса в координаты."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://nominatim.openstreetmap.org"
    
    def geocode(self, address: str) -> Optional[Location]:
        """Преобразование адреса в координаты."""
        try:
            params = {
                'q': address,
                'format': 'json',
                'limit': 1
            }
            
            headers = {
                'User-Agent': 'GeoService/1.0'
            }
            
            response = requests.get(
                f"{self.base_url}/search",
                params=params,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data:
                    location_data = data[0]
                    
                    return Location(
                        coordinates=Coordinates(
                            latitude=float(location_data['lat']),
                            longitude=float(location_data['lon'])
                        ),
                        address=location_data.get('display_name'),
                        city=location_data.get('address', {}).get('city'),
                        country=location_data.get('address', {}).get('country'),
                        postal_code=location_data.get('address', {}).get('postcode')
                    )
            
        except Exception as e:
            logger.error(f"Geocoding failed: {e}")
        
        return None
    
    def reverse_geocode(self, coordinates: Coordinates) -> Optional[Location]:
        """Преобразование координат в адрес."""
        try:
            params = {
                'lat': coordinates.latitude,
                'lon': coordinates.longitude,
                'format': 'json'
            }
            
            headers = {
                'User-Agent': 'GeoService/1.0'
            }
            
            response = requests.get(
                f"{self.base_url}/reverse",
                params=params,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                return Location(
                    coordinates=coordinates,
                    address=data.get('display_name'),
                    city=data.get('address', {}).get('city'),
                    country=data.get('address', {}).get('country'),
                    postal_code=data.get('address', {}).get('postcode')
                )
            
        except Exception as e:
            logger.error(f"Reverse geocoding failed: {e}")
        
        return None


class LocationStorage:
    """Хранилище локаций."""
    
    def __init__(self, db_path: str = "locations.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация БД."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    address TEXT,
                    city TEXT,
                    country TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, name)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user ON locations(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_coords ON locations(latitude, longitude)")
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def save_location(self, user_id: str, name: str,
                     coordinates: Coordinates,
                     address: Optional[str] = None,
                     city: Optional[str] = None,
                     country: Optional[str] = None) -> bool:
        """Сохранение локации пользователя."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO locations 
                    (user_id, name, latitude, longitude, address, city, country)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    name,
                    coordinates.latitude,
                    coordinates.longitude,
                    address,
                    city,
                    country
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving location: {e}")
            return False
    
    def get_nearby_locations(self, center: Coordinates,
                            radius_km: float,
                            user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Поиск ближайших локаций."""
        try:
            # Получаем bounding box для фильтрации
            calculator = GeoCalculator()
            nw, se = calculator.bounding_box(center, radius_km)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT *, 
                    (6371 * acos(
                        cos(radians(?)) * cos(radians(latitude)) * 
                        cos(radians(longitude) - radians(?)) + 
                        sin(radians(?)) * sin(radians(latitude))
                    )) as distance_km
                    FROM locations 
                    WHERE latitude BETWEEN ? AND ?
                    AND longitude BETWEEN ? AND ?
                """
                
                params = [
                    center.latitude,
                    center.longitude,
                    center.latitude,
                    se.latitude,  # min lat
                    nw.latitude,  # max lat
                    nw.longitude, # min lon
                    se.longitude  # max lon
                ]
                
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                
                query += " HAVING distance_km <= ? ORDER BY distance_km"
                params.append(radius_km)
                
                cursor.execute(query, params)
                
                locations = []
                for row in cursor.fetchall():
                    locations.append({
                        'id': row['id'],
                        'user_id': row['user_id'],
                        'name': row['name'],
                        'coordinates': {
                            'latitude': row['latitude'],
                            'longitude': row['longitude']
                        },
                        'address': row['address'],
                        'city': row['city'],
                        'country': row['country'],
                        'distance_km': round(row['distance_km'], 2)
                    })
                
                return locations
                
        except Exception as e:
            logger.error(f"Error finding nearby locations: {e}")
            return []
    
    def get_user_locations(self, user_id: str) -> List[Dict[str, Any]]:
        """Получение локаций пользователя."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM locations 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC
                """, (user_id,))
                
                locations = []
                for row in cursor.fetchall():
                    locations.append({
                        'id': row['id'],
                        'name': row['name'],
                        'coordinates': {
                            'latitude': row['latitude'],
                            'longitude': row['longitude']
                        },
                        'address': row['address'],
                        'city': row['city'],
                        'country': row['country'],
                        'created_at': row['created_at']
                    })
                
                return locations
                
        except Exception as e:
            logger.error(f"Error getting user locations: {e}")
            return []
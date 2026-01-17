import csv
import json
from typing import List, Dict, Any
from datetime import datetime
from io import StringIO, BytesIO
import zipfile
from abc import ABC, abstractmethod

class DataExporter(ABC):
    """Базовый экспортер данных."""
    
    @abstractmethod
    def export(self, data: List[Dict[str, Any]]) -> bytes:
        """Экспорт данных."""
        pass

class CSVExporter(DataExporter):
    """Экспорт в CSV."""
    
    def __init__(self, delimiter: str = ","):
        self.delimiter = delimiter
    
    def export(self, data: List[Dict[str, Any]]) -> bytes:
        if not data:
            return b""
        
        # Определяем поля
        fieldnames = list(data[0].keys())
        
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=self.delimiter)
        
        writer.writeheader()
        writer.writerows(data)
        
        return output.getvalue().encode('utf-8')

class JSONExporter(DataExporter):
    """Экспорт в JSON."""
    
    def export(self, data: List[Dict[str, Any]]) -> bytes:
        return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')

class ExcelExporter(DataExporter):
    """Экспорт в Excel."""
    
    def export(self, data: List[Dict[str, Any]]) -> bytes:
        try:
            import pandas as pd
            df = pd.DataFrame(data)
            
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Data')
            
            return output.getvalue()
        except ImportError:
            raise ImportError("Install pandas and openpyxl for Excel export")

class ExportManager:
    """Менеджер экспорта."""
    
    def __init__(self):
        self.exporters = {
            'csv': CSVExporter(),
            'json': JSONExporter(),
            'excel': ExcelExporter()
        }
    
    def export(self, data: List[Dict[str, Any]], format: str) -> Dict[str, Any]:
        """Экспорт данных в указанном формате."""
        if format not in self.exporters:
            raise ValueError(f"Unsupported format: {format}")
        
        exporter = self.exporters[format]
        content = exporter.export(data)
        
        filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{format}"
        
        return {
            'content': content,
            'filename': filename,
            'content_type': self._get_content_type(format),
            'size': len(content)
        }
    
    def export_zip(self, data_sets: Dict[str, List[Dict[str, Any]]]) -> bytes:
        """Экспорт нескольких наборов данных в ZIP."""
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for name, data in data_sets.items():
                # Экспортируем в CSV по умолчанию
                exporter = CSVExporter()
                content = exporter.export(data)
                
                filename = f"{name}.csv"
                zip_file.writestr(filename, content)
        
        return zip_buffer.getvalue()
    
    @staticmethod
    def _get_content_type(format: str) -> str:
        """Получение Content-Type для формата."""
        types = {
            'csv': 'text/csv',
            'json': 'application/json',
            'excel': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        }
        return types.get(format, 'application/octet-stream')
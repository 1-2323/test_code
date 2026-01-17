from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
import pandas as pd
import jinja2
from io import BytesIO
import matplotlib.pyplot as plt

@dataclass
class ReportConfig:
    """Конфигурация отчета."""
    title: str
    start_date: datetime
    end_date: datetime
    filters: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.filters is None:
            self.filters = {}

class ReportGenerator(ABC):
    """Базовый генератор отчетов."""
    
    @abstractmethod
    async def generate(self, config: ReportConfig) -> Dict[str, Any]:
        """Генерация отчета."""
        pass

class SalesReportGenerator(ReportGenerator):
    """Генератор отчета по продажам."""
    
    def __init__(self, data_source):
        self.data_source = data_source
    
    async def generate(self, config: ReportConfig) -> Dict[str, Any]:
        # Получаем данные
        sales_data = await self.data_source.get_sales_data(
            config.start_date,
            config.end_date,
            config.filters
        )
        
        # Анализируем данные
        analysis = self._analyze_sales(sales_data)
        
        # Генерируем визуализации
        charts = self._generate_charts(sales_data)
        
        # Форматируем отчет
        report = {
            'title': config.title,
            'period': f"{config.start_date.date()} - {config.end_date.date()}",
            'generated_at': datetime.now(),
            'summary': analysis['summary'],
            'details': analysis['details'],
            'charts': charts
        }
        
        return report
    
    def _analyze_sales(self, data: List[Dict]) -> Dict[str, Any]:
        """Анализ данных о продажах."""
        df = pd.DataFrame(data)
        
        summary = {
            'total_sales': df['amount'].sum(),
            'avg_order_value': df['amount'].mean(),
            'total_orders': len(df),
            'top_products': df.groupby('product')['amount'].sum().nlargest(5).to_dict()
        }
        
        details = {
            'daily_sales': df.groupby(df['date'].dt.date)['amount'].sum().to_dict(),
            'by_category': df.groupby('category')['amount'].sum().to_dict(),
            'customer_stats': {
                'repeat_customers': df['customer_id'].nunique(),
                'new_customers': len(df['customer_id'].unique())
            }
        }
        
        return {'summary': summary, 'details': details}
    
    def _generate_charts(self, data: List[Dict]) -> Dict[str, bytes]:
        """Генерация графиков."""
        df = pd.DataFrame(data)
        
        charts = {}
        
        # График продаж по дням
        fig, ax = plt.subplots(figsize=(10, 6))
        daily_sales = df.groupby(df['date'].dt.date)['amount'].sum()
        ax.plot(daily_sales.index, daily_sales.values)
        ax.set_title('Daily Sales')
        ax.set_xlabel('Date')
        ax.set_ylabel('Amount')
        
        buffer = BytesIO()
        plt.tight_layout()
        plt.savefig(buffer, format='png', dpi=100)
        buffer.seek(0)
        charts['daily_sales'] = buffer.getvalue()
        plt.close()
        
        return charts

class ReportExporter:
    """Экспортер отчетов."""
    
    def __init__(self):
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader('templates')
        )
    
    def to_html(self, report: Dict[str, Any]) -> str:
        """Экспорт в HTML."""
        template = self.template_env.get_template('report.html')
        return template.render(report=report)
    
    def to_pdf(self, report: Dict[str, Any]) -> bytes:
        """Экспорт в PDF."""
        # Используем weasyprint или reportlab в реальной реализации
        html_content = self.to_html(report)
        # Конвертация HTML в PDF
        return b"PDF_CONTENT"  # Заглушка
    
    def to_excel(self, report: Dict[str, Any]) -> bytes:
        """Экспорт в Excel."""
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Сводка
            summary_df = pd.DataFrame([report['summary']])
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            # Детали
            for sheet_name, data in report['details'].items():
                if isinstance(data, dict):
                    df = pd.DataFrame(list(data.items()), columns=['Key', 'Value'])
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        return output.getvalue()
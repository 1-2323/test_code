from typing import Dict, Any, Optional, Callable
import re
from datetime import datetime
import html
from abc import ABC, abstractmethod

class TemplateError(Exception):
    """Ошибка шаблона."""
    pass

class TemplateNode(ABC):
    """Базовый узел шаблона."""
    
    @abstractmethod
    def render(self, context: Dict[str, Any]) -> str:
        pass

class TextNode(TemplateNode):
    """Текстовый узел."""
    
    def __init__(self, text: str):
        self.text = text
    
    def render(self, context: Dict[str, Any]) -> str:
        return self.text

class VariableNode(TemplateNode):
    """Узел переменной."""
    
    def __init__(self, var_name: str, escape: bool = True):
        self.var_name = var_name.strip()
        self.escape = escape
    
    def render(self, context: Dict[str, Any]) -> str:
        # Поддержка точечной нотации: user.name
        value = context
        for part in self.var_name.split('.'):
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return ""
        
        result = str(value) if value is not None else ""
        
        if self.escape and isinstance(result, str):
            result = html.escape(result)
        
        return result

class IfNode(TemplateNode):
    """Узел условия."""
    
    def __init__(self, condition: str, true_block: list, false_block: list = None):
        self.condition = condition.strip()
        self.true_block = true_block
        self.false_block = false_block or []
    
    def render(self, context: Dict[str, Any]) -> str:
        # Простая проверка условий
        condition_parts = self.condition.split()
        
        if len(condition_parts) == 1:
            # Проверка существования переменной
            var_name = condition_parts[0]
            value = self._get_value(context, var_name)
            condition_met = bool(value)
        elif len(condition_parts) == 3:
            # Сравнение: var op value
            var_name, operator, compare_value = condition_parts
            
            value = self._get_value(context, var_name)
            
            try:
                compare_value = int(compare_value)
                if isinstance(value, str):
                    try:
                        value = int(value)
                    except:
                        pass
            except:
                pass
            
            if operator == '==':
                condition_met = value == compare_value
            elif operator == '!=':
                condition_met = value != compare_value
            elif operator == '>':
                condition_met = value > compare_value
            elif operator == '<':
                condition_met = value < compare_value
            elif operator == '>=':
                condition_met = value >= compare_value
            elif operator == '<=':
                condition_met = value <= compare_value
            else:
                condition_met = False
        else:
            condition_met = False
        
        # Рендеринг соответствующего блока
        block = self.true_block if condition_met else self.false_block
        return ''.join(node.render(context) for node in block)
    
    def _get_value(self, context: Dict[str, Any], var_name: str) -> Any:
        """Получение значения из контекста."""
        value = context
        for part in var_name.split('.'):
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return None
        return value

class ForNode(TemplateNode):
    """Узел цикла."""
    
    def __init__(self, var_name: str, iterable_name: str, body: list):
        self.var_name = var_name.strip()
        self.iterable_name = iterable_name.strip()
        self.body = body
    
    def render(self, context: Dict[str, Any]) -> str:
        # Получаем итерируемый объект
        iterable = self._get_value(context, self.iterable_name)
        
        if not iterable or not hasattr(iterable, '__iter__'):
            return ""
        
        result = []
        
        for i, item in enumerate(iterable):
            # Создаем контекст для итерации
            loop_context = context.copy()
            loop_context[self.var_name] = item
            loop_context['loop'] = {
                'index': i + 1,
                'index0': i,
                'first': i == 0,
                'last': i == len(list(iterable)) - 1,
                'length': len(list(iterable))
            }
            
            # Рендерим тело цикла
            result.append(''.join(node.render(loop_context) for node in self.body))
        
        return ''.join(result)
    
    def _get_value(self, context: Dict[str, Any], var_name: str) -> Any:
        """Получение значения из контекста."""
        value = context
        for part in var_name.split('.'):
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return None
        return value

class FilterRegistry:
    """Реестр фильтров."""
    
    def __init__(self):
        self.filters: Dict[str, Callable] = {}
        self._register_default_filters()
    
    def _register_default_filters(self):
        """Регистрация фильтров по умолчанию."""
        self.filters['upper'] = lambda x: x.upper() if x else ''
        self.filters['lower'] = lambda x: x.lower() if x else ''
        self.filters['capitalize'] = lambda x: x.capitalize() if x else ''
        self.filters['title'] = lambda x: x.title() if x else ''
        self.filters['length'] = lambda x: len(x) if hasattr(x, '__len__') else 0
        self.filters['default'] = lambda x, default='': x if x else default
        self.filters['date'] = lambda x, fmt='%Y-%m-%d': (
            x.strftime(fmt) if isinstance(x, (datetime, date)) else x
        )
    
    def register(self, name: str, filter_func: Callable):
        """Регистрация фильтра."""
        self.filters[name] = filter_func
    
    def apply(self, value: Any, filter_name: str, *args) -> Any:
        """Применение фильтра."""
        if filter_name not in self.filters:
            raise TemplateError(f"Filter '{filter_name}' not found")
        
        try:
            return self.filters[filter_name](value, *args)
        except Exception as e:
            raise TemplateError(f"Filter error: {str(e)}")

class TemplateParser:
    """Парсер шаблонов."""
    
    def __init__(self, filter_registry: Optional[FilterRegistry] = None):
        self.filter_registry = filter_registry or FilterRegistry()
        
        # Регулярные выражения для парсинга
        self.var_pattern = re.compile(r'\{\{\s*(.*?)\s*\}\}')
        self.tag_pattern = re.compile(r'\{%\s*(.*?)\s*%\}')
        self.if_pattern = re.compile(r'if\s+(.+?)\s*%\}')
        self.for_pattern = re.compile(r'for\s+(\w+)\s+in\s+(\w+)\s*%\}')
        self.end_pattern = re.compile(r'end(for|if)\s*%\}')
    
    def parse(self, template: str) -> list:
        """Парсинг шаблона."""
        nodes = []
        pos = 0
        
        while pos < len(template):
            # Ищем следующий тег
            var_match = self.var_pattern.search(template, pos)
            tag_match = self.tag_pattern.search(template, pos)
            
            # Выбираем ближайший тег
            matches = []
            if var_match:
                matches.append((var_match.start(), 'var', var_match))
            if tag_match:
                matches.append((tag_match.start(), 'tag', tag_match))
            
            if not matches:
                # Добавляем оставшийся текст
                nodes.append(TextNode(template[pos:]))
                break
            
            # Сортируем по позиции
            matches.sort(key=lambda x: x[0])
            next_pos, match_type, match = matches[0]
            
            # Добавляем текст до тега
            if next_pos > pos:
                nodes.append(TextNode(template[pos:next_pos]))
            
            if match_type == 'var':
                # Обработка переменной
                content = match.group(1)
                nodes.append(self._parse_variable(content))
                pos = match.end()
            else:
                # Обработка тега
                content = match.group(1)
                
                if content.startswith('if '):
                    # Парсинг блока if
                    if_match = self.if_pattern.match(match.group(0)[2:-2])
                    if if_match:
                        condition = if_match.group(1)
                        true_block, end_pos = self._parse_block(
                            template, match.end(), 'if'
                        )
                        # Парсим else если есть
                        else_pos = template.find('{% else %}', match.end(), end_pos)
                        
                        if else_pos != -1:
                            false_block, _ = self._parse_block(
                                template, else_pos + 10, 'if'
                            )
                            true_block = self.parse(template[match.end():else_pos])
                        else:
                            false_block = []
                        
                        nodes.append(IfNode(condition, true_block, false_block))
                        pos = end_pos
                        continue
                
                elif content.startswith('for '):
                    # Парсинг блока for
                    for_match = self.for_pattern.match(match.group(0)[2:-2])
                    if for_match:
                        var_name = for_match.group(1)
                        iterable_name = for_match.group(2)
                        body, end_pos = self._parse_block(
                            template, match.end(), 'for'
                        )
                        nodes.append(ForNode(var_name, iterable_name, body))
                        pos = end_pos
                        continue
                
                elif content.startswith('end'):
                    # Конец блока
                    pos = match.end()
                    continue
                
                # Неизвестный тег
                nodes.append(TextNode(match.group(0)))
                pos = match.end()
        
        return nodes
    
    def _parse_variable(self, content: str) -> TemplateNode:
        """Парсинг переменной с фильтрами."""
        parts = content.split('|')
        var_name = parts[0].strip()
        
        # Проверяем экранирование
        escape = True
        if var_name.startswith('safe '):
            var_name = var_name[5:].strip()
            escape = False
        
        # Применяем фильтры
        if len(parts) > 1:
            # В реальной реализации здесь будет цепочка фильтров
            # Для простоты берем последний фильтр
            filter_part = parts[-1].strip()
            filter_name = filter_part
            filter_args = []
            
            if '(' in filter_part and filter_part.endswith(')'):
                filter_name = filter_part.split('(')[0].strip()
                args_str = filter_part[len(filter_name)+1:-1]
                filter_args = [arg.strip() for arg in args_str.split(',')]
            
            # Создаем узел с фильтром
            return FilteredVariableNode(
                var_name, filter_name, filter_args, 
                self.filter_registry, escape
            )
        
        return VariableNode(var_name, escape)
    
    def _parse_block(self, template: str, start_pos: int, 
                    block_type: str) -> Tuple[list, int]:
        """Парсинг блока (if/for)."""
        depth = 1
        pos = start_pos
        
        while pos < len(template):
            # Ищем закрывающий тег
            end_match = self.end_pattern.search(template, pos)
            if not end_match:
                raise TemplateError(f"Unclosed {block_type} block")
            
            # Проверяем тип блока
            if end_match.group(1) == block_type:
                depth -= 1
                if depth == 0:
                    # Нашли соответствующий конец
                    block_content = template[start_pos:end_match.start()]
                    block_nodes = self.parse(block_content)
                    return block_nodes, end_match.end()
            else:
                # Вложенный блок
                depth += 1
            
            pos = end_match.end()
        
        raise TemplateError(f"Unclosed {block_type} block")

class FilteredVariableNode(TemplateNode):
    """Узел переменной с фильтром."""
    
    def __init__(self, var_name: str, filter_name: str, 
                 filter_args: list, registry: FilterRegistry,
                 escape: bool = True):
        self.var_name = var_name
        self.filter_name = filter_name
        self.filter_args = filter_args
        self.registry = registry
        self.escape = escape
    
    def render(self, context: Dict[str, Any]) -> str:
        # Получаем значение
        value = self._get_value(context, self.var_name)
        
        # Применяем фильтр
        filtered_value = self.registry.apply(
            value, self.filter_name, *self.filter_args
        )
        
        result = str(filtered_value) if filtered_value is not None else ""
        
        if self.escape and isinstance(result, str):
            result = html.escape(result)
        
        return result
    
    def _get_value(self, context: Dict[str, Any], var_name: str) -> Any:
        """Получение значения из контекста."""
        value = context
        for part in var_name.split('.'):
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return None
        return value

class TemplateEngine:
    """Движок шаблонов."""
    
    def __init__(self):
        self.filter_registry = FilterRegistry()
        self.parser = TemplateParser(self.filter_registry)
        self.cache: Dict[str, list] = {}
    
    def register_filter(self, name: str, filter_func: Callable):
        """Регистрация кастомного фильтра."""
        self.filter_registry.register(name, filter_func)
    
    def compile(self, template: str) -> list:
        """Компиляция шаблона."""
        cache_key = hash(template)
        if cache_key not in self.cache:
            self.cache[cache_key] = self.parser.parse(template)
        return self.cache[cache_key]
    
    def render(self, template: str, context: Dict[str, Any]) -> str:
        """Рендеринг шаблона с контекстом."""
        nodes = self.compile(template)
        return ''.join(node.render(context) for node in nodes)
    
    def render_from_file(self, filepath: str, context: Dict[str, Any]) -> str:
        """Рендеринг шаблона из файла."""
        with open(filepath, 'r', encoding='utf-8') as f:
            template = f.read()
        return self.render(template, context)
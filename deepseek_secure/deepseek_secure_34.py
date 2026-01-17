from typing import List, Dict, Set
import re
from collections import Counter
import pkgutil
import json

class SpellChecker:
    """Проверка орфографии."""
    
    def __init__(self, language: str = "en"):
        self.language = language
        self.dictionary: Set[str] = set()
        self._load_dictionary()
        
        # Статистика частоты букв для языка
        self.letter_frequency = self._get_letter_frequency()
    
    def _load_dictionary(self):
        """Загрузка словаря."""
        try:
            # Пробуем загрузить встроенный словарь
            dict_data = pkgutil.get_data(__name__, f"dictionaries/{self.language}.txt")
            if dict_data:
                words = dict_data.decode('utf-8').splitlines()
                self.dictionary = set(word.lower().strip() for word in words)
        except:
            # Используем минимальный словарь по умолчанию
            self.dictionary = self._get_basic_dictionary()
    
    def _get_basic_dictionary(self) -> Set[str]:
        """Базовый словарь."""
        basic_words = {
            "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
            "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
            "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
            "or", "an", "will", "my", "one", "all", "would", "there", "their", "what",
            "so", "up", "out", "if", "about", "who", "get", "which", "go", "me"
        }
        return basic_words
    
    def _get_letter_frequency(self) -> Dict[str, float]:
        """Частота букв в языке."""
        # Частоты для английского языка
        return {
            'e': 12.02, 't': 9.10, 'a': 8.12, 'o': 7.68, 'i': 7.31,
            'n': 6.95, 's': 6.28, 'r': 6.02, 'h': 5.92, 'd': 4.32,
            'l': 3.98, 'u': 2.88, 'c': 2.71, 'm': 2.61, 'f': 2.30,
            'y': 2.11, 'w': 2.09, 'g': 2.03, 'p': 1.82, 'b': 1.49,
            'v': 1.11, 'k': 0.69, 'x': 0.17, 'q': 0.11, 'j': 0.10, 'z': 0.07
        }
    
    def check(self, text: str) -> List[Dict]:
        """
        Проверка текста на опечатки.
        
        Returns:
            Список найденных ошибок с предложениями
        """
        # Извлекаем слова из текста
        words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
        
        errors = []
        for word in words:
            if word not in self.dictionary:
                suggestions = self._suggest_corrections(word)
                
                if suggestions:
                    errors.append({
                        'word': word,
                        'suggestions': suggestions,
                        'context': self._get_context(text, word)
                    })
        
        return errors
    
    def _suggest_corrections(self, word: str) -> List[str]:
        """Предложения по исправлению слова."""
        suggestions = []
        
        # 1. Проверяем опечатки с одной буквой
        for i in range(len(word)):
            # Удаление буквы
            deleted = word[:i] + word[i+1:]
            if deleted in self.dictionary:
                suggestions.append(deleted)
            
            # Вставка буквы
            for letter in 'abcdefghijklmnopqrstuvwxyz':
                inserted = word[:i] + letter + word[i:]
                if inserted in self.dictionary:
                    suggestions.append(inserted)
            
            # Замена буквы
            for letter in 'abcdefghijklmnopqrstuvwxyz':
                if letter != word[i]:
                    replaced = word[:i] + letter + word[i+1:]
                    if replaced in self.dictionary:
                        suggestions.append(replaced)
        
        # 2. Перестановка соседних букв
        for i in range(len(word)-1):
            swapped = word[:i] + word[i+1] + word[i] + word[i+2:]
            if swapped in self.dictionary:
                suggestions.append(swapped)
        
        # Ранжируем предложения по вероятности
        ranked = self._rank_suggestions(word, suggestions)
        
        return ranked[:5]  # Возвращаем топ-5 предложений
    
    def _rank_suggestions(self, original: str, suggestions: List[str]) -> List[str]:
        """Ранжирование предложений по вероятности."""
        if not suggestions:
            return []
        
        scored = []
        for suggestion in set(suggestions):  # Убираем дубли
            score = self._calculate_similarity(original, suggestion)
            scored.append((score, suggestion))
        
        # Сортируем по убыванию score
        scored.sort(reverse=True)
        return [suggestion for _, suggestion in scored]
    
    def _calculate_similarity(self, word1: str, word2: str) -> float:
        """Вычисление схожести слов."""
        # Используем расстояние Левенштейна и частоту букв
        distance = self._levenshtein_distance(word1, word2)
        
        # Учитываем частоту букв
        freq_score = 0
        for letter in word2:
            freq_score += self.letter_frequency.get(letter, 0)
        
        # Общий score (чем меньше расстояние и выше частотность - тем лучше)
        return 1.0 / (distance + 1) + freq_score / 100
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Расстояние Левенштейна между двумя строками."""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def _get_context(self, text: str, word: str, window: int = 30) -> str:
        """Получение контекста слова в тексте."""
        import re
        pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        match = pattern.search(text)
        
        if match:
            start = max(0, match.start() - window)
            end = min(len(text), match.end() + window)
            
            context = text[start:end]
            if start > 0:
                context = '...' + context
            if end < len(text):
                context = context + '...'
            
            return context
        
        return word
    
    def add_to_dictionary(self, word: str):
        """Добавление слова в словарь."""
        self.dictionary.add(word.lower())
    
    def batch_check(self, texts: List[str]) -> Dict[str, List]:
        """Пакетная проверка текстов."""
        results = {}
        for i, text in enumerate(texts):
            results[f"text_{i}"] = self.check(text)
        return results
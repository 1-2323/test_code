from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import networkx as nx
from abc import ABC, abstractmethod

class WorkflowStatus(str, Enum):
    """Статусы workflow."""
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class NodeType(str, Enum):
    """Типы узлов workflow."""
    START = "start"
    END = "end"
    TASK = "task"
    DECISION = "decision"
    PARALLEL = "parallel"
    MERGE = "merge"

@dataclass
class WorkflowNode:
    """Узел workflow."""
    id: str
    name: str
    node_type: NodeType
    config: Dict[str, Any] = field(default_factory=dict)
    
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение узла."""
        # В реальной системе здесь будет логика выполнения
        result = {
            'node_id': self.id,
            'node_name': self.name,
            'executed_at': datetime.now(),
            'status': 'success',
            'output': {}
        }
        
        # Добавляем вывод в контекст
        context[f"node_{self.id}_result"] = result
        return result

@dataclass
class WorkflowEdge:
    """Ребро workflow (переход)."""
    source_id: str
    target_id: str
    condition: Optional[str] = None

class Workflow:
    """Рабочий процесс."""
    
    def __init__(self, workflow_id: str, name: str):
        self.id = workflow_id
        self.name = name
        self.graph = nx.DiGraph()
        self.nodes: Dict[str, WorkflowNode] = {}
        self.status: WorkflowStatus = WorkflowStatus.DRAFT
    
    def add_node(self, node: WorkflowNode):
        """Добавление узла."""
        self.nodes[node.id] = node
        self.graph.add_node(node.id, node=node)
    
    def add_edge(self, edge: WorkflowEdge):
        """Добавление перехода."""
        if edge.source_id in self.nodes and edge.target_id in self.nodes:
            self.graph.add_edge(
                edge.source_id,
                edge.target_id,
                condition=edge.condition
            )
    
    def get_start_node(self) -> Optional[WorkflowNode]:
        """Получение стартового узла."""
        for node in self.nodes.values():
            if node.node_type == NodeType.START:
                return node
        return None
    
    def get_next_nodes(self, current_node_id: str, 
                      context: Dict[str, Any]) -> List[WorkflowNode]:
        """Получение следующих узлов."""
        next_nodes = []
        
        for successor in self.graph.successors(current_node_id):
            edge_data = self.graph.get_edge_data(current_node_id, successor)
            
            # Проверяем условие перехода если есть
            if edge_data and 'condition' in edge_data:
                condition = edge_data['condition']
                if condition and not self._evaluate_condition(condition, context):
                    continue
            
            node = self.nodes.get(successor)
            if node:
                next_nodes.append(node)
        
        return next_nodes
    
    def _evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """Вычисление условия."""
        try:
            # Безопасное вычисление выражения
            # В реальной системе используйте ast.literal_eval или собственную логику
            return True  # Заглушка
        except:
            return False
    
    def validate(self) -> List[str]:
        """Валидация workflow."""
        errors = []
        
        # Проверяем наличие стартового узла
        if not self.get_start_node():
            errors.append("Workflow must have a start node")
        
        # Проверяем наличие конечных узлов
        end_nodes = [n for n in self.nodes.values() if n.node_type == NodeType.END]
        if not end_nodes:
            errors.append("Workflow must have at least one end node")
        
        # Проверяем связность графа
        if not nx.is_weakly_connected(self.graph):
            errors.append("Workflow graph is not connected")
        
        return errors

class WorkflowExecutor:
    """Исполнитель workflow."""
    
    def __init__(self):
        self.active_workflows: Dict[str, Dict] = {}
    
    def start_workflow(self, workflow: Workflow, 
                      initial_context: Dict[str, Any] = None) -> str:
        """Запуск workflow."""
        import uuid
        
        execution_id = str(uuid.uuid4())
        
        start_node = workflow.get_start_node()
        if not start_node:
            raise ValueError("Workflow has no start node")
        
        self.active_workflows[execution_id] = {
            'workflow': workflow,
            'current_node': start_node,
            'context': initial_context or {},
            'history': [],
            'started_at': datetime.now(),
            'status': WorkflowStatus.ACTIVE
        }
        
        return execution_id
    
    def execute_step(self, execution_id: str) -> bool:
        """Выполнение одного шага workflow."""
        execution = self.active_workflows.get(execution_id)
        if not execution:
            return False
        
        workflow = execution['workflow']
        current_node = execution['current_node']
        context = execution['context']
        
        # Выполняем текущий узел
        result = current_node.execute(context)
        execution['history'].append(result)
        
        # Проверяем тип узла
        if current_node.node_type == NodeType.END:
            execution['status'] = WorkflowStatus.COMPLETED
            execution['completed_at'] = datetime.now()
            return False  # Workflow завершен
        
        # Получаем следующие узлы
        next_nodes = workflow.get_next_nodes(current_node.id, context)
        
        if not next_nodes:
            # Нет следующих узлов - workflow завершен с ошибкой
            execution['status'] = WorkflowStatus.FAILED
            execution['failed_at'] = datetime.now()
            return False
        
        # Переходим к следующему узлу (пока берем первый)
        if len(next_nodes) == 1:
            execution['current_node'] = next_nodes[0]
        else:
            # Для параллельных узлов нужно обрабатывать по-другому
            # В этой упрощенной версии берем первый
            execution['current_node'] = next_nodes[0]
        
        return True
    
    def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Получение статуса выполнения."""
        execution = self.active_workflows.get(execution_id)
        if not execution:
            return None
        
        workflow = execution['workflow']
        
        return {
            'execution_id': execution_id,
            'workflow_id': workflow.id,
            'workflow_name': workflow.name,
            'current_node': execution['current_node'].name,
            'status': execution['status'],
            'started_at': execution['started_at'],
            'completed_at': execution.get('completed_at'),
            'history_length': len(execution['history']),
            'context_keys': list(execution['context'].keys())
        }
    
    def cancel_execution(self, execution_id: str) -> bool:
        """Отмена выполнения."""
        if execution_id in self.active_workflows:
            execution = self.active_workflows[execution_id]
            execution['status'] = WorkflowStatus.CANCELLED
            execution['cancelled_at'] = datetime.now()
            return True
        return False
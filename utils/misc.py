import yaml
from typing import Dict, Any

def load_yaml(file_path: str) -> Dict[str, Any]:
    """加载YAML配置文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

__all__ = ['load_yaml']

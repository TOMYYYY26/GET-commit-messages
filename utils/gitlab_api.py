import requests
from typing import Optional
from .log import logger

class GitLabAPI:
    def __init__(self, api_root: str, token: str):
        self.api_root = api_root.rstrip('/')  # e.g. "http://10.219.8.231/api/v4"
        self.headers = {
            'PRIVATE-TOKEN': token,
            'Content-Type': 'application/json'
        }
        logger.debug(f"GitLabAPI初始化，根路径: {self.api_root}")

    def get_project_id(self, project_path: str) -> int:
        """通过项目路径获取数字ID"""
        url = f"{self.api_root}/projects"
        params = {'search': project_path, 'search_namespaces': True}
        
        logger.debug(f"查询项目URL: {url}, 参数: {params}")
        response = requests.get(url, headers=self.headers, params=params, timeout=10)
        
        logger.debug(f"响应状态码: {response.status_code}")
        if response.status_code != 200:
            raise ValueError(f"API请求失败: HTTP {response.status_code}")
            
        for project in response.json():
            if project['path_with_namespace'] == project_path:
                logger.debug(f"找到项目: ID={project['id']}")
                return project['id']
        
        raise ValueError(f"未找到项目: {project_path}")
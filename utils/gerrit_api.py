import requests
from urllib.parse import quote
import json
from typing import Dict, List, Optional
import logging

class GerritAPI:
    def __init__(self, api_root: str, username: str, password: str):
        """
        初始化Gerrit REST API客户端
        
        :param api_root: Gerrit API根地址 (e.g. "http://xx.xxx.xx.xxx:8080/a")
        :param username: Gerrit用户名
        :param password: HTTP密码 (从Settings->HTTP Password生成)
        """
        self.api_root = api_root.rstrip('/')
        self.auth = (username, password)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.verify = False  # 禁用SSL验证(测试环境)
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "GerritPythonClient/1.0"
        })
        logging.info(f"GerritAPI initialized for {self.api_root}")

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """统一处理API请求"""
        url = f"{self.api_root}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            # Gerrit API响应以)]}'开头需要去除
            content = response.text.lstrip(')]}\'\n')
            return json.loads(content)
        except requests.exceptions.RequestException as e:
            logging.error(f"API请求失败: {str(e)}")
            raise

    def get_projects(self) -> Dict:
        """获取所有项目列表"""
        return self._make_request("/projects/")

    def get_project_info(self, project_name: str) -> Dict:
        """
        获取特定项目信息
        
        :param project_name: 项目名称 
        """
        encoded_name = quote(project_name, safe='')
        return self._make_request(f"/projects/{encoded_name}")

    def get_changes(self, query: str, limit: int = 100) -> List[Dict]:
        """
        获取变更列表
        
        :param query: 查询条件 (e.g. "status:open+project:gerritDemo+branch:master")
        :param limit: 返回结果数量限制
        """
        params = {
            'q': query,
            'n': limit
        }
        return self._make_request("/changes/", params=params)

    def get_change_detail(self, change_id: str) -> Dict:
        """
        获取变更详情
        
        :param change_id: 变更ID 
        """
        return self._make_request(f"/changes/{change_id}/detail")

    def get_commits(self, project_name: str, branch: str = "master", limit: int = 100) -> List[Dict]:
        """
        获取项目提交历史
        
        :param project_name: 项目名称
        :param branch: 分支名称
        :param limit: 返回结果数量限制
        """
        encoded_project = quote(project_name, safe='')
        endpoint = f"/projects/{encoded_project}/commits/"
        params = {
            'branch': branch,
            'n': limit
        }
        return self._make_request(endpoint, params=params)

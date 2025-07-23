import requests
import yaml
from urllib.parse import quote
from requests.auth import HTTPBasicAuth
import argparse
import sys
from pprint import pprint


class GerritAPI:
    def __init__(self, config):
        self.base_url = config['gerrit_url'].rstrip('/')
        self.username = config['username']
        self.http_password = config['http_password']
        self.auth = HTTPBasicAuth(self.username, self.http_password)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({'Accept': 'application/json'})

    def get_changes(self, query="status:open", limit=10):
        """获取changes列表（返回完整信息）"""

        url = f"{self.base_url}/a/changes/?q={quote(query)}&n={limit}"
        response = self.session.get(url)
        self._check_response(response)
        return self._parse_gerrit_response(response.text)

    def get_change_details(self, change_id):
        """获取change详细信息"""
        url = f"{self.base_url}/a/changes/{quote(change_id)}/detail"
        response = self.session.get(url)
        self._check_response(response)
        return self._parse_gerrit_response(response.text)

    def get_change_diff(self, change_id):
        """获取change的代码修改内容"""
        # 首先获取当前revision（通常是最新的）
        details = self.get_change_details(change_id)
        current_revision = details['current_revision']
        
        # 获取修改的文件列表
        files_url = f"{self.base_url}/a/changes/{quote(change_id)}/revisions/{current_revision}/files/"
        response = self.session.get(files_url)
        self._check_response(response)
        files = self._parse_gerrit_response(response.text)
        
        # 获取每个文件的diff
        diffs = {}
        for file_path in files:
            if file_path == "/COMMIT_MSG":
                continue  # 跳过提交信息文件
            
            diff_url = f"{self.base_url}/a/changes/{quote(change_id)}/revisions/{current_revision}/files/{quote(file_path)}/diff"
            response = self.session.get(diff_url)
            self._check_response(response)
            diffs[file_path] = self._parse_gerrit_response(response.text)
        
        return diffs

    def _check_response(self, response):
        """检查响应状态"""
        if response.status_code != 200:
            error_msg = f"请求失败: {response.status_code}\n{response.text}"
            print(error_msg, file=sys.stderr)
            raise requests.HTTPError(error_msg)

    def _parse_gerrit_response(self, response_text):
        """处理Gerrit的特殊响应格式"""
        if response_text.startswith(")]}'"):
            return yaml.safe_load(response_text[4:])
        return yaml.safe_load(response_text)


def load_config(config_file='gerrit_config.yaml'):
    """加载配置文件"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"错误：配置文件 {config_file} 未找到", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"配置文件解析错误: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Gerrit自动化工具')
    parser.add_argument('--query', help='Gerrit查询语句，例如: "status:open project:myproject"')
    parser.add_argument('--limit', type=int, default=5, help='返回结果数量限制')
    parser.add_argument('--details', metavar='CHANGE_ID', help='获取指定Change ID的详细信息')
    parser.add_argument('--full', action='store_true', help='显示完整的change信息')
    parser.add_argument('--diff', metavar='CHANGE_ID', help='获取指定Change ID的代码修改内容')
    
    args = parser.parse_args()

    try:
        config = load_config()
        gerrit = GerritAPI(config)

        if args.diff:
            # 获取代码修改内容模式
            diffs = gerrit.get_change_diff(args.diff)
            print(f"\nChange {args.diff} 的代码修改内容:")
            for file_path, diff in diffs.items():
                print(f"\n文件: {file_path}")
                print("=" * 80)
                if 'content' in diff:
                    print(diff['content'])
                else:
                    pprint(diff)
        elif args.details:
            # 获取详细信息模式
            details = gerrit.get_change_details(args.details)
            print("\nChange详细信息:")
            pprint(details)
        else:
            # 查询模式
            query = args.query if args.query else config.get('default_query', 'status:open')
            print(f"执行查询: {query}")
            
            changes = gerrit.get_changes(query, args.limit)
            print(f"\n找到 {len(changes)} 个变更:")
            
            for i, change in enumerate(changes, 1):
                if args.full:
                    print(f"\n[{i}] 完整信息:")
                    pprint(change)
                else:
                    print(f"\n[{i}] {change['id']}")
                    print(f"项目: {change['project']} ({change['branch']})")
                    print(f"状态: {change['status']}")
                    print(f"标题: {change['subject']}")
            
            if changes and not args.full:
                print("\n提示: 使用 --details <Change ID> 查看详细信息")
                print("      使用 --diff <Change ID> 查看代码修改内容")
                print("      使用 --full 查看完整列表信息")

    except Exception as e:
        print(f"错误: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
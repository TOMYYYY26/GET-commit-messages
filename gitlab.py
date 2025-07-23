from typing import *
import json
from urllib.parse import urlparse, quote
import os
from pathlib import Path
import requests
from utils.log import logger
from utils.misc import load_yaml
from utils.gitlab_api import GitLabAPI
from datetime import datetime

logger.info('成功导入日志模块')

class GitLabCommitAnalyzer:
    def __init__(self, config=None):
        # 加载配置
        if config is None:
            self.config = load_yaml("configs/env.yaml")
        elif isinstance(config, str):
            self.config = load_yaml(config)
        elif isinstance(config, dict):
            self.config = config
        else:
            raise ValueError("config参数必须是路径(str)或配置字典(dict)")

        # 统一API根路径
        self.api_root = f"http://{self.config['GITLAB']['HOST']}/api/v4"
        logger.debug(f"API根路径: {self.api_root}")

        # 初始化Session
        self._s = requests.Session()
        self._s.headers.update({
            "PRIVATE-TOKEN": self.config['GITLAB']['TOKEN'],
            "Content-Type": "application/json"
        })
        self._s.verify = False  # 忽略SSL验证（仅测试环境）

        # 初始化API客户端
        self.api = GitLabAPI(self.api_root, self.config['GITLAB']['TOKEN'])
        
    def extract_project_path(self, url: str) -> str:
        """从URL提取项目路径"""
        parsed = urlparse(url)
        path = parsed.path.lstrip('/')
        return path[:-4] if path.endswith('.git') else path

    def get_project_id(self, project_url: str) -> int:
        """获取数字项目ID"""
        project_path = self.extract_project_path(project_url)
        logger.debug(f"提取的项目路径: {project_path}")
        return self.api.get_project_id(project_path)

    def initialize_project(self, target: dict) -> None:
        """初始化项目信息"""
        self.ref = target['branch']
        self.project_path = self.extract_project_path(target['path'])
        self.project_id = self.get_project_id(target['path'])
        logger.info(f"初始化项目: ID={self.project_id}, 分支={self.ref}")

    def get_commits(self, limit: int = 100) -> List[dict]:
        """获取提交历史"""
        try:
            endpoint = (
                f"{self.api_root}/projects/{self.project_id}/repository/commits"
                f"?ref_name={quote(self.ref, safe='')}&per_page={limit}"
            )
            
            logger.debug(f"请求端点: {endpoint}")
            response = self._s.get(endpoint)
            
            if 'application/json' not in response.headers.get('Content-Type', ''):
                raise ValueError(f"响应不是JSON: {response.text[:200]}...")
                
            return response.json()
        except Exception as e:
            logger.error(f"获取提交失败: {str(e)}")
            raise
    
    def get_commit_diff(self, commit_id: str) -> List[dict]:
        """获取commit差异数据"""
        endpoint = f"{self.api_root}/projects/{self.project_id}/repository/commits/{commit_id}/diff"
        return self._s.get(endpoint).json()
    
    def generate_diff_report(self, commit_id: str, output_dir: str = "diff_reports") -> dict:
        """
        生成完整的差异报告并保存到文件
        返回结构:
        {
            "status": "success"|"error",
            "commit_id": str,
            "report_path": str,
            "files_changed": List[str],
            "error": Optional[str]
        }
        """
        result = {
            "status": "success",
            "commit_id": commit_id,
            "report_path": "",
            "files_changed": [],
            "error": None
        }

        try:
            # 确保输出目录存在
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
            # 获取差异数据
            diffs = self.get_commit_diff(commit_id)
            if not diffs:
                raise ValueError("没有找到差异数据")
            
            # 创建报告文件
            report_file = Path(output_dir) / f"diff_report_{commit_id[:8]}.json"
            report_data = {
                "commit_id": commit_id,
                "timestamp": str(datetime.now()),
                "diffs": diffs,
                "files": []
            }

            # 处理每个文件的差异
            for diff in diffs:
                file_info = {
                    "old_path": diff.get('old_path'),
                    "new_path": diff.get('new_path'),
                    "change_type": "added" if diff.get('new_file') else 
                                 "deleted" if diff.get('deleted_file') else 
                                 "renamed" if diff.get('renamed_file') else "modified",
                    "diff": diff.get('diff', '')
                }
                report_data["files"].append(file_info)
                result["files_changed"].append(file_info["new_path"] or file_info["old_path"])

            # 保存报告
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
            
            result["report_path"] = str(report_file.absolute())
            logger.info(f"差异报告已保存到: {result['report_path']}")
            return result

        except Exception as e:
            logger.error(f"生成差异报告失败: {str(e)}")
            result.update({
                "status": "error",
                "error": str(e)
            })
            return result

    def save_raw_diff_files(self, commit_id: str, output_dir: str = "raw_diffs") -> dict:
        """
        保存原始diff文件到指定目录
        返回结构:
        {
            "status": "success"|"error",
            "commit_id": str,
            "output_dir": str,
            "saved_files": List[str],
            "error": Optional[str]
        }
        """
        result = {
            "status": "success",
            "commit_id": commit_id,
            "output_dir": os.path.abspath(output_dir),
            "saved_files": [],
            "error": None
        }

        try:
            # 获取差异数据
            diffs = self.get_commit_diff(commit_id)
            
            # 确保输出目录存在
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
            # 保存每个文件的diff
            for diff in diffs:
                old_path = diff.get('old_path', '')
                new_path = diff.get('new_path', '')
                diff_content = diff.get('diff', '')
                
                # 确定文件名
                filename = new_path if new_path else old_path
                if not filename:
                    continue
                    
                # 创建安全文件名
                safe_name = filename.replace('/', '_')
                output_file = Path(output_dir) / f"{safe_name}.diff"
                
                # 写入diff内容
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(f"--- {old_path}\n+++ {new_path}\n{diff_content}")
                
                result["saved_files"].append(str(output_file))
            
            logger.info(f"已保存 {len(result['saved_files'])} 个差异文件到 {output_dir}")
            return result

        except Exception as e:
            logger.error(f"保存原始diff文件失败: {str(e)}")
            result.update({
                "status": "error",
                "error": str(e)
            })
            return result

def main():
    try:
        # 加载配置
        config = load_yaml("configs/env.yaml")
        
        # 初始化分析器
        analyzer = GitLabCommitAnalyzer(config)
        analyzer.initialize_project(config["PROJECT"])
        
        # 获取最近的100条commits
        commits = analyzer.get_commits(limit=10)
        if not commits:
            logger.error("没有找到任何commits")
            return
        
        total_commits_processed = 0
        total_files_changed = 0
        failed_commits = []
        
        print("\n" + "="*50)
        print(f"开始分析 {len(commits)} 条commits的差异")
        print("="*50 + "\n")
        
        # 处理每条commit
        for commit in commits:
            commit_id = commit['id']
            commit_msg = commit['message'].strip()
            
            try:
                logger.info(f"正在处理 commit: {commit_id[:8]} - {commit_msg}")
                
                # 为每个commit创建独立目录
                commit_output_dir = f"diff_reports/commit_{commit_id[:8]}"
                
                # 生成差异报告
                report_result = analyzer.generate_diff_report(commit_id, commit_output_dir)
                if report_result["status"] != "success":
                    raise RuntimeError(f"生成报告失败: {report_result['error']}")
                
                # 保存原始diff文件
                diff_result = analyzer.save_raw_diff_files(commit_id, commit_output_dir)
                if diff_result["status"] != "success":
                    raise RuntimeError(f"保存diff文件失败: {diff_result['error']}")
                
                # 统计信息
                files_changed = len(diff_result["saved_files"])
                total_files_changed += files_changed
                total_commits_processed += 1
                
                print(f"Commit {commit_id[:8]} 处理完成, 修改文件数: {files_changed}")
                
            except Exception as e:
                logger.error(f"处理commit {commit_id[:8]} 时出错: {str(e)}")
                failed_commits.append({
                    "commit_id": commit_id,
                    "error": str(e)
                })
                continue
        
        # 打印最终摘要
        print("\n" + "="*50)
        print("分析完成摘要:")
        print(f"成功处理的commits数量: {total_commits_processed}/{len(commits)}")
        print(f"累计修改文件总数: {total_files_changed}")
        print(f"失败的commits数量: {len(failed_commits)}")
        
        if failed_commits:
            print("\n失败的commits列表:")
            for fail in failed_commits:
                print(f" - {fail['commit_id'][:8]}: {fail['error']}")
        
        print("="*50 + "\n")
        
        # 保存汇总报告
        summary_report = {
            "total_commits": len(commits),
            "processed_commits": total_commits_processed,
            "failed_commits": failed_commits,
            "total_files_changed": total_files_changed,
            "timestamp": str(datetime.now())
        }
        
        with open("diff_reports/summary_report.json", "w", encoding="utf-8") as f:
            json.dump(summary_report, f, indent=2, ensure_ascii=False)
            
        print(f"汇总报告已保存到: diff_reports/summary_report.json")
        
    except Exception as e:
        logger.error(f"程序运行失败: {str(e)}")
        raise

if __name__ == "__main__":
    main()
import requests
import base64
import json
import os
import re
import csv
import yaml
from urllib.parse import quote
from typing import List, Dict, Tuple
from openai import OpenAI  # 修改为使用OpenAI兼容接口


class GerritClient:
    def __init__(self, config_path="gerrit_AI_config.yaml"):
        # 从YAML文件加载配置
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        self.host = self.config["host"]
        self.session = requests.Session()
        self.session.auth = (self.config["username"], self.config["password"])
        self.session.headers.update({
            'Accept': 'text/plain',
            'X-Gerrit-Auth': 'X'
        })
        # 初始化阿里云百炼API客户端
        self.ai_client = OpenAI(
            api_key=self.config["api_key"],
            base_url=self.config["base_url"]
        )

    def _make_gerrit_request(self, url: str) -> dict:
        """处理Gerrit的特殊响应格式"""
        response = self.session.get(url)
        if response.status_code == 200:
            content = response.text.strip()
            if content.startswith(")]}'"):
                return json.loads(content[4:])
            return json.loads(content)
        raise Exception(f"请求失败: HTTP {response.status_code}")

    def get_project_changes(self, project_name: str, limit: int = 500) -> list:
        """获取项目的所有变更列表"""
        url = f"http://{self.host}/a/changes/?q=project:{project_name}+status:merged&n={limit}"
        return self._make_gerrit_request(url)

    def get_change_files(self, change_id: str) -> list:
        """获取变更中所有修改的文件"""
        url = f"http://{self.host}/a/changes/{change_id}/revisions/current/files/"
        files = self._make_gerrit_request(url)
        return [file_path for file_path in files.keys() if file_path != "/COMMIT_MSG"]

    def get_well_formatted_patch(self, change_id: str, file_path: str) -> str:
        """获取格式良好的patch内容"""
        encoded_path = quote(file_path, safe='')
        url = f"http://{self.host}/a/changes/{change_id}/revisions/current/patch?path={encoded_path}"
        
        response = self.session.get(url)
        if not response.ok:
            raise Exception(f"获取patch失败: HTTP {response.status_code}")
        
        try:
            decoded = base64.b64decode(response.text).decode('utf-8')
        except:
            decoded = response.text
        
        return decoded.replace('\r\n', '\n').replace('\r', '\n') + ('\n' if not decoded.endswith('\n') else '')

    def _analyze_bug_with_ai(self, diff_content: str, change_subject: str) -> Tuple[bool, str, str]:
        """
        使用阿里云百炼(qwen-plus)模型分析bug类型和描述
        返回: (是否有效bug, bug类型, bug描述)
        """
        if not diff_content:
            return False, "", ""

        # 构造提示词
        prompt = f"""
        请严格分析以下代码变更是否是一个高价值的bug修复，并按要求回答。

        变更描述: {change_subject}
        代码变更:{diff_content}

        请按以下格式回答，必须严格遵循格式：
        [判断]是/否
        [类型]bug类型
        [描述]一句话描述

        判断标准:
        1. 如果是格式调整、注释修改、import优化等非功能性变更或需求、功能缺失类变更，判断为"否"
        2. 如果是修复了明确的逻辑错误、异常处理、边界条件等问题，判断为"是"
        3. 如果无法确定或变更不明显，判断为"否"

        示例:
        [判断]是
        [类型]空指针异常
        [描述]修复了在未初始化情况下可能导致的空指针异常

        [判断]否
        [类型]功能缺失/功能增加
        [描述]修复了车窗无法关闭的问题
        """

        try:
            response = self.ai_client.chat.completions.create(
                model=self.config["model_name"],
                messages=[
                    {"role": "system", "content": "你是一个严谨的代码审查助手，需要严格分析代码变更是否是高价值bug修复。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=100
            )
            
            answer = response.choices[0].message.content.strip()
            
            # 解析AI回答
            is_bug = False
            bug_type = ""
            bug_desc = ""
            
            if "[判断]是" in answer:
                is_bug = True
            
            type_match = re.search(r'\[类型\](.*)', answer)
            if type_match:
                bug_type = type_match.group(1).strip()
            
            desc_match = re.search(r'\[描述\](.*)', answer)
            if desc_match:
                bug_desc = desc_match.group(1).strip()
            
            return is_bug, bug_type, bug_desc
        except Exception as e:
            print(f"调用AI API失败: {e}")
            return False, "", ""

    def filter_bug_fixes(
        self,
        changes: List[Dict],
        bug_keywords: List[str] = ["Bug", "BUG", "bug"]
    ) -> List[Dict]:
        """
        严格的两步筛选：
        1. 先通过关键词筛选变更
        2. 使用大模型API进行严格的低价值修改判断
        """
        result = []
        keyword_pattern = re.compile('|'.join(bug_keywords), re.IGNORECASE)

        # 第一步：关键词筛选
        keyword_matched_changes = [
            change for change in changes
            if keyword_pattern.search(change.get("subject", ""))
        ]

        print(f"找到 {len(keyword_matched_changes)} 个关键词匹配的变更，开始AI筛选...")

        # 第二步：使用AI进行严格的低价值修改判断
        for i, change in enumerate(keyword_matched_changes, 1):
            change_id = change["id"]
            files = self.get_change_files(change_id)
            valuable_files = []

            print(f"\n处理变更 {i}/{len(keyword_matched_changes)}: {change['subject']}")

            for file_path in files:
                try:
                    patch = self.get_well_formatted_patch(change_id, file_path)
                    bad_code = self._extract_bad_code(patch)
                    good_code = self._extract_good_code(patch)
                    
                    # 检查 bad_code 和 good_code 是否为空
                    if not bad_code.strip() or not good_code.strip():
                        print(f"  ❌ 文件 {file_path} 被识别为低价值变更 (空代码)")
                        continue
                    
                    is_bug, bug_type, bug_desc = self._analyze_bug_with_ai(patch, change["subject"])
                    
                    if is_bug:
                        valuable_files.append({
                            "path": file_path,
                            "patch": patch,
                            "bug_type": bug_type,
                            "bug_desc": bug_desc,
                            "bad_code": bad_code,
                            "good_code": good_code
                        })
                        print(f"  ✅ 文件 {file_path} 被识别为有效bug修复")
                        print(f"    类型: {bug_type}")
                        print(f"    描述: {bug_desc}")
                    else:
                        print(f"  ❌ 文件 {file_path} 被识别为低价值变更")
                except Exception as e:
                    print(f"  ⚠️ 处理文件 {file_path} 时出错: {e}")
                    continue

            if valuable_files:
                matched_keywords = keyword_pattern.findall(change.get("subject", ""))
                result.append({
                    "change_id": change_id,
                    "number": change["_number"],
                    "subject": change.get("subject", ""),
                    "files": valuable_files,
                    "matched_keywords": list(set(matched_keywords)),
                    "url": f"http://{self.host}/{change['_number']}"
                })

        return result

    def _extract_bad_code(self, patch: str) -> str:
        """从patch中提取被删除的代码(坏代码)"""
        bad_lines = []
        for line in patch.split('\n'):
            if line.startswith('-') and not line.startswith('---'):
                bad_lines.append(line[1:])
        return '\n'.join(bad_lines)

    def _extract_good_code(self, patch: str) -> str:
        """从patch中提取新增的代码(好代码)"""
        good_lines = []
        for line in patch.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                good_lines.append(line[1:])
        return '\n'.join(good_lines)

    def download_bugfix_patches(
        self,
        project_name: str,
        output_dir: str = "strict_bugfixes",
        bug_keywords: List[str] = None,
        max_retries: int = 3
    ):
        """严格模式下载Bug修复patch"""
        os.makedirs(output_dir, exist_ok=True)
        
        if bug_keywords is None:
            bug_keywords = ["Bug", "BUG", "bug", "错误", "修复"]

        print(f"严格模式扫描项目 {project_name}...")
        print("筛选流程: 1.关键词匹配 → 2.AI判断是否为真实bug修复")
        changes = self.get_project_changes(project_name)
        bugfix_changes = self.filter_bug_fixes(changes, bug_keywords)
        
        print(f"\n找到 {len(bugfix_changes)} 个有效Bug修复变更:")
        
        # 准备CSV表格数据
        csv_data = []
        
        for change in bugfix_changes:
            print(f"\n🔍 变更 {change['number']}: {change['subject']}")
            print(f"  匹配关键词: {', '.join(change['matched_keywords'])}")
            print(f"  有效文件: {len(change['files'])}")
            print(f"  链接: {change['url']}")

            for file in change["files"]:
                filename = f"{change['number']}_{file['path'].replace('/', '_')}.patch"
                file_path = os.path.join(output_dir, filename)
                
                # 添加重试机制
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(file["patch"])
                        print(f"  ✅ 保存: {filename}")
                        
                        # 添加到CSV数据
                        csv_data.append({
                            "bad_code": file["bad_code"],
                            "good_code": file["good_code"],
                            "bug_type": file["bug_type"],
                            "bug_analysis": file["bug_desc"],
                            "file_path": file["path"],
                            "change_id": change["change_id"],
                            "change_number": change["number"],
                            "change_subject": change["subject"]
                        })
                        break
                    except Exception as e:
                        retry_count += 1
                        print(f"  ⚠️ 保存文件 {filename} 失败 (尝试 {retry_count}/{max_retries}): {e}")
                        if retry_count == max_retries:
                            print(f"  ❌ 无法保存文件 {filename}")

        # 保存CSV表格
        csv_path = os.path.join(output_dir, "bugfix_analysis.csv")
        if csv_data:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ["bad_code", "good_code", "bug_type", "bug_analysis", 
                            "file_path", "change_id", "change_number", "change_subject"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_data)
            print(f"\n✅ 已保存分析结果到: {csv_path}")

        print(f"\n严格模式完成！有效patch保存在: {os.path.abspath(output_dir)}")


if __name__ == "__main__":
    # 加载配置文件
    config_path = "gerrit_AI_config.yaml"  # 或者使用绝对路径
    
    client = GerritClient(config_path)
    
    # 执行严格模式下载
    client.download_bugfix_patches(
        project_name=client.config['project_name'],
        bug_keywords=["Bug", "BUG", "bug"]
    )
import pandas as pd
import csv
import time
import yaml
from openai import OpenAI


class AICodeReviewer:
    def __init__(self, config_path="AI_check_config.yaml"):
        # 从YAML文件加载配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 初始化阿里云百炼API客户端
        self.ai_client = OpenAI(
            api_key=config["api_key"],
            base_url=config["base_url"]
        )
        self.model_name = config["model_name_1"]

    # 第一次评审：检查bad_code是否正确
    def first_review(self, bad_code):
        prompt = f"""你是一个专业的代码评审员：
请检查以下代码是否存在错误：

{bad_code}

请只回答"对"或"错"，不要添加其他解释。"""
        
        try:
            response = self.ai_client.chat.completions.create(
                model=self.model_name,  # 使用配置文件中的模型名称
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.1
            )
            result = response.choices[0].message.content.strip()
            return result
        except Exception as e:
            print(f"Error in first review: {e}")
            return "错"  # 默认认为是错误的

    # 如果第一次评审结果为"错"，则生成修正代码
    def generate_fixed_code(self, bad_code):
        prompt = f"""你是一个专业的代码工程师:
以下代码存在错误：

{bad_code}

请修复以上代码中的错误，并只返回修复后的代码，不要添加任何解释或其他内容。"""
        
        try:
            response = self.ai_client.chat.completions.create(
                model=self.model_name,  # 使用配置文件中的模型名称
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.3
            )
            fixed_code = response.choices[0].message.content.strip()
            return fixed_code
        except Exception as e:
            print(f"Error in generating fixed code: {e}")
            return bad_code  # 出错时返回原始代码

    # 第二次评审：比较AI修正代码与正确代码的相似度并评分
    def second_review(self, ai_code, good_code, bad_code, bug_analysis):
        prompt = f"""你是一个专业严格的代码评审员
        
通过与good_code(正确)和bad_code(有Bug)对比, 评估ai_code对bug的修复成功度，并给出0-100的评分。
同时，请判断这组代码（bad_code, good_code, bug_analysis）是否适合作为微调"代码评审大模型"的训练集。请回答"是"或"否"。

原始错误代码：{bad_code}
错误分析：{bug_analysis}
人工修正的正确代码：
{good_code}
AI修正代码：
{ai_code}

请先返回评分数字，然后换行返回是否适合作为训练集（是/否）。不要添加其他解释。"""
        
        try:
            response = self.ai_client.chat.completions.create(
                model=self.model_name,  # 使用配置文件中的模型名称
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.1  # 降低温度参数以获得更一致的评分
            )
            result = response.choices[0].message.content.strip().split('\n')
            score = int(result[0])
            is_suitable = result[1] if len(result) > 1 else "否"
            return score, is_suitable
        except Exception as e:
            print(f"Error in second review: {e}")
            return 0, "否"  # 出错时返回0分和否


# 读取CSV文件
def read_csv_data(file_path):
    df = pd.read_csv(file_path)
    return df


# 主函数
def main():
    # 创建AI代码评审器实例，传入配置文件路径
    reviewer = AICodeReviewer("AI_check_config.yaml")
    
    # 读取数据
    file_path = "strict_bugfixes/bugfix_analysis.csv"
    df = read_csv_data(file_path)
    
    # 添加新列用于存储结果
    df['first_review'] = ''
    df['ai_code'] = ''
    df['similarity_score'] = 0
    df['suitable_for_training'] = ''
    
    # 处理每一行数据
    for index, row in df.iterrows():
        bad_code = row['bad_code']
        good_code = row['good_code']
        bug_analysis = row['bug_analysis']  
        
        # 跳过空行
        if pd.isna(bad_code) or pd.isna(good_code):
            continue
        
        print(f"Processing row {index+1}/{len(df)}")
        
        # 第一次评审
        first_result = reviewer.first_review(bad_code)
        df.at[index, 'first_review'] = first_result
        
        # 如果第一次评审结果为"错"，则生成修正代码
        if first_result == "错":
            ai_code = reviewer.generate_fixed_code(bad_code)
            df.at[index, 'ai_code'] = ai_code
            
            # 第二次评审：计算相似度评分
            score, is_suitable = reviewer.second_review(ai_code, good_code, bad_code, bug_analysis)
            df.at[index, 'similarity_score'] = score
            df.at[index, 'suitable_for_training'] = is_suitable
        else:
            # 如果第一次评审结果为"对"，则不需要修正，相似度为100
            df.at[index, 'ai_code'] = bad_code
            df.at[index, 'similarity_score'] = 100
            df.at[index, 'suitable_for_training'] = "是"
        
        # 添加延迟以避免API调用频率过高
        time.sleep(1)
    
    # 保存结果到新的CSV文件
    df.to_csv("strict_bugfixes/bugfix_analysis_results.csv", index=False, quoting=csv.QUOTE_ALL)
    print("Processing complete. Results saved to bugfix_analysis_results.csv")


if __name__ == "__main__":
    main()
# dongchedi_analyzer_engine.py
# -*- coding: utf-8 -*-
"""
懂车帝评论大模型分析引擎（专用版）
封装 run_dongchedi_analysis 函数，供 Flask Web 框架调用
处理懂车帝原生 CSV 格式（评分_XXX、评论内容等字段）
"""

import os
import json
import time
import pandas as pd
from openai import OpenAI
import concurrent.futures
import re
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not API_KEY:
    raise RuntimeError("未设置 DEEPSEEK_API_KEY，请在 .env 文件中定义或设置环境变量")

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY", API_KEY),
    base_url="https://api.deepseek.com",
    timeout=60.0,
)

MODEL = "deepseek-chat"
MAX_WORKERS = 5
RETRY_TIMES = 2
RETRY_DELAY_BASE = 0.5
REQUEST_DELAY = 0.2
MIN_COMMENT_LENGTH = 20
DEBUG = True

# 懂车帝评分列 → 标准评分列 映射
DC_SCORE_MAP = {
    '评分_空间': '空间评分', '评分_驾驶感受': '驾驶感受评分',
    '评分_续航': '续航评分', '评分_外观': '外观评分',
    '评分_内饰': '内饰评分', '评分_性价比': '性价比评分',
    '评分_智能化': '智能化评分', '评分_油耗': '油耗评分',
    '评分_配置': '配置评分',
    '评分_动力': '动力评分', '评分_操控': '操控评分', '评分_舒适': '舒适评分',
}

# ========== 计算总评分 ==========
def calculate_total_score(row):
    score_columns = DC_SCORE_MAP.values()
    valid_scores = []
    for col in score_columns:
        if col in row and pd.notna(row[col]):
            try:
                val = float(row[col])
                if 0 <= val <= 10:
                    valid_scores.append(val)
            except (ValueError, TypeError):
                pass
    if not valid_scores:
        return None
    return round(sum(valid_scores) / 7.0, 2)


# ========== 系统提示词（与汽车之家共用） ==========
SYSTEM_PROMPT = """
你是一个专业的汽车评论分析助手。请仔细阅读用户提供的汽车评论，从中提取以下五类结构化信息：

1. **使用场景**：用户提到的主要用车场景（如上下班通勤、接送小孩、自驾游、家庭出行、购物、商务接待等）。每条评论可能包含多个场景，请全部提取。
2. **满意点**：用户明确表示满意的方面。每个满意点需包含两个字段：
   - 满意领域：从以下列表中选择（空间、驾驶感受、续航、外观、内饰、性价比、智能化、动力、操控、舒适、配置、服务、品牌等）。
   - 满意点：具体描述满意的内容（一句话，直接摘录或概括，保留关键信息）。
3. **不满意点**：用户明确表示不满意的方面。每个不满意点需包含：
   - 不满意领域：同上领域列表。
   - 不满意点：具体描述不满意的内容。
4. **改进建议**：用户明确提出的改进期望或建议。每个建议需包含：
   - 改进领域：同上领域列表。
   - 改进建议：具体建议内容。
5. **对比车型**：用户提到的其他车型与当前车型的对比信息。每个对比需包含：
   - 对比车型名称：标准化的车型名称（如"理想L6"、"问界M7"）。
   - 对比内容：用户关于对比的描述句子（完整摘录或准确概括）。

**注意**：
- 如果评论中未提及某项信息，则对应字段返回空数组。
- 输出必须是严格的 JSON 格式，包含以下五个键：
  - "scenes" (字符串数组)
  - "satisfactions" (对象数组，每个对象含 "domain" 和 "point")
  - "dissatisfactions" (对象数组，每个对象含 "domain" 和 "point")
  - "suggestions" (对象数组，每个对象含 "domain" 和 "suggestion")
  - "comparisons" (对象数组，每个对象含 "model" 和 "content")
- 只输出 JSON，不要包含任何解释性文字。
"""


# ========== JSON 解析辅助函数 ==========
def safe_parse_json(content):
    if not content:
        raise ValueError("内容为空")
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass
    try:
        repaired = repair_json(content)
        return json.loads(repaired)
    except:
        pass
    raise ValueError(f"无法解析 JSON，原始内容前200字符: {content[:200]}")


def repair_json(broken):
    stack = []
    fixed = []
    in_string = False
    escape = False
    for ch in broken:
        if in_string:
            fixed.append(ch)
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            fixed.append(ch)
            continue
        if ch in '{[':
            stack.append(ch)
            fixed.append(ch)
        elif ch in '}]':
            if stack:
                last = stack[-1]
                if (last == '{' and ch == '}') or (last == '[' and ch == ']'):
                    stack.pop()
                    fixed.append(ch)
        else:
            fixed.append(ch)
    while stack:
        last = stack.pop()
        fixed.append('}' if last == '{' else ']')
    return ''.join(fixed)


# ========== 核心分析函数 ==========
def analyze_comment(comment_text, retries=RETRY_TIMES):
    if not comment_text or not isinstance(comment_text, str) or len(comment_text.strip()) < MIN_COMMENT_LENGTH:
        return {"scenes": [], "satisfactions": [], "dissatisfactions": [], "suggestions": [], "comparisons": []}

    user_prompt = f"请分析以下汽车评论：\n{comment_text}"
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=2000,
                timeout=60,
            )
            content = response.choices[0].message.content
            if DEBUG:
                print(f"📥 模型返回长度: {len(content)} 字符")
            result = safe_parse_json(content)
            default = {"scenes": [], "satisfactions": [], "dissatisfactions": [], "suggestions": [], "comparisons": []}
            for key in default:
                if key not in result:
                    result[key] = default[key]
            return result
        except Exception as e:
            print(f"❌ 第{attempt+1}次调用失败: {type(e).__name__}: {e}")
            if attempt == retries - 1:
                print(f"🚫 最终失败，评论长度: {len(comment_text)}")
            else:
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                time.sleep(delay)
    return {"scenes": [], "satisfactions": [], "dissatisfactions": [], "suggestions": [], "comparisons": []}


# ========== 生成摘要 ==========
def generate_summary(df_raw, df_satisfactions, df_dissatisfactions):
    total_score = df_raw["总评分"].mean()
    total_score = round(total_score, 2) if pd.notna(total_score) else None
    if not df_satisfactions.empty:
        top_satis = df_satisfactions["满意领域"].value_counts().idxmax()
    else:
        top_satis = "无"
    if not df_dissatisfactions.empty:
        top_diss = df_dissatisfactions["不满意领域"].value_counts().idxmax()
    else:
        top_diss = "无"
    summary_text = f"综合分析 {len(df_raw)} 条懂车帝口碑，综合评分 {total_score or '暂无'}。最满意的方面是【{top_satis}】，主要不满集中在【{top_diss}】。"
    return {
        "total_score": total_score,
        "satisfactions_top": top_satis,
        "dissatisfactions_top": top_diss,
        "summary_text": summary_text
    }


# ========== 主分析函数（入口） ==========
def run_dongchedi_analysis(input_csv, output_xlsx, progress_callback):
    progress_callback(0, "正在读取懂车帝数据...")
    try:
        df_raw = pd.read_csv(input_csv, encoding='utf-8-sig')
    except Exception as e:
        raise ValueError(f"读取CSV失败: {e}")

    # ---- 评分预处理：评分_XXX → XXX评分 ----
    for dc_col, std_col in DC_SCORE_MAP.items():
        if dc_col in df_raw.columns:
            df_raw[std_col] = pd.to_numeric(df_raw[dc_col], errors='coerce')

    # ---- 字段预处理 ----
    if "点评车型" in df_raw.columns:
        df_raw["车型版本"] = df_raw["点评车型"].fillna("").astype(str)
    else:
        df_raw["车型版本"] = ""
    if "车型名称" not in df_raw.columns:
        raise ValueError("CSV中缺少'车型名称'列")
    if "提车时间" in df_raw.columns:
        df_raw["发表时间"] = df_raw["提车时间"].fillna("").astype(str)
    if "用户昵称" not in df_raw.columns:
        df_raw["用户昵称"] = "懂车帝用户"
    df_raw.rename(columns={"用户昵称": "用户名"}, inplace=True)

    df_raw["车型名称"] = df_raw["车型名称"].fillna("").astype(str).str.strip()
    df_raw["车型版本"] = df_raw["车型版本"].fillna("").astype(str).str.strip()

    progress_callback(10, "正在计算总评分...")
    df_raw["总评分"] = df_raw.apply(calculate_total_score, axis=1)

    progress_callback(15, "正在提取评论文本...")
    # 懂车帝评论内容已在"评论内容"列中，直接使用
    if "评论内容" in df_raw.columns:
        df_raw["评论内容"] = df_raw["评论内容"].fillna("").astype(str)
    else:
        raise ValueError("CSV中缺少'评论内容'列")

    df = df_raw[df_raw["评论内容"].str.strip() != ""].copy()
    df = df[df["评论内容"].str.len() >= MIN_COMMENT_LENGTH].copy()
    if len(df) == 0:
        raise ValueError("没有符合条件的有效评论")

    # 初始化结果容器
    scenes_data = []
    satisfactions_data = []
    dissatisfactions_data = []
    suggestions_data = []
    comparisons_data = []

    comment_items = []
    for idx, row in df.iterrows():
        username = row["用户名"]
        model_name = row["车型名称"]
        model_version = row.get("车型版本", "")
        if isinstance(model_version, float) or model_version == "nan":
            model_version = ""
        total_score = row.get("总评分", "")
        if pd.isna(total_score):
            total_score = ""
        else:
            total_score = str(total_score)
        comment = row["评论内容"]
        comment_items.append((idx, username, model_name, str(model_version), total_score, comment))

    progress_callback(20, "开始AI分析...")
    total_tasks = len(comment_items)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(analyze_comment, comment): (idx, username, model_name, model_version, score, comment)
            for idx, username, model_name, model_version, score, comment in comment_items
        }
        completed = 0
        for future in concurrent.futures.as_completed(future_to_item):
            completed += 1
            idx, username, model_name, model_version, score, comment = future_to_item[future]
            try:
                result = future.result()
            except Exception:
                result = {"scenes": [], "satisfactions": [], "dissatisfactions": [], "suggestions": [], "comparisons": []}

            for scene in result.get("scenes", []):
                if scene and isinstance(scene, str) and scene.strip():
                    scenes_data.append([username, model_name, model_version, score, scene.strip()])
            for sat in result.get("satisfactions", []):
                domain = sat.get("domain", "").strip()
                point = sat.get("point", "").strip()
                if domain and point:
                    satisfactions_data.append([username, model_name, model_version, score, domain, point])
            for dis in result.get("dissatisfactions", []):
                domain = dis.get("domain", "").strip()
                point = dis.get("point", "").strip()
                if domain and point:
                    dissatisfactions_data.append([username, model_name, model_version, score, domain, point])
            for sug in result.get("suggestions", []):
                domain = sug.get("domain", "").strip()
                suggestion = sug.get("suggestion", "").strip()
                if domain and suggestion:
                    suggestions_data.append([username, model_name, model_version, score, domain, suggestion])
            for comp in result.get("comparisons", []):
                comp_model = comp.get("model", "").strip()
                content = comp.get("content", "").strip()
                if comp_model and content:
                    comparisons_data.append([username, model_name, model_version, score, comp_model, content])

            percent = 20 + int(70 * completed / total_tasks)
            progress_callback(percent, f"分析中 {completed}/{total_tasks}")
            time.sleep(REQUEST_DELAY)

    df_scenes = pd.DataFrame(scenes_data, columns=["用户名", "车型名称", "车型版本", "评分", "使用场景"])
    df_satisfactions = pd.DataFrame(satisfactions_data, columns=["用户名", "车型名称", "车型版本", "评分", "满意领域", "满意点"])
    df_dissatisfactions = pd.DataFrame(dissatisfactions_data, columns=["用户名", "车型名称", "车型版本", "评分", "不满意领域", "不满意点"])
    df_suggestions = pd.DataFrame(suggestions_data, columns=["用户名", "车型名称", "车型版本", "评分", "改进领域", "改进建议"])
    df_comparisons = pd.DataFrame(comparisons_data, columns=["用户名", "车型名称", "车型版本", "评分", "对比车型名称", "对比内容"])

    progress_callback(95, "正在生成 Excel 报告...")
    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        df_raw.to_excel(writer, sheet_name="懂车帝评论", index=False)
        df_scenes.to_excel(writer, sheet_name="使用场景", index=False)
        df_satisfactions.to_excel(writer, sheet_name="满意点", index=False)
        df_dissatisfactions.to_excel(writer, sheet_name="不满意点", index=False)
        df_suggestions.to_excel(writer, sheet_name="改进建议", index=False)
        df_comparisons.to_excel(writer, sheet_name="对比车型", index=False)

    summary = generate_summary(df_raw, df_satisfactions, df_dissatisfactions)
    progress_callback(100, "懂车帝分析完成")
    return summary


if __name__ == "__main__":
    def test_progress(pct, msg):
        print(f"[{pct}%] {msg}")

    test_input = "outputs/dongchedi_MEGA_6067.csv"
    test_output = "outputs/dongchedi_test_analysis_result.xlsx"
    if os.path.exists(test_input):
        print("开始测试懂车帝分析流程...")
        summary = run_dongchedi_analysis(test_input, test_output, test_progress)
        print("分析摘要:", summary)
    else:
        print("测试文件不存在，请先运行懂车帝爬虫生成 CSV")

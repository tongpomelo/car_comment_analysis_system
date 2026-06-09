# p01_visualizer.py
# -*- coding: utf-8 -*-
"""
可视化分析引擎 — 商品企划深度版
读取分析结果 Excel，输出多维商业洞察数据供前端 ECharts 渲染。
"""

import pandas as pd
import numpy as np
from collections import Counter, defaultdict
import difflib
import re
import math


# ========== 工具函数 ==========

def cluster_texts(texts, threshold=0.6):
    """相似度聚类，返回 {类代表文本: 出现次数}"""
    clusters = []
    for text in texts:
        text = text.strip()
        if not text:
            continue
        best_ratio = 0
        best_idx = -1
        for i, cluster in enumerate(clusters):
            ratio = difflib.SequenceMatcher(None, cluster[0], text).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i
        if best_ratio >= threshold and best_idx != -1:
            clusters[best_idx].append(text)
        else:
            clusters.append([text])

    result = {}
    for cluster in clusters:
        counter = Counter(cluster)
        most_common = counter.most_common(1)[0][0]
        result[most_common] = len(cluster)
    return result


def safe_read_excel(excel_path, sheet_name):
    """安全读取 Excel Sheet，不存在则返回空 DataFrame"""
    try:
        return pd.read_excel(excel_path, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()


def extract_keyword(text, max_len=12):
    """从文本中提取简短关键词"""
    text = re.sub(r'[，。！？、；：""''（）\s]+', ' ', str(text))
    text = text.strip()
    if len(text) > max_len:
        # 取第一个逗号/空格前的内容
        parts = re.split(r'[，, ]', text)
        short = parts[0]
        if len(short) < 4 and len(parts) > 1:
            short = parts[0] + parts[1] if len(parts) > 1 else short
        return short[:max_len]
    return text


# ========== 1. 领域优劣势矩阵 ==========

def build_domain_matrix(df_satis, df_dissatis, df_suggest):
    """构建领域 × 满意/不满意/建议 交叉矩阵"""
    domains = set()
    satis_by_domain = Counter()
    diss_by_domain = Counter()
    suggest_by_domain = Counter()

    if not df_satis.empty and '满意领域' in df_satis.columns:
        for d in df_satis['满意领域'].dropna():
            d = str(d).strip()
            if d:
                satis_by_domain[d] += 1
                domains.add(d)

    if not df_dissatis.empty and '不满意领域' in df_dissatis.columns:
        for d in df_dissatis['不满意领域'].dropna():
            d = str(d).strip()
            if d:
                diss_by_domain[d] += 1
                domains.add(d)

    if not df_suggest.empty and '改进领域' in df_suggest.columns:
        for d in df_suggest['改进领域'].dropna():
            d = str(d).strip()
            if d:
                suggest_by_domain[d] += 1
                domains.add(d)

    result = []
    for domain in domains:
        s = satis_by_domain.get(domain, 0)
        d = diss_by_domain.get(domain, 0)
        sg = suggest_by_domain.get(domain, 0)
        net = s - d
        # 判定象限
        if s >= d:
            quadrant = "核心优势" if s >= 3 else "潜力优势"
        else:
            quadrant = "重点关注" if d >= 3 else "观察改进"
        result.append({
            "domain": domain,
            "satis_count": s,
            "diss_count": d,
            "suggest_count": sg,
            "net_score": net,
            "quadrant": quadrant
        })

    result.sort(key=lambda x: x["net_score"], reverse=True)
    return result


# ========== 2. 改进优先级 ==========

def build_improvement_priority(df_dissatis, df_suggest):
    """综合不满意次数和改进建议次数，计算改进优先级分"""
    diss_points = defaultdict(list)

    if not df_dissatis.empty and '不满意领域' in df_dissatis.columns:
        for _, row in df_dissatis.iterrows():
            domain = str(row.get('不满意领域', '')).strip()
            point = str(row.get('不满意点', '')).strip()
            if domain and point:
                diss_points[domain].append(point)

    suggest_count = Counter()
    if not df_suggest.empty and '改进领域' in df_suggest.columns:
        for d in df_suggest['改进领域'].dropna():
            suggest_count[str(d).strip()] += 1

    result = []
    for domain, points in diss_points.items():
        sg = suggest_count.get(domain, 0)
        priority = len(points) * 2 + sg * 3  # 不满意度权重2，建议权重3
        # 聚类获取代表性抱怨
        unique_points = list(set(points))
        if len(unique_points) > 5:
            clustered = cluster_texts(unique_points, threshold=0.5)
            top_points = sorted(clustered.items(), key=lambda x: x[1], reverse=True)[:5]
            top_points = [p[0] for p in top_points]
        else:
            top_points = unique_points[:5]

        result.append({
            "domain": domain,
            "priority_score": priority,
            "diss_count": len(points),
            "suggest_count": sg,
            "top_complaints": [extract_keyword(p) for p in top_points]
        })

    result.sort(key=lambda x: x["priority_score"], reverse=True)
    return result[:10]


# ========== 3. 竞品对战分析 ==========

def build_competitive_insight(df_compare, df_satis, df_dissatis):
    """从对比内容中提取竞品优劣势"""
    if df_compare.empty or '对比车型名称' not in df_compare.columns:
        return {"top_rivals": [], "rival_detail": [], "our_edges": [], "rival_edges": []}

    rival_counter = Counter()
    rival_content = defaultdict(list)

    for _, row in df_compare.iterrows():
        name = str(row.get('对比车型名称', '')).strip()
        content = str(row.get('对比内容', '')).strip()
        if name and content:
            rival_counter[name] += 1
            rival_content[name].append(content)

    # 判断优劣关键词
    our_edge_words = ['更好', '更大', '更舒适', '更强', '更省', '优于', '胜于', '优势', '领先']
    rival_edge_words = ['不如', '较差', '不足', '遗憾', '比不上', '劣势', '短板', '欠缺']

    rival_detail = []
    our_edges = Counter()
    rival_edges = Counter()
    our_edge_examples = defaultdict(list)
    rival_edge_examples = defaultdict(list)

    for rival, count in rival_counter.most_common(8):
        contents = rival_content[rival]
        our_mentions = []
        rival_mentions = []

        for content in contents:
            for kw in our_edge_words:
                if kw in content:
                    our_mentions.append(content)
                    # 提取涉及的领域
                    for domain in ['空间', '续航', '外观', '内饰', '智能化', '驾驶感受', '性价比', '配置', '舒适', '动力']:
                        if domain in content:
                            our_edges[domain] += 1
                            our_edge_examples[domain].append(extract_keyword(content, 20))
                    break
            for kw in rival_edge_words:
                if kw in content:
                    rival_mentions.append(content)
                    for domain in ['空间', '续航', '外观', '内饰', '智能化', '驾驶感受', '性价比', '配置', '舒适', '动力']:
                        if domain in content:
                            rival_edges[domain] += 1
                            rival_edge_examples[domain].append(extract_keyword(content, 20))
                    break

        rival_detail.append({
            "rival": rival,
            "mention_count": count,
            "our_advantage_count": len(our_mentions),
            "rival_advantage_count": len(rival_mentions),
            "our_advantage_sample": extract_keyword(our_mentions[0], 30) if our_mentions else "",
            "rival_advantage_sample": extract_keyword(rival_mentions[0], 30) if rival_mentions else "",
        })

    # 汇总优劣势领域
    our_edge_summary = [{"domain": k, "count": v, "example": our_edge_examples[k][0] if our_edge_examples[k] else ""}
                        for k, v in our_edges.most_common(6)]
    rival_edge_summary = [{"domain": k, "count": v, "example": rival_edge_examples[k][0] if rival_edge_examples[k] else ""}
                          for k, v in rival_edges.most_common(6)]

    return {
        "top_rivals": [r[0] for r in rival_counter.most_common(8)],
        "rival_detail": rival_detail,
        "our_edges": our_edge_summary,
        "rival_edges": rival_edge_summary
    }


# ========== 4. 评分雷达 ==========

def build_score_radar(df_raw):
    """从原始数据中提取各维度平均评分"""
    score_cols = [
        ('空间', '空间评分'), ('驾驶感受', '驾驶感受评分'),
        ('续航', '续航评分'), ('外观', '外观评分'),
        ('内饰', '内饰评分'), ('性价比', '性价比评分'),
        ('智能化', '智能化评分'), ('油耗', '油耗评分'),
        ('配置', '配置评分'),
    ]

    radar = []
    for name, col in score_cols:
        if col in df_raw.columns:
            vals = pd.to_numeric(df_raw[col], errors='coerce').dropna()
            if len(vals) > 0:
                radar.append({
                    "name": name,
                    "value": round(float(vals.mean()), 1),
                    "max": 5.0
                })

    # 补充懂车帝评分格式
    for col in df_raw.columns:
        if col.startswith('评分_'):
            name = col.replace('评分_', '')
            if not any(r['name'] == name for r in radar):
                vals = pd.to_numeric(df_raw[col], errors='coerce').dropna()
                if len(vals) > 0:
                    radar.append({
                        "name": name,
                        "value": round(float(vals.mean()), 1),
                        "max": 5.0
                    })

    return radar


# ========== 5. 具体口碑点（好评/抱怨 Top N） ==========

def build_top_points(df_satis, df_dissatis):
    """提取具体的好评点和抱怨点（聚类后）"""
    praise_points = []
    if not df_satis.empty and '满意点' in df_satis.columns:
        raw = [str(p).strip() for p in df_satis['满意点'].dropna() if len(str(p).strip()) > 2]
        if raw:
            clustered = cluster_texts(raw, threshold=0.45)
            praise_points = [{"text": extract_keyword(k, 20), "count": v}
                             for k, v in sorted(clustered.items(), key=lambda x: x[1], reverse=True)[:12]]

    complaint_points = []
    if not df_dissatis.empty and '不满意点' in df_dissatis.columns:
        raw = [str(p).strip() for p in df_dissatis['不满意点'].dropna() if len(str(p).strip()) > 2]
        if raw:
            clustered = cluster_texts(raw, threshold=0.45)
            complaint_points = [{"text": extract_keyword(k, 20), "count": v}
                                for k, v in sorted(clustered.items(), key=lambda x: x[1], reverse=True)[:12]]

    return praise_points, complaint_points


# ========== 6. 场景-关注点关联 ==========

def build_scenario_concern(df_scenes, df_satis, df_dissatis):
    """分析不同使用场景下用户关注的领域"""
    if df_scenes.empty or '使用场景' not in df_scenes.columns:
        return []

    # 按用户名关联场景与满意度
    user_scenes = defaultdict(set)
    if '用户名' in df_scenes.columns:
        for _, row in df_scenes.iterrows():
            user = str(row.get('用户名', '')).strip()
            scene = str(row.get('使用场景', '')).strip()
            if user and scene:
                user_scenes[user].add(scene)

    # 为每个场景统计关注领域
    scene_domains = defaultdict(lambda: {"satis": Counter(), "diss": Counter()})

    if not df_satis.empty and '用户名' in df_satis.columns and '满意领域' in df_satis.columns:
        for _, row in df_satis.iterrows():
            user = str(row.get('用户名', '')).strip()
            domain = str(row.get('满意领域', '')).strip()
            if user in user_scenes and domain:
                for scene in user_scenes[user]:
                    scene_domains[scene]["satis"][domain] += 1

    if not df_dissatis.empty and '用户名' in df_dissatis.columns and '不满意领域' in df_dissatis.columns:
        for _, row in df_dissatis.iterrows():
            user = str(row.get('用户名', '')).strip()
            domain = str(row.get('不满意领域', '')).strip()
            if user in user_scenes and domain:
                for scene in user_scenes[user]:
                    scene_domains[scene]["diss"][domain] += 1

    result = []
    for scene, data in scene_domains.items():
        top_satis = data["satis"].most_common(3)
        top_diss = data["diss"].most_common(3)
        total = sum(c for _, c in top_satis) + sum(c for _, c in top_diss)
        if total >= 2:
            result.append({
                "scenario": scene,
                "top_satis": [{"domain": d, "count": c} for d, c in top_satis],
                "top_diss": [{"domain": d, "count": c} for d, c in top_diss],
            })

    result.sort(key=lambda x: sum(d["count"] for d in x["top_satis"]) +
                              sum(d["count"] for d in x["top_diss"]), reverse=True)
    return result[:8]


# ========== 主入口 ==========

def generate_visualization(excel_path):
    """读取分析结果 Excel，返回完整商业洞察数据"""
    df_raw = safe_read_excel(excel_path, sheet_name=0)  # 第一个 sheet
    df_scenes = safe_read_excel(excel_path, sheet_name='使用场景')
    df_satis = safe_read_excel(excel_path, sheet_name='满意点')
    df_dissatis = safe_read_excel(excel_path, sheet_name='不满意点')
    df_suggest = safe_read_excel(excel_path, sheet_name='改进建议')
    df_compare = safe_read_excel(excel_path, sheet_name='对比车型')

    # === 基础统计（保留旧接口兼容） ===
    scenes_raw = df_scenes['使用场景'].dropna().astype(str).tolist() if not df_scenes.empty else []
    scenes_clustered = cluster_texts(scenes_raw, threshold=0.55) if scenes_raw else {}
    scenes_sorted = sorted(scenes_clustered.items(), key=lambda x: x[1], reverse=True)[:15]
    scenes_data = [{"name": k, "value": v} for k, v in scenes_sorted]

    satis_domain = df_satis['满意领域'].dropna().astype(str).tolist() if not df_satis.empty else []
    satisfactions_data = [{"name": k, "value": v} for k, v in Counter(satis_domain).most_common(15)]

    dis_domain = df_dissatis['不满意领域'].dropna().astype(str).tolist() if not df_dissatis.empty else []
    dissatisfactions_data = [{"name": k, "value": v} for k, v in Counter(dis_domain).most_common(15)]

    suggest_domain = df_suggest['改进领域'].dropna().astype(str).tolist() if not df_suggest.empty else []
    suggestions_data = [{"name": k, "value": v} for k, v in Counter(suggest_domain).most_common(15)]

    compare_models = df_compare['对比车型名称'].dropna().astype(str).tolist() if not df_compare.empty else []
    comparisons_data = [{"name": k, "value": v} for k, v in Counter(compare_models).most_common(15)]

    # === 深层分析 ===
    domain_matrix = build_domain_matrix(df_satis, df_dissatis, df_suggest)
    improvement_priority = build_improvement_priority(df_dissatis, df_suggest)
    competitive_insight = build_competitive_insight(df_compare, df_satis, df_dissatis)
    score_radar = build_score_radar(df_raw)
    top_praise, top_complaint = build_top_points(df_satis, df_dissatis)
    scenario_concern = build_scenario_concern(df_scenes, df_satis, df_dissatis)

    return {
        # 基础
        "scenes": scenes_data,
        "satisfactions": satisfactions_data,
        "dissatisfactions": dissatisfactions_data,
        "suggestions": suggestions_data,
        "comparisons": comparisons_data,
        # 深层
        "domain_matrix": domain_matrix,
        "improvement_priority": improvement_priority,
        "competitive_insight": competitive_insight,
        "score_radar": score_radar,
        "top_praise_points": top_praise,
        "top_complaint_points": top_complaint,
        "scenario_concern": scenario_concern,
    }


if __name__ == "__main__":
    import json
    import os
    test_excel = "outputs/【理想MEGA怎么样】理想汽车_理想MEGA怎么样_缺点_优点_6939_分析结果.xlsx"
    if os.path.exists(test_excel):
        data = generate_visualization(test_excel)
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"测试文件不存在: {test_excel}")
        # 列出 outputs 目录下的文件
        if os.path.exists("outputs"):
            print("outputs 目录内容:", os.listdir("outputs"))

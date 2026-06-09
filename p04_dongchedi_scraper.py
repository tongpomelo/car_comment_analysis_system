import requests
import pandas as pd
from bs4 import BeautifulSoup
import time
import random
import re
from tqdm import tqdm
import json
import os
from urllib.parse import urljoin
import threading
from queue import Queue
import pickle
import csv
from datetime import datetime

# ============================================================
# 修复说明（相比V5版本的改动）：
#
# Bug1修复：parse_review_page 容器检测策略彻底重构
#   - 旧逻辑：方法2用">=3个h2/h3/p"抓取几乎所有div，导致侧边栏、
#     推荐模块等其他车型内容被当作评论容器
#   - 新逻辑：多层精准选择器 + 去嵌套去重，只保留最小有效评论容器
#
# Bug2修复：新增 validate_and_filter_reviews() 函数
#   - 提取到 点评车型 后，与当前爬取的 car_name 进行模糊匹配校验
#   - 不匹配的评论记录到 mismatch_log，不写入结果
#
# Bug3修复：车型名称赋值前先校验，而不是盲目覆盖
#   - 只有通过校验的评论才赋值 车型名称
# ============================================================

# 随机User-Agent池
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:127.0) Gecko/20100101 Firefox/127.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/126.0.0.0 Safari/537.36'
]


def get_random_headers():
    """获取随机请求头"""
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Referer': random.choice([
            'https://www.dongchedi.com/',
            'https://www.baidu.com/',
            'https://www.google.com/',
            'https://www.bing.com/'
        ]),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/avif,*/*;q=0.8',
        'Accept-Language': random.choice([
            'zh-CN,zh;q=0.9,en;q=0.8',
            'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
            'zh-CN,zh;q=0.9'
        ]),
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': random.choice(['max-age=0', 'no-cache', 'no-store']),
        'sec-ch-ua': f'"Chromium";v="{random.randint(120, 128)}", "Google Chrome";v="{random.randint(120, 128)}", "Not-A.Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': random.choice(['"Windows"', '"macOS"', '"Linux"']),
        'DNT': '1'
    }


# 优化后的时间配置
BASE_URL = "https://www.dongchedi.com/auto/series/score/{}-x-S0-x-default-1-{}"  # 启用"只看车主"
MAX_PAGES = 100
DELAY_RANGE = (1.5, 2.5)
RETRY_TIMES = 3
SESSION_REFRESH_INTERVAL = 5
REQUEST_COUNT = 0

# 全局session池
SESSION_POOL = []
SESSION_POOL_SIZE = 5

# 文件保存配置
OUTPUT_DIR = "dongchedi_reviews_data"
MAIN_OUTPUT_FILE = "懂车帝口碑评论_汇总.csv"
PROGRESS_FILE = "crawl_progress.pkl"
MISMATCH_LOG_FILE = "车型名称不匹配记录.csv"  # ★新增：不匹配记录文件


def init_output_directory():
    """初始化输出目录"""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"📁 创建输出目录: {OUTPUT_DIR}")


def init_session_pool():
    """初始化session池"""
    global SESSION_POOL
    SESSION_POOL = []
    for i in range(SESSION_POOL_SIZE):
        session = requests.Session()
        session.headers.update(get_random_headers())
        SESSION_POOL.append(session)
    print(f"✅ 初始化了{SESSION_POOL_SIZE}个session")


def get_session():
    """随机获取一个session"""
    return random.choice(SESSION_POOL)


def refresh_session_pool():
    """刷新session池"""
    global SESSION_POOL
    print("🔄 刷新session池...")
    for session in SESSION_POOL:
        session.close()
    time.sleep(random.uniform(1, 2))
    init_session_pool()


def save_car_reviews(car_id, car_name, reviews, timestamp):
    """保存单个车型的评论数据"""
    if not reviews:
        print(f"⚠️ 车型 {car_name}({car_id}) 没有评论数据，跳过保存")
        return None

    try:
        safe_car_name = "".join(c for c in car_name if c.isalnum() or c in (' ', '-', '_', '（', '）', '(', ')')).strip()
        car_filename = f"{OUTPUT_DIR}/车型_{safe_car_name}_{car_id}_{timestamp}.csv"

        car_df = pd.DataFrame(reviews)
        car_df.to_csv(car_filename, index=False, encoding='utf-8-sig')

        print(f"💾 车型 {car_name}({car_id}) 的 {len(reviews)} 条评论已保存到: {car_filename}")
        return car_filename
    except Exception as e:
        print(f"❌ 保存车型 {car_name}({car_id}) 数据失败: {e}")
        return None


def update_main_file(all_reviews, timestamp):
    """更新主汇总文件"""
    if not all_reviews:
        return

    try:
        main_file_path = f"{OUTPUT_DIR}/{MAIN_OUTPUT_FILE.replace('.csv', f'_{timestamp}.csv')}"

        result_df = pd.DataFrame(all_reviews)
        columns_order = ['车型名称', '车型ID', '页码', '评论序号', '点评车型', '提车时间', '购买地点',
                         '裸车价格', '油耗', '续航', '评论内容']

        score_columns = [col for col in result_df.columns if col.startswith('评分_')]
        columns_order.extend(score_columns)

        other_columns = [col for col in result_df.columns if col not in columns_order]
        columns_order.extend(other_columns)

        final_columns = [col for col in columns_order if col in result_df.columns]
        result_df = result_df[final_columns]

        result_df.to_csv(main_file_path, index=False, encoding='utf-8-sig')
        print(f"📊 主汇总文件已更新: {main_file_path} (共 {len(all_reviews)} 条评论)")

    except Exception as e:
        print(f"❌ 更新主汇总文件失败: {e}")


# ★ 新增：保存车型名称不匹配记录
def save_mismatch_log(mismatch_records, timestamp):
    """保存车型名称不匹配的评论记录，便于排查问题"""
    if not mismatch_records:
        return
    try:
        mismatch_file = f"{OUTPUT_DIR}/{MISMATCH_LOG_FILE.replace('.csv', f'_{timestamp}.csv')}"
        df = pd.DataFrame(mismatch_records)
        df.to_csv(mismatch_file, index=False, encoding='utf-8-sig')
        print(f"⚠️ 发现 {len(mismatch_records)} 条车型不匹配记录，已保存到: {mismatch_file}")
    except Exception as e:
        print(f"❌ 保存不匹配记录失败: {e}")


def save_progress(processed_cars, current_car_index, failed_cars, all_reviews, timestamp):
    """保存爬取进度"""
    progress_data = {
        'processed_cars': processed_cars,
        'current_car_index': current_car_index,
        'failed_cars': failed_cars,
        'all_reviews': all_reviews,
        'timestamp': timestamp,
        'save_time': time.time()
    }
    with open(PROGRESS_FILE, 'wb') as f:
        pickle.dump(progress_data, f)
    print(f"💾 进度已保存: 已处理 {len(processed_cars)} 个车型")


def load_progress():
    """加载爬取进度"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'rb') as f:
                progress_data = pickle.load(f)
            print(f"📋 发现进度文件，已处理 {len(progress_data.get('processed_cars', []))} 个车型")
            return progress_data
        except Exception as e:
            print(f"⚠️ 加载进度失败: {e}")
    return None


def smart_delay():
    """智能延时"""
    base_delay = random.uniform(*DELAY_RANGE)

    if random.random() < 0.05:
        extra_delay = random.uniform(5, 15)
        print(f"😴 模拟用户思考: {extra_delay:.1f}秒")
        base_delay += extra_delay

    current_hour = time.localtime().tm_hour
    if 9 <= current_hour <= 17:
        base_delay *= random.uniform(1.1, 1.3)

    time.sleep(base_delay)


def save_debug_info(car_id, page, content, filename_suffix=""):
    """保存调试信息"""
    os.makedirs("debug_data", exist_ok=True)
    filename = f"debug_data/{car_id}_page_{page}{filename_suffix}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"🔍 调试文件已保存: {filename}")


def extract_car_model(review_container):
    """提取点评车型信息"""
    selectors = [
        'h2.tw-text-14.tw-mb-12 span.tw-ml-4.tw-font-bold.tw-text-16',
        'h2[class*="tw-text-14"] span[class*="tw-font-bold"]',
        'h2 span[class*="tw-font-bold"]'
    ]

    for selector in selectors:
        try:
            element = review_container.select_one(selector)
            if element:
                return element.get_text(strip=True)
        except:
            continue

    return None


def extract_basic_info(review_container):
    """提取基础信息：提车时间、购买地点、裸车价格、油耗、续航"""
    basic_info = {}

    info_containers = review_container.find_all('div', class_=re.compile(r'tw-flex.*tw-py-12'))

    for container in info_containers:
        info_items = container.find_all('div', class_=re.compile(r'tw-flex-1.*tw-text-center'))

        for item in info_items:
            try:
                value_elem = item.find('p', class_=re.compile(r'tw-font-semibold'))
                label_elem = item.find('p', class_=re.compile(r'tw-text-color-gray-700'))

                if value_elem and label_elem:
                    label = label_elem.get_text(strip=True)
                    value = value_elem.get_text(strip=True)

                    label_mapping = {
                        '提车时间': '提车时间',
                        '购买地点': '购买地点',
                        '裸车价格': '裸车价格',
                        '油耗': '油耗',
                        '续航': '续航'
                    }

                    if label in label_mapping:
                        basic_info[label_mapping[label]] = value
            except Exception as e:
                continue

    return basic_info


def extract_scores(review_container):
    """提取评分信息"""
    scores = {}

    score_containers = review_container.find_all('div', class_=re.compile(r'tw-flex.*tw-justify-around'))

    for container in score_containers:
        score_items = container.find_all('div', class_=re.compile(r'tw-col-span-3.*tw-text-center'))

        for item in score_items:
            try:
                score_selectors = [
                    'p[class*="score-item"] span.tw-relative',
                    'p[class*="score-item"]',
                    'span.tw-relative',
                    'p'
                ]

                score_value = None
                for selector in score_selectors:
                    score_elem = item.select_one(selector)
                    if score_elem:
                        score_text = score_elem.get_text(strip=True)
                        if re.match(r'^\d+(\.\d+)?$', score_text):
                            score_value = score_text
                            break

                label_elem = item.find('p', class_=re.compile(r'tw-text-color-gray-700'))

                if score_value and label_elem:
                    label = label_elem.get_text(strip=True)
                    scores[f'评分_{label}'] = score_value

            except Exception as e:
                continue

    return scores


def extract_review_content(review_container):
    """提取评论文本内容"""
    content_selectors = [
        'p.line-4.tw-text-16.tw-leading-26.tw-cursor-pointer',
        'p[class*="line-4"]',
        'p[class*="tw-text-16"]',
        'div[class*="content"] p',
        'p[class*="content"]'
    ]

    for selector in content_selectors:
        try:
            content_elem = review_container.select_one(selector)
            if content_elem:
                content = content_elem.get_text(strip=True)
                if len(content) > 10:
                    return content
        except:
            continue

    return None


# ============================================================
# ★ Bug1修复核心：重构容器检测逻辑
# ============================================================
def find_review_containers(soup):
    """
    精准查找评论容器，解决旧方法2抓取范围过宽导致的混入问题。

    策略：
    1. 优先使用懂车帝特定的精准选择器
    2. 如果找不到，使用"有h2且有长文本p"的组合条件（而非仅>=3个标签）
    3. 对找到的容器去嵌套，避免父子容器重复计入
    """

    # ---- 阶段1：精准选择器（最优先） ----
    precise_selectors = [
        # 懂车帝口碑评论的典型结构
        'div[class*="review-item"]',
        'div[class*="ReviewItem"]',
        'div[class*="score-item"]',
        'div[class*="comment-item"]',
        'div[class*="reputation-item"]',
        'li[class*="review"]',
        'li[class*="comment"]',
    ]
    for selector in precise_selectors:
        containers = soup.select(selector)
        if len(containers) >= 1:
            print(f"  ✅ 精准选择器命中: {selector}，找到{len(containers)}个容器")
            return remove_nested_containers(containers)

    # ---- 阶段2：语义标签（次优先） ----
    for tag in ['article', 'section']:
        containers = soup.find_all(tag)
        # 过滤：必须包含较长的文本（排除纯导航section）
        valid = [c for c in containers if len(c.get_text(strip=True)) > 50]
        if valid:
            print(f"  ✅ 语义标签 <{tag}> 命中，找到{len(valid)}个有效容器")
            return remove_nested_containers(valid)

    # ---- 阶段3：宽泛备选（最后手段，增加严格过滤条件） ----
    # 与旧方法2的关键区别：
    #   旧：find_all('div') + len(h2/h3/p) >= 3   → 几乎所有div都入选
    #   新：必须同时满足：
    #       a) 有h2标题元素（评论标题通常是h2）
    #       b) 有超过30字的长文本p（评论正文）
    #       c) 排除已知的非评论区域（导航、页脚等）
    EXCLUDED_CLASSES = re.compile(
        r'nav|header|footer|sidebar|recommend|advertisement|'
        r'ad-|banner|breadcrumb|pagination|tabs|toolbar', re.I
    )

    all_divs = soup.find_all('div', recursive=True)
    fallback_containers = []
    for div in all_divs:
        cls = ' '.join(div.get('class', []))
        if EXCLUDED_CLASSES.search(cls):
            continue
        has_h2 = bool(div.find('h2'))
        long_p = [p for p in div.find_all('p', recursive=True)
                  if len(p.get_text(strip=True)) > 30]
        if has_h2 and len(long_p) >= 1:
            fallback_containers.append(div)

    if fallback_containers:
        print(f"  ⚠️ 使用宽泛备选策略，找到{len(fallback_containers)}个候选容器（已去嵌套）")
        return remove_nested_containers(fallback_containers)

    print("  ❌ 未找到任何评论容器")
    return []


def remove_nested_containers(containers):
    """
    去嵌套：如果容器A是容器B的祖先，只保留子容器B。
    避免同一评论被父容器、子容器各解析一次，产生重复/混入数据。
    """
    if not containers:
        return containers

    # 将BeautifulSoup Tag对象转为集合，判断包含关系
    result = []
    for i, c in enumerate(containers):
        is_ancestor = False
        for j, other in enumerate(containers):
            if i != j and c != other:
                # 如果 c 是 other 的祖先，则跳过 c
                try:
                    if c in other.parents:
                        is_ancestor = True
                        break
                except Exception:
                    pass
        if not is_ancestor:
            result.append(c)

    return result


# ============================================================
# ★ Bug2修复：车型名称一致性校验
# ============================================================
def car_name_matches(expected_name: str, actual_model: str) -> bool:
    """
    判断 点评车型(actual_model) 是否与当前爬取的 车型名称(expected_name) 相符。

    由于点评车型通常是"2024款 比亚迪汉 EV 610km尊贵型"等完整名称，
    而expected_name是"比亚迪汉"这类简短名称，使用模糊匹配。

    匹配规则：
    - expected_name 的任意一个关键词（>=2字）出现在 actual_model 中即认为匹配
    - 或 actual_model 中的关键词出现在 expected_name 中
    """
    if not actual_model:
        # 没有提取到点评车型，无法判断，保守处理：保留该评论
        return True

    # 清洗：去除年份、"款"字等干扰词
    clean_expected = re.sub(r'\d{4}款?|款', '', expected_name).strip()
    clean_actual = re.sub(r'\d{4}款?|款', '', actual_model).strip()

    # 将车型名拆成关键词（>=2个字符）
    keywords_expected = [w for w in re.split(r'[\s\-\(\)（）·]+', clean_expected) if len(w) >= 2]
    keywords_actual = [w for w in re.split(r'[\s\-\(\)（）·]+', clean_actual) if len(w) >= 2]

    # 任一关键词双向包含即通过
    for kw in keywords_expected:
        if kw in clean_actual:
            return True
    for kw in keywords_actual:
        if kw in clean_expected:
            return True

    return False


def validate_and_filter_reviews(reviews, car_name, car_id, page, mismatch_records):
    """
    对解析出的评论列表做车型名称校验，过滤掉不属于当前车型的评论。

    Args:
        reviews: 当前页解析出的评论列表
        car_name: 当前正在爬取的车型名称（来自CSV）
        car_id: 当前车型ID
        page: 当前页码
        mismatch_records: 不匹配记录列表（in-place追加，用于最终输出日志）

    Returns:
        valid_reviews: 通过校验的评论列表
    """
    valid_reviews = []
    for review in reviews:
        actual_model = review.get('点评车型', '')

        if car_name_matches(car_name, actual_model):
            # ★ Bug3修复：只有通过校验才赋值车型名称
            review['车型名称'] = car_name
            valid_reviews.append(review)
        else:
            # 记录不匹配情况，但不写入结果
            mismatch_record = {
                '期望车型名称': car_name,
                '期望车型ID': car_id,
                '实际点评车型': actual_model,
                '页码': page,
                '评论内容片段': str(review.get('评论内容', ''))[:100]
            }
            mismatch_records.append(mismatch_record)
            print(f"  🚫 过滤不匹配评论: 期望[{car_name}] ≠ 实际[{actual_model}]")

    return valid_reviews


# ============================================================
# ★ 重构后的 parse_review_page
# ============================================================
def parse_review_page(html_content, car_id, page):
    """
    解析单页评论。
    主要变化：使用新的 find_review_containers() 替代旧的宽泛方法2。
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    reviews = []

    # 使用重构后的精准容器查找
    review_containers = find_review_containers(soup)

    print(f"🔍 车型{car_id}第{page}页找到{len(review_containers)}个评论容器")

    for i, container in enumerate(review_containers):
        try:
            review_data = {
                '车型ID': car_id,
                '页码': page,
                '评论序号': i + 1
            }

            car_model = extract_car_model(container)
            if car_model:
                review_data['点评车型'] = car_model

            basic_info = extract_basic_info(container)
            review_data.update(basic_info)

            scores = extract_scores(container)
            review_data.update(scores)

            content = extract_review_content(container)
            if content:
                review_data['评论内容'] = content

            # 只有当提取到有效信息时才添加
            if car_model or content or basic_info or scores:
                reviews.append(review_data)

        except Exception as e:
            print(f"❌ 解析第{i + 1}个评论时出错: {e}")
            continue

    return reviews, len(review_containers)


def detect_blocking(response):
    """检测是否被反爬限制"""
    if not response:
        return True, "无响应"

    if response.status_code in [403, 429, 503]:
        return True, f"HTTP {response.status_code}"

    if len(response.text) < 500:
        return True, "内容过短"

    blocking_keywords = [
        '验证码', '人机验证', 'blocked', 'forbidden',
        '访问频繁', '请稍后再试', 'too many requests',
        'captcha', '机器人', 'robot'
    ]

    content_lower = response.text.lower()
    for keyword in blocking_keywords:
        if keyword in content_lower:
            return True, f"包含关键词: {keyword}"

    return False, "正常"


def get_page_with_retry(url, max_retries=RETRY_TIMES):
    """带重试的页面获取"""
    global REQUEST_COUNT

    for attempt in range(max_retries):
        try:
            REQUEST_COUNT += 1
            if REQUEST_COUNT % SESSION_REFRESH_INTERVAL == 0:
                refresh_session_pool()
                smart_delay()

            session = get_session()

            if random.random() < 0.2:
                session.headers.update(get_random_headers())

            if random.random() < 0.05:
                try:
                    session.get("https://www.dongchedi.com/",
                                headers=get_random_headers(), timeout=15)
                    time.sleep(random.uniform(0.5, 1.5))
                except:
                    pass

            response = session.get(url, headers=get_random_headers(), timeout=30)

            is_blocked, reason = detect_blocking(response)
            if is_blocked:
                print(f"🚫 检测到限制 ({reason})，等待后重试...")
                wait_time = random.uniform(15, 30) * (attempt + 1)
                print(f"⏳ 等待 {wait_time:.1f} 秒...")
                time.sleep(wait_time)
                continue

            if response.status_code == 200:
                return response
            else:
                print(f"❌ HTTP {response.status_code}: {url}")

        except requests.exceptions.RequestException as e:
            print(f"🚫 网络错误 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = random.uniform(5, 10) * (attempt + 1)
                time.sleep(wait_time)

    print(f"💥 {url} 重试{max_retries}次后仍然失败")
    return None


def has_next_page(soup):
    """检查是否有下一页"""
    next_selectors = [
        'a[class*="next"]:not([class*="disabled"])',
        'button[class*="next"]:not([disabled])',
        'li[class*="next"]:not([class*="disabled"])'
    ]

    for selector in next_selectors:
        if soup.select(selector):
            return True

    page_numbers = soup.find_all(text=re.compile(r'\d+'))
    if len(page_numbers) > 1:
        return True

    return False


def crawl_car_reviews():
    """主爬虫函数"""
    init_output_directory()
    init_session_pool()
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # 加载车型ID
    try:
        if not os.path.exists('car_rank_civic.csv'):
            print("❌❌❌❌ 错误：car_rank_civic.csv文件不存在")
            return

        encodings = ['gbk', 'gb18030', 'big5', 'utf-8-sig']
        car_df = None

        for encoding in encodings:
            try:
                car_df = pd.read_csv('car_rank_civic.csv', encoding=encoding)
                print(f"✅ 使用 {encoding} 编码成功读取文件")
                break
            except Exception as e:
                print(f"⚠️ {encoding} 编码失败: {e}")
                continue

        if car_df is None:
            print("❌❌❌❌ 错误：无法读取CSV文件，尝试的编码都失败")
            return

        if 'id' not in car_df.columns or '车型' not in car_df.columns:
            print("❌❌❌❌ 错误：CSV文件中缺少id列或车型列")
            print(f"实际存在的列名: {list(car_df.columns)}")
            return

        car_id_to_name = car_df.set_index('id')['车型'].to_dict()
        car_ids = car_df['id'].dropna().astype(str).unique().tolist()
        print(f"📋📋📋📋 成功加载{len(car_ids)}个车型ID和车型名称")

    except Exception as e:
        print(f"❌❌❌❌ 读取车型ID失败：{e}")
        return

    # 尝试加载之前的进度
    progress_data = load_progress()
    if progress_data:
        processed_cars = progress_data.get('processed_cars', [])
        all_reviews = progress_data.get('all_reviews', [])
        failed_cars = progress_data.get('failed_cars', [])
        start_index = progress_data.get('current_car_index', 0)
        print(f"🔄 从第{start_index}个车型继续爬取，已有 {len(all_reviews)} 条评论")
    else:
        processed_cars = []
        all_reviews = []
        failed_cars = []
        start_index = 0

    remaining_car_ids = [car_id for car_id in car_ids[start_index:] if car_id not in processed_cars]
    print(f"📝 还需处理 {len(remaining_car_ids)} 个车型")

    # ★ 新增：全局不匹配记录列表
    all_mismatch_records = []

    with tqdm(total=len(remaining_car_ids), desc="总体进度") as pbar:
        for idx, car_id in enumerate(remaining_car_ids):
            car_name = car_id_to_name.get(int(car_id), '未知')
            pbar.set_description(f"处理车型 {car_name}({car_id})")

            car_reviews = []
            page = 1
            consecutive_empty_pages = 0
            consecutive_failures = 0

            print(f"\n🚗 开始爬取车型: {car_name}({car_id})")

            while page <= MAX_PAGES and consecutive_empty_pages < 3:
                url = BASE_URL.format(car_id, page)
                print(f"🌐 请求: {url}")

                response = get_page_with_retry(url)
                if not response:
                    print(f"❌ 车型{car_id}第{page}页请求失败")
                    consecutive_empty_pages += 1
                    consecutive_failures += 1

                    if consecutive_failures >= 3:
                        wait_time = random.uniform(60, 120)
                        print(f"😴 连续失败{consecutive_failures}次，等待: {wait_time:.1f}秒")
                        time.sleep(wait_time)
                        consecutive_failures = 0

                    page += 1
                    continue

                consecutive_failures = 0

                if os.getenv('DEBUG') == '1':
                    save_debug_info(car_id, page, response.text)

                # 解析页面
                page_reviews, container_count = parse_review_page(response.text, car_id, page)

                # ============================================================
                # ★ Bug2+Bug3修复：校验车型名称一致性，过滤掉不匹配的评论
                # 注意：validate_and_filter_reviews 内部会设置 review['车型名称']
                # ============================================================
                page_reviews = validate_and_filter_reviews(
                    page_reviews, car_name, car_id, page, all_mismatch_records
                )

                # 空页检测
                if container_count <= 1:
                    print(f"⚠️ 车型{car_id}第{page}页只有{container_count}个空容器，判定为无有效评论，停止当前车型爬取")
                    break

                if page_reviews:
                    car_reviews.extend(page_reviews)
                    consecutive_empty_pages = 0
                    print(f"✅ 车型{car_id}第{page}页: 获取到{len(page_reviews)}条有效评论")
                else:
                    consecutive_empty_pages += 1
                    print(f"⚠️ 车型{car_id}第{page}页: 未获取到评论（可能全被过滤）")

                soup = BeautifulSoup(response.text, 'html.parser')
                if not has_next_page(soup) and page > 1:
                    print(f"📄 车型{car_id}已到最后一页")
                    break

                page += 1
                smart_delay()

            # 处理完一个车型后保存数据
            if car_reviews:
                car_file = save_car_reviews(car_id, car_name, car_reviews, timestamp)
                all_reviews.extend(car_reviews)
                processed_cars.append(car_id)
                update_main_file(all_reviews, timestamp)
                print(f"🎉 车型 {car_name}({car_id}) 完成，共获取 {len(car_reviews)} 条评论")
            else:
                failed_cars.append(car_id)
                print(f"❌ 车型 {car_name}({car_id}) 未获取到任何评论")

            # 保存进度
            current_index = start_index + idx + 1
            save_progress(processed_cars, current_index, failed_cars, all_reviews, timestamp)

            # 定期保存不匹配记录
            if all_mismatch_records:
                save_mismatch_log(all_mismatch_records, timestamp)

            pbar.set_postfix({
                '当前车型评论数': len(car_reviews),
                '总评论数': len(all_reviews),
                '已完成车型': len(processed_cars),
                '失败车型': len(failed_cars),
                '过滤不匹配': len(all_mismatch_records)
            })
            pbar.update(1)

            if (idx + 1) % 8 == 0:
                rest_time = random.uniform(30, 60)
                print(f"😴 阶段性休息: {rest_time:.1f}秒")
                time.sleep(rest_time)

    # 最终统计
    print(f"\n🎉🎉🎉 爬取完成！")
    print(f"📊 最终统计:")
    print(f"   - 成功处理车型: {len(processed_cars)}")
    print(f"   - 失败车型: {len(failed_cars)}")
    print(f"   - 总评论数: {len(all_reviews)}")
    print(f"   - 过滤掉的不匹配评论: {len(all_mismatch_records)}")
    print(f"   - 输出目录: {OUTPUT_DIR}")

    if failed_cars:
        print(f"   - 失败车型ID: {failed_cars}")

    generate_final_report(processed_cars, failed_cars, all_reviews, car_id_to_name,
                          all_mismatch_records, timestamp)

    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("✅ 清理进度文件")


def generate_final_report(processed_cars, failed_cars, all_reviews, car_id_to_name,
                          mismatch_records, timestamp):
    """生成最终爬取报告"""
    try:
        report_file = f"{OUTPUT_DIR}/爬取报告_{timestamp}.txt"

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("懂车帝口碑评论爬取报告\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"爬取时间: {timestamp}\n")
            f.write(f"总计处理车型: {len(processed_cars)} 个\n")
            f.write(f"失败车型: {len(failed_cars)} 个\n")
            f.write(f"总评论数: {len(all_reviews)} 条\n")
            f.write(f"过滤掉的车型不匹配评论: {len(mismatch_records)} 条\n\n")

            f.write("成功处理的车型:\n")
            f.write("-" * 30 + "\n")
            for car_id in processed_cars:
                car_name = car_id_to_name.get(int(car_id), '未知')
                car_review_count = len([r for r in all_reviews if r['车型ID'] == car_id])
                f.write(f"  {car_name}({car_id}): {car_review_count} 条评论\n")

            if failed_cars:
                f.write(f"\n失败的车型:\n")
                f.write("-" * 30 + "\n")
                for car_id in failed_cars:
                    car_name = car_id_to_name.get(int(car_id), '未知')
                    f.write(f"  {car_name}({car_id})\n")

            if mismatch_records:
                f.write(f"\n车型不匹配记录（已过滤，不计入结果）:\n")
                f.write("-" * 30 + "\n")
                for rec in mismatch_records[:20]:  # 只列前20条
                    f.write(f"  期望[{rec['期望车型名称']}] ≠ 实际[{rec['实际点评车型']}]\n")
                if len(mismatch_records) > 20:
                    f.write(f"  ...（共{len(mismatch_records)}条，详见不匹配记录CSV）\n")

            f.write(f"\n文件说明:\n")
            f.write("-" * 30 + "\n")
            f.write(f"  - 主汇总文件: {MAIN_OUTPUT_FILE.replace('.csv', f'_{timestamp}.csv')}\n")
            f.write(f"  - 单车型文件: 车型_[车型名称]_[车型ID]_{timestamp}.csv\n")
            f.write(f"  - 不匹配记录: {MISMATCH_LOG_FILE.replace('.csv', f'_{timestamp}.csv')}\n")
            f.write(f"  - 所有文件位于: {OUTPUT_DIR}/ 目录下\n")

        print(f"📋 爬取报告已生成: {report_file}")

    except Exception as e:
        print(f"❌ 生成报告失败: {e}")


def show_progress_info():
    """显示当前进度信息"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'rb') as f:
                progress_data = pickle.load(f)

            processed_cars = progress_data.get('processed_cars', [])
            all_reviews = progress_data.get('all_reviews', [])
            failed_cars = progress_data.get('failed_cars', [])
            current_index = progress_data.get('current_car_index', 0)

            print("📊 当前进度信息:")
            print(f"  - 已处理车型: {len(processed_cars)} 个")
            print(f"  - 失败车型: {len(failed_cars)} 个")
            print(f"  - 已获取评论: {len(all_reviews)} 条")
            print(f"  - 当前索引: {current_index}")

            if os.path.exists(OUTPUT_DIR):
                files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.csv')]
                print(f"  - 已保存文件: {len(files)} 个")

        except Exception as e:
            print(f"❌ 读取进度信息失败: {e}")
    else:
        print("📋 未发现进度文件，需要重新开始")


# ============================================================
# DongchediReviewScraper — Web集成类（不修改任何V6函数）
# ============================================================
class DongchediReviewScraper:
    def __init__(self, output_dir="outputs"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        global SESSION_POOL
        if not SESSION_POOL:
            init_session_pool()

    def setup_driver(self):
        pass

    def close(self):
        pass

    def get_car_preview(self, car_id):
        url = BASE_URL.format(car_id, 1)
        response = get_page_with_retry(url)
        if not response:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        car_name = ""
        try:
            title = soup.title.string if soup.title else ""
            if title:
                car_name = title.replace("_懂车帝", "").replace("-懂车帝", "").strip()
        except:
            pass
        if not car_name:
            try:
                h1 = soup.find('h1')
                if h1:
                    car_name = h1.get_text(strip=True)
            except:
                car_name = "未知车型"
        total_reviews = 0
        try:
            page_elements = soup.find_all('a', string=re.compile(r'\d+'))
            max_page = 1
            for elem in page_elements:
                text = elem.get_text(strip=True)
                if text.isdigit():
                    page_num = int(text)
                    if page_num > max_page and page_num < 200:
                        max_page = page_num
            if max_page > 1:
                total_reviews = max_page * 20
        except:
            pass
        return {"car_id": car_id, "car_name": car_name,
                "total_reviews": total_reviews, "in_sale_reviews": 0}

    def scrape_with_progress(self, car_id, car_name, progress_callback):
        progress_callback(0, "开始获取懂车帝口碑...")
        all_reviews = []
        page = 1
        consecutive_empty = 0
        mismatch_records = []

        while page <= MAX_PAGES and consecutive_empty < 3:
            progress_callback(min(10 + page * 3, 90), f"爬取第{page}页...")
            url = BASE_URL.format(car_id, page)
            response = get_page_with_retry(url)
            if not response:
                consecutive_empty += 1
                page += 1
                continue

            page_reviews, container_count = parse_review_page(response.text, car_id, page)
            page_reviews = validate_and_filter_reviews(
                page_reviews, car_name, car_id, page, mismatch_records)

            if container_count <= 1 and page > 1:
                break
            if page_reviews:
                all_reviews.extend(page_reviews)
                consecutive_empty = 0
            else:
                consecutive_empty += 1

            soup = BeautifulSoup(response.text, 'html.parser')
            if not has_next_page(soup):
                break
            page += 1
            smart_delay()

        if not all_reviews:
            progress_callback(100, "未获取到任何评论")
            return None

        progress_callback(95, "正在保存...")
        filename = f"dongchedi_{car_name}_{car_id}.csv"
        success = self.save_to_csv(all_reviews, filename)
        if success:
            filepath = os.path.join(self.output_dir, filename)
            progress_callback(100, f"爬取完成，共 {len(all_reviews)} 条评论")
            return filepath
        else:
            progress_callback(100, "保存文件失败")
            return None

    def save_to_csv(self, data, filename):
        try:
            if not data:
                return False
            base_cols = ['车型名称', '车型ID', '页码', '评论序号',
                         '点评车型', '提车时间', '购买地点', '裸车价格',
                         '油耗', '续航', '评论内容']
            score_cols = []
            for row in data:
                for key in row:
                    if key.startswith('评分_') and key not in score_cols:
                        score_cols.append(key)
            fieldnames = base_cols + score_cols
            filepath = os.path.join(self.output_dir, filename)
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                for row in data:
                    writer.writerow(row)
            print(f"💾 数据已保存到 {filepath}")
            return True
        except Exception as e:
            print(f"❌ 保存CSV失败: {e}")
            return False


if __name__ == "__main__":
    print("🚀🚀 懂车帝口碑评论爬虫 - 修复版（解决车型名称不匹配问题）")
    print("=" * 60)

    show_progress_info()

    user_input = input("\n是否开始/继续爬取？(y/n): ").strip().lower()
    if user_input not in ['y', 'yes', '']:
        print("👋 已取消")
        exit()

    start_time = time.time()

    try:
        crawl_car_reviews()
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断爬取")
        print("💾 当前进度已保存，下次运行时可继续")
    except Exception as e:
        print(f"❌ 程序异常: {e}")
        print("💾 当前进度已保存，下次运行时可继续")
    finally:
        elapsed_time = time.time() - start_time
        print(f"\n⏱️ 总耗时: {elapsed_time:.2f}秒")

        for session in SESSION_POOL:
            session.close()

        print("=" * 60)
# 懂车智析 — 汽车口碑采集与智能分析系统

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)](https://flask.palletsprojects.com/)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-purple.svg)](https://deepseek.com/)
[![License](https://img.shields.io/badge/License-Academic%20Use%20Only-orange.svg)]()

面向汽车之家（k.autohome.com.cn）与懂车帝（www.dongchedi.com）的口碑数据全流程分析系统。从数据采集 → AI 智能分析 → 可视化展示的端到端自动化处理。

## ✨ 核心功能

| 阶段 | 功能 | 技术 |
|------|------|------|
| 🔍 **数据采集** | 汽车之家/懂车帝口碑全文爬取 | Selenium + Chrome headless |
| 🤖 **智能分析** | 基于 LLM 的使用场景/满意点/不满意点/改进建议/对比车型提取 | DeepSeek API |
| 📊 **可视化** | 多维度统计聚类 + ECharts 图表 | difflib 文本聚类 |
| 🌐 **Web 界面** | 一站式操作：搜索→爬取→分析→可视化→下载 | Flask + AJAX |

## 📁 项目结构

```
程序V2/
├── app.py                      # Flask Web 主程序，REST API + 异步任务调度
├── p01_visualizer.py           # 可视化引擎：文本聚类 + ECharts JSON 输出
├── p02_autohome_scraper.py     # 汽车之家爬虫：Selenium 全量口碑采集
├── p03_autohome_analyzer.py    # 汽车之家分析器：DeepSeek API 批量分析
├── p04_dongchedi_scraper.py    # 懂车帝爬虫：Selenium 口碑采集
├── p05_dongchedi_analyzer.py   # 懂车帝分析器：DeepSeek API 批量分析
├── database.py                 # SQLite 缓存模块（避免重复爬取）
├── templates/
│   └── index.html              # 前端界面（懂车智析）
├── outputs/                    # 输出目录
│   ├── *.csv                   # 爬取原始数据
│   └── *_分析结果.xlsx          # AI 分析报告
├── .env                        # API Key 配置（不提交）
└── cache.db                    # 爬取缓存数据库
```

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Chrome 浏览器 + 匹配版本的 [ChromeDriver](https://chromedriver.chromium.org/)
- [DeepSeek API Key](https://platform.deepseek.com/)

### 安装

```bash
# 1. 克隆仓库
git clone <repo-url>
cd 程序V2

# 2. 安装依赖
pip install flask requests selenium beautifulsoup4 pandas openpyxl python-dotenv

# 3. 配置 API Key
echo "DEEPSEEK_API_KEY=你的密钥" > .env

# 4. 启动
python app.py
# 访问 http://localhost:5000
```

### 使用流程

1. 在汽车之家/懂车帝找到目标车型 ID（URL 中的数字）
2. 输入车型 ID → 点击「检索口碑」查看预览
3. 点击「开始爬取全部口碑」
4. 爬取完成后点击「前往智能分析」
5. 查看分析摘要 → 生成可视化报告 → 下载 Excel

## 📡 API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web 前端界面 |
| `/api/search` | POST | 检索汽车之家车型口碑概览 |
| `/api/dongchedi/search` | POST | 检索懂车帝车型口碑概览 |
| `/api/scrape` | POST | 启动汽车之家异步爬取 |
| `/api/dongchedi/scrape` | POST | 启动懂车帝异步爬取 |
| `/api/analyze` | POST | 启动 AI 分析 |
| `/api/visualize` | POST | 生成可视化图表数据 |
| `/api/task/<task_id>` | GET | 查询任务进度（实时轮询） |
| `/outputs/<filename>` | GET | 下载输出文件 |

## 📊 AI 分析维度

每条口碑评论通过 DeepSeek LLM 提取 5 个维度：

| 维度 | 说明 | 示例 |
|------|------|------|
| 🏠 使用场景 | 车辆主要用途 | 通勤代步、接送小孩、自驾游 |
| ✅ 满意点 | 用户满意领域 + 具体描述 | 空间→后排腿部空间宽裕 |
| ❌ 不满意点 | 用户不满意领域 + 具体描述 | 续航→冬季续航缩水30% |
| 💡 改进建议 | 用户提出的改进方向 | 增加座椅通风功能 |
| 🆚 对比车型 | 选购时对比的车型 + 对比内容 | 理想L9→价格更低但配置更高 |

## 📦 输出文件

| 类型 | 命名 | 内容 |
|------|------|------|
| CSV | `{车系}_{ID}.csv` | 30+ 列原始口碑数据（评分/评论/购买信息） |
| Excel | `{车系}_{ID}_分析结果.xlsx` | 6 个 Sheet（原始+场景+满意+不满意+建议+对比） |

## 🛠️ 技术要点

- **反爬对抗**：headless Chrome + 自定义 UA + 隐藏 `navigator.webdriver` + 多策略提取隐藏交互数据
- **异步任务**：Flask 多线程 + 前端轮询实时进度条
- **并发分析**：`ThreadPoolExecutor` 5 线程 + 指数退避重试
- **JSON 修复**：LLM 输出截断自动补齐（括号匹配）
- **文本聚类**：`difflib.SequenceMatcher` 相似度聚类（阈值 0.55~0.6）
- **缓存去重**：SQLite 存储已爬取车型，避免重复采集

## ⚠️ 免责声明

本项目仅供学术研究和学习参考。使用者应：
- 遵守目标网站的 Robots 协议和服务条款
- 合理控制请求频率，避免对目标服务器造成负担
- 不得将爬取数据用于商业用途
- API Key 等敏感信息通过 `.env` 管理，切勿提交至公开仓库

## 📝 论文相关

本项目为 MEM 硕士论文《基于在线评论的MPV汽车产品需求识别研究》的技术支撑工具，用于批量获取汽车之家/懂车帝用户口碑数据并进行 LLM 智能分析。

---

**作者**：童鑫 | 武汉大学经济管理学院 MEM | 2026

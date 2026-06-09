# app.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
汽车口碑分析系统 - Flask 主程序
提供 API 接口，串联爬虫与分析引擎，新增可视化接口
"""

import os
import uuid
from threading import Thread
from flask import Flask, request, jsonify, send_from_directory, render_template
from dotenv import load_dotenv

load_dotenv()

from p02_autohome_scraper import AutohomeReviewScraper
from p04_dongchedi_scraper import DongchediReviewScraper
from p03_autohome_analyzer import run_analysis
from p05_dongchedi_analyzer import run_dongchedi_analysis
from p01_visualizer import generate_visualization
from database import check_cache, save_cache

app = Flask(__name__)
app.secret_key = "autohome-review-system-secret-key"

OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

tasks = {}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/search', methods=['POST'])
def search():
    data = request.get_json()
    car_id = data.get('car_id', '').strip()
    if not car_id:
        return jsonify({"error": "车型ID不能为空"}), 400

    cached = check_cache('autohome', car_id)
    scraper = AutohomeReviewScraper(output_dir=OUTPUT_DIR)
    try:
        scraper.setup_driver()
        preview = scraper.get_car_preview(car_id)
        if preview:
            if cached:
                preview['cached'] = cached
            return jsonify(preview)
        else:
            return jsonify({"error": "未找到该车型，请确认ID是否正确"}), 404
    except Exception as e:
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500
    finally:
        scraper.close()


@app.route('/api/dongchedi/search', methods=['POST'])
def dongchedi_search():
    data = request.get_json()
    car_id = data.get('car_id', '').strip()
    if not car_id:
        return jsonify({"error": "车型ID不能为空"}), 400

    cached = check_cache('dongchedi', car_id)
    scraper = DongchediReviewScraper(output_dir=OUTPUT_DIR)
    try:
        preview = scraper.get_car_preview(car_id)
        if preview:
            if cached:
                preview['cached'] = cached
            return jsonify(preview)
        else:
            return jsonify({"error": "未找到该车型，请确认ID是否正确"}), 404
    except Exception as e:
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500
    finally:
        scraper.close()


@app.route('/api/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    car_id = data.get('car_id', '').strip()
    car_name = data.get('car_name', '未知车型')

    if not car_id:
        return jsonify({"error": "车型ID不能为空"}), 400

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "message": "等待开始",
        "type": "scrape"
    }

    thread = Thread(target=_run_scrape_task, args=(task_id, car_id, car_name))
    thread.start()
    return jsonify({"task_id": task_id})


@app.route('/api/dongchedi/scrape', methods=['POST'])
def dongchedi_scrape():
    data = request.get_json()
    car_id = data.get('car_id', '').strip()
    car_name = data.get('car_name', '未知车型')

    if not car_id:
        return jsonify({"error": "车型ID不能为空"}), 400

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "message": "等待开始",
        "type": "dongchedi_scrape"
    }

    thread = Thread(target=_run_dongchedi_scrape_task, args=(task_id, car_id, car_name))
    thread.start()
    return jsonify({"task_id": task_id})


@app.route('/api/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    filename = data.get('file', '').strip()
    if not filename:
        return jsonify({"error": "请指定要分析的文件名"}), 400
    csv_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(csv_path):
        return jsonify({"error": "文件不存在"}), 404
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending", "progress": 0,
        "message": "等待分析", "type": "analyze"
    }
    thread = Thread(target=_run_analysis_task, args=(task_id, csv_path))
    thread.start()
    return jsonify({"task_id": task_id})


@app.route('/api/dongchedi/analyze', methods=['POST'])
def dongchedi_analyze():
    data = request.get_json()
    filename = data.get('file', '').strip()
    if not filename:
        return jsonify({"error": "请指定要分析的文件名"}), 400
    csv_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(csv_path):
        return jsonify({"error": "文件不存在"}), 404
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending", "progress": 0,
        "message": "等待懂车帝分析", "type": "dongchedi_analyze"
    }
    thread = Thread(target=_run_dongchedi_analysis_task, args=(task_id, csv_path))
    thread.start()
    return jsonify({"task_id": task_id})


@app.route('/api/visualize', methods=['POST'])
def visualize():
    data = request.get_json()
    filename = data.get('file', '').strip()
    if not filename:
        return jsonify({"error": "请指定分析结果文件名"}), 400
    excel_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(excel_path):
        return jsonify({"error": "文件不存在"}), 404
    try:
        result = generate_visualization(excel_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"可视化生成失败: {str(e)}"}), 500


@app.route('/api/dongchedi/visualize', methods=['POST'])
def dongchedi_visualize():
    data = request.get_json()
    filename = data.get('file', '').strip()
    if not filename:
        return jsonify({"error": "请指定分析结果文件名"}), 400
    excel_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(excel_path):
        return jsonify({"error": "文件不存在"}), 404
    try:
        result = generate_visualization(excel_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"可视化生成失败: {str(e)}"}), 500


@app.route('/outputs/<path:filename>')
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


def _run_scrape_task(task_id, car_id, car_name):
    def progress_callback(percent, message):
        tasks[task_id] = {
            "status": "running",
            "progress": percent,
            "message": message,
            "type": "scrape"
        }

    scraper = AutohomeReviewScraper(output_dir=OUTPUT_DIR)
    try:
        scraper.setup_driver()
        filepath = scraper.scrape_with_progress(car_id, car_name, progress_callback)
        if filepath:
            filename = os.path.basename(filepath)
            # 写入缓存
            try:
                import pandas as pd
                df = pd.read_csv(filepath, encoding='utf-8-sig')
                save_cache('autohome', car_id, car_name, filename, len(df))
            except Exception:
                pass
            tasks[task_id] = {
                "status": "completed",
                "progress": 100,
                "message": "爬取完成",
                "file": filename,
                "type": "scrape"
            }
        else:
            tasks[task_id] = {
                "status": "failed",
                "progress": 0,
                "message": "未获取到任何口碑数据",
                "type": "scrape"
            }
    except Exception as e:
        tasks[task_id] = {
            "status": "failed",
            "progress": 0,
            "message": f"爬取出错: {str(e)}",
            "type": "scrape"
        }
    finally:
        scraper.close()


def _run_dongchedi_scrape_task(task_id, car_id, car_name):
    def progress_callback(percent, message):
        tasks[task_id] = {
            "status": "running",
            "progress": percent,
            "message": message,
            "type": "dongchedi_scrape"
        }

    scraper = DongchediReviewScraper(output_dir=OUTPUT_DIR)
    try:
        filepath = scraper.scrape_with_progress(car_id, car_name, progress_callback)
        if filepath:
            filename = os.path.basename(filepath)
            try:
                import pandas as pd
                df = pd.read_csv(filepath, encoding='utf-8-sig')
                save_cache('dongchedi', car_id, car_name, filename, len(df))
            except Exception:
                pass
            tasks[task_id] = {
                "status": "completed",
                "progress": 100,
                "message": "懂车帝爬取完成",
                "file": filename,
                "type": "dongchedi_scrape"
            }
        else:
            tasks[task_id] = {
                "status": "failed",
                "progress": 0,
                "message": "未获取到任何懂车帝口碑数据",
                "type": "dongchedi_scrape"
            }
    except Exception as e:
        tasks[task_id] = {
            "status": "failed",
            "progress": 0,
            "message": f"懂车帝爬取出错: {str(e)}",
            "type": "dongchedi_scrape"
        }
    finally:
        scraper.close()


def _run_analysis_task(task_id, csv_path):
    def progress_callback(percent, message):
        tasks[task_id] = {
            "status": "running",
            "progress": percent,
            "message": message,
            "type": "analyze"
        }

    base_name = os.path.splitext(os.path.basename(csv_path))[0]
    output_xlsx = os.path.join(OUTPUT_DIR, f"{base_name}_分析结果.xlsx")

    try:
        summary = run_analysis(csv_path, output_xlsx, progress_callback)
        tasks[task_id] = {
            "status": "completed",
            "progress": 100,
            "message": "分析完成",
            "file": os.path.basename(output_xlsx),
            "summary": summary,
            "type": "analyze"
        }
    except Exception as e:
        tasks[task_id] = {
            "status": "failed",
            "progress": 0,
            "message": f"分析失败: {str(e)}",
            "type": "analyze"
        }


def _run_dongchedi_analysis_task(task_id, csv_path):
    def progress_callback(percent, message):
        tasks[task_id] = {
            "status": "running",
            "progress": percent,
            "message": message,
            "type": "dongchedi_analyze"
        }

    base_name = os.path.splitext(os.path.basename(csv_path))[0]
    output_xlsx = os.path.join(OUTPUT_DIR, f"{base_name}_懂车帝分析结果.xlsx")

    try:
        summary = run_dongchedi_analysis(csv_path, output_xlsx, progress_callback)
        tasks[task_id] = {
            "status": "completed",
            "progress": 100,
            "message": "懂车帝分析完成",
            "file": os.path.basename(output_xlsx),
            "summary": summary,
            "type": "dongchedi_analyze"
        }
    except Exception as e:
        tasks[task_id] = {
            "status": "failed",
            "progress": 0,
            "message": f"懂车帝分析失败: {str(e)}",
            "type": "dongchedi_analyze"
        }


@app.route('/api/task/<task_id>', methods=['GET'])
def task_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"status": "not found"})
    return jsonify(task)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
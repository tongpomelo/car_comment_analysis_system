# database.py
# -*- coding: utf-8 -*-
"""
SQLite 缓存模块 —— 存储爬取元数据，避免重复爬取
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.db")


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    """初始化数据库表"""
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scrape_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            car_id TEXT NOT NULL,
            car_name TEXT NOT NULL,
            csv_filename TEXT NOT NULL,
            review_count INTEGER DEFAULT 0,
            scraped_at TEXT NOT NULL,
            UNIQUE(source, car_id)
        )
    """)
    conn.commit()
    conn.close()


def check_cache(source, car_id):
    """查询缓存，命中返回 dict，否则 None"""
    conn = _conn()
    row = conn.execute(
        "SELECT car_name, csv_filename, review_count, scraped_at FROM scrape_cache WHERE source=? AND car_id=?",
        (source, car_id)
    ).fetchone()
    conn.close()
    if row:
        return {
            "car_name": row[0],
            "csv_filename": row[1],
            "review_count": row[2],
            "scraped_at": row[3],
        }
    return None


def save_cache(source, car_id, car_name, csv_filename, review_count):
    """写入或更新缓存记录"""
    conn = _conn()
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        INSERT INTO scrape_cache (source, car_id, car_name, csv_filename, review_count, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, car_id) DO UPDATE SET
            car_name=excluded.car_name,
            csv_filename=excluded.csv_filename,
            review_count=excluded.review_count,
            scraped_at=excluded.scraped_at
    """, (source, car_id, car_name, csv_filename, review_count, now))
    conn.commit()
    conn.close()


# 启动时自动建表
init_db()

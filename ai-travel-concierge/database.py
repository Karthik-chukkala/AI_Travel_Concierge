import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "travel_cache.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Table 1: route_cache
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS route_cache (
        src_dst TEXT PRIMARY KEY,
        data TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # Table 2: delay_cache
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS delay_cache (
        train_no_duration TEXT PRIMARY KEY,
        delay_data TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # Table 3: schedule_cache
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schedule_cache (
        train_no TEXT PRIMARY KEY,
        schedule_data TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

# Route Cache Helpers
def get_route_cache(src_dst):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM route_cache WHERE src_dst = ?", (src_dst,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row["data"])
    return None

def set_route_cache(src_dst, data):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO route_cache (src_dst, data, timestamp)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (src_dst, json.dumps(data)))
    conn.commit()
    conn.close()

# Delay Cache Helpers
def get_delay_cache(train_no_duration):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT delay_data FROM delay_cache WHERE train_no_duration = ?", (train_no_duration,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row["delay_data"])
    return None

def set_delay_cache(train_no_duration, delay_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO delay_cache (train_no_duration, delay_data, timestamp)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (train_no_duration, json.dumps(delay_data)))
    conn.commit()
    conn.close()

# Schedule Cache Helpers
def get_schedule_cache(train_no):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT schedule_data FROM schedule_cache WHERE train_no = ?", (train_no,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row["schedule_data"])
    return None

def set_schedule_cache(train_no, schedule_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO schedule_cache (train_no, schedule_data, timestamp)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (train_no, json.dumps(schedule_data)))
    conn.commit()
    conn.close()

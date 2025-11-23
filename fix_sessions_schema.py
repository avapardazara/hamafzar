import sqlite3
from pathlib import Path

DB_PATH = Path("instance/app.db")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

def has_column(table, col):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in cur.fetchall())

# add columns if missing
if not has_column("course_sessions", "session_date"):
    cur.execute("ALTER TABLE course_sessions ADD COLUMN session_date DATE")

if not has_column("course_sessions", "start_time"):
    cur.execute("ALTER TABLE course_sessions ADD COLUMN start_time TIME")

if not has_column("course_sessions", "end_time"):
    cur.execute("ALTER TABLE course_sessions ADD COLUMN end_time TIME")

# backfill session_date from date for old rows
cur.execute("""
    UPDATE course_sessions
    SET session_date = DATE(date)
    WHERE session_date IS NULL
""")

conn.commit()
conn.close()

print("✅ schema updated: session_date, start_time, end_time added.")

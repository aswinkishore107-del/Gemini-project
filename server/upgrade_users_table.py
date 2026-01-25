import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

columns = [
    "text_submitted INTEGER DEFAULT 0",
    "image_submitted INTEGER DEFAULT 0",
    "audio_submitted INTEGER DEFAULT 0",
    "video_submitted INTEGER DEFAULT 0",
    "final_submitted INTEGER DEFAULT 0"
]

for col in columns:
    try:
        cur.execute(f"ALTER TABLE users ADD COLUMN {col}")
        print("✅ Added column:", col)
    except sqlite3.OperationalError:
        print("ℹ️ Column already exists:", col)

conn.commit()
conn.close()

print("🎉 users table upgraded successfully")

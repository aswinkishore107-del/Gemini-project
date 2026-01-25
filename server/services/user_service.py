import sqlite3

DB_PATH = "database.db"

def create_user(email, pin):
    conn = sqlite3.connect(DB_PATH, timeout=10)   # ✅ changed
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (email, pin) VALUES (?, ?)", (email, pin))
    conn.commit()
    conn.close()

def validate_pin(pin):
    conn = sqlite3.connect(DB_PATH, timeout=10)   # ✅ changed
    cursor = conn.cursor()
    cursor.execute("SELECT id, email FROM users WHERE pin = ?", (pin,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {"id": row[0], "email": row[1]}

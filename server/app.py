from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import base64
from PIL import Image
import google.generativeai as genai
from dotenv import load_dotenv
from datetime import datetime

from utils.pin_generator import generate_pin
from utils.email_service import send_pin_email

# ================= LOAD ENV =================
load_dotenv()

# ================= FLASK APP =================
app = Flask(__name__)
CORS(app)

# ================= CONFIG =================
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

DB_PATH = "database.db"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

# ================= FRONTEND ROUTES =================

@app.route("/login-page")
def login_page():
    return send_from_directory("public", "index.html")

@app.route("/test-page")
def test_page():
    return send_from_directory("public", "test.html")

@app.route("/admin-page")
def admin_login_page():
    return send_from_directory("public", "admin_login.html")

@app.route("/admin-dashboard")
def admin_dashboard_page():
    return send_from_directory("public", "admin.html")

# ================= CENTRAL STRICT TIME CHECK =================

def check_time_window(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT test_start, test_end, final_submitted
        FROM users WHERE id=?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return False, "User not found"

    test_start, test_end, final_submitted = row

    if final_submitted == 1:
        return False, "Test already final submitted"

    now = datetime.now()
    start = datetime.fromisoformat(test_start)
    end = datetime.fromisoformat(test_end)

    if now < start:
        return False, "Test not started yet"

    if now > end:
        return False, "Test time is over"

    return True, "Allowed"

# ================= ADMIN LOGIN =================

@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.json
    user = data.get("username")
    pwd = data.get("password")

    if user == ADMIN_USER and pwd == ADMIN_PASS:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "Invalid admin credentials"}), 401

# ================= INVITE + EMAIL =================

@app.route("/generate-invite", methods=["POST"])
def generate_invite():
    email = request.json.get("email")
    start_time = request.json.get("start_time")
    end_time = request.json.get("end_time")

    pin = generate_pin()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (email, pin, test_start, test_end, status)
        VALUES (?, ?, ?, ?, ?)
    """, (email, pin, start_time, end_time, "Invited"))
    conn.commit()
    conn.close()

    send_pin_email(email, pin, start_time, end_time)

    return jsonify({"message": "Invite sent successfully"})

# ================= LOGIN =================

@app.route("/validate-pin", methods=["POST"])
def validate_pin_api():
    pin = request.json.get("pin")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, email, test_start, test_end, status
        FROM users WHERE pin = ?
    """, (pin,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "message": "Invalid PIN"})

    user_id, email, test_start, test_end, status = row

    now = datetime.now()
    start = datetime.fromisoformat(test_start)
    end = datetime.fromisoformat(test_end)

    if now < start:
        return jsonify({"success": False, "message": "Test not started yet"})

    if now > end:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE users SET status=? WHERE id=?", ("Time Over", user_id))
        conn.commit()
        conn.close()

        return jsonify({"success": False, "message": "Test time is over"})

    # Mark as started
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET status=? WHERE id=?", ("Started", user_id))
    conn.commit()
    conn.close()

    # 🔴 IMPORTANT: Send BOTH start and end time
    return jsonify({
        "success": True,
        "user_id": user_id,
        "email": email,
        "test_start": test_start,
        "test_end": test_end
    })
# ================= HOME =================
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Backend running successfully 🚀"})

# ================= TEXT ANSWER =================

@app.route("/submit-text-answer", methods=["POST"])
def submit_text_answer():
    data = request.json
    user_id = int(data["user_id"])
    question = data["question"]
    answer = data["answer"]

    allowed, msg = check_time_window(user_id)
    if not allowed:
        return jsonify({"error": msg}), 403

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Freeze check
    cur.execute("SELECT text_submitted FROM users WHERE id=?", (user_id,))
    if cur.fetchone()[0] == 1:
        conn.close()
        return jsonify({"error": "Text already submitted"}), 400

    # ---- AI ANALYSIS ----
    prompt = f"""
You are an AI assistant helping recruiters.

Analyze the following answer and decide whether it is
more likely written by a Human or generated by AI.

Reply strictly:
Result: Human or AI
Reason: short explanation

Text:
{answer}
"""
    response = model.generate_content(prompt)

    # Save answer
    cur.execute("""
        INSERT INTO tests (user_id, question, answer, ai_result)
        VALUES (?, ?, ?, ?)
    """, (user_id, question, answer, response.text))

    # Mark freeze
    cur.execute("UPDATE users SET text_submitted=1 WHERE id=?", (user_id,))

    conn.commit()
    conn.close()

    return jsonify({"ai_result": response.text})

# ================= IMAGE ANSWER =================

@app.route("/submit-image-answer", methods=["POST"])
def submit_image_answer():
    user_id = int(request.form.get("user_id"))
    question = request.form.get("question")

    allowed, msg = check_time_window(user_id)
    if not allowed:
        return jsonify({"error": msg}), 403

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT image_submitted FROM users WHERE id=?", (user_id,))
    if cur.fetchone()[0] == 1:
        conn.close()
        return jsonify({"error": "Image already submitted"}), 400

    if "file" not in request.files:
        conn.close()
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    img = Image.open(path)

    prompt = """
You are an AI forensic expert.

Reply:
Result: AI or Real
Reason: one short sentence
"""
    response = model.generate_content([prompt, img])

    cur.execute("""
        INSERT INTO tests (user_id, question, answer, ai_result)
        VALUES (?, ?, ?, ?)
    """, (user_id, question, file.filename, response.text))

    cur.execute("UPDATE users SET image_submitted=1 WHERE id=?", (user_id,))

    conn.commit()
    conn.close()

    return jsonify({"ai_result": response.text})

# ================= AUDIO ANSWER =================

@app.route("/submit-audio-answer", methods=["POST"])
def submit_audio():
    user_id = int(request.form.get("user_id"))
    question = request.form.get("question")

    allowed, msg = check_time_window(user_id)
    if not allowed:
        return jsonify({"error": msg}), 403

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT audio_submitted FROM users WHERE id=?", (user_id,))
    if cur.fetchone()[0] == 1:
        conn.close()
        return jsonify({"error": "Audio already submitted"}), 400

    if "file" not in request.files:
        conn.close()
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    with open(path, "rb") as f:
        audio_bytes = f.read()

    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

    prompt = """
Analyze this audio.

Reply:
Result: Human or AI
Reason: short explanation
"""
    response = model.generate_content([
        prompt,
        {"mime_type": "audio/wav", "data": audio_base64}
    ])

    cur.execute("""
        INSERT INTO tests (user_id, question, answer, ai_result)
        VALUES (?, ?, ?, ?)
    """, (user_id, question, file.filename, response.text))

    cur.execute("UPDATE users SET audio_submitted=1 WHERE id=?", (user_id,))

    conn.commit()
    conn.close()

    return jsonify({"ai_result": response.text})

# ================= VIDEO ANSWER =================

@app.route("/submit-video-answer", methods=["POST"])
def submit_video():
    user_id = int(request.form.get("user_id"))
    question = request.form.get("question")

    allowed, msg = check_time_window(user_id)
    if not allowed:
        return jsonify({"error": msg}), 403

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT video_submitted FROM users WHERE id=?", (user_id,))
    if cur.fetchone()[0] == 1:
        conn.close()
        return jsonify({"error": "Video already submitted"}), 400

    if "file" not in request.files:
        conn.close()
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    with open(path, "rb") as f:
        video_bytes = f.read()

    video_base64 = base64.b64encode(video_bytes).decode("utf-8")

    prompt = """
Analyze this video.

Reply:
Result: Real or AI
Reason: short explanation
"""
    response = model.generate_content([
        prompt,
        {"mime_type": "video/mp4", "data": video_base64}
    ])

    cur.execute("""
        INSERT INTO tests (user_id, question, answer, ai_result)
        VALUES (?, ?, ?, ?)
    """, (user_id, question, file.filename, response.text))

    cur.execute("UPDATE users SET video_submitted=1 WHERE id=?", (user_id,))

    conn.commit()
    conn.close()

    return jsonify({"ai_result": response.text})

# ================= FINAL SUBMIT =================

@app.route("/mark-submitted", methods=["POST"])
def mark_submitted():
    data = request.json
    user_id = int(data["user_id"])

    allowed, msg = check_time_window(user_id)
    if not allowed:
        return jsonify({"error": msg}), 403

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT final_submitted FROM users WHERE id=?", (user_id,))
    if cur.fetchone()[0] == 1:
        conn.close()
        return jsonify({"error": "Already final submitted"}), 400

    cur.execute("""
        UPDATE users 
        SET status=?, final_submitted=1 
        WHERE id=?
    """, ("Submitted", user_id))

    conn.commit()
    conn.close()

    return jsonify({"success": True})

@app.route("/submission-status/<int:user_id>")
def submission_status(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
      SELECT text_submitted, image_submitted,
             audio_submitted, video_submitted,
             final_submitted
      FROM users WHERE id=?
    """, (user_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "text":  bool(row[0]),
        "image": bool(row[1]),
        "audio": bool(row[2]),
        "video": bool(row[3]),
        "final": bool(row[4])
    })

# ================= ADMIN: ALL RESULTS =================

@app.route("/admin/all-results")
def admin_all_results():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get all users
    cur.execute("""
        SELECT id, email, status, test_start, test_end
        FROM users
        ORDER BY id DESC
    """)
    users = cur.fetchall()

    result = {}

    for u in users:
        user_id, email, status, test_start, test_end = u

        # Get answers
        cur.execute("""
            SELECT question, answer, ai_result
            FROM tests
            WHERE user_id=?
            ORDER BY id ASC
        """, (user_id,))
        answers = cur.fetchall()

        result[user_id] = {
            "email": email,
            "status": status,
            "test_start": test_start,
            "test_end": test_end,
            "answers": [
                {
                    "question": a[0],
                    "answer": a[1],
                    "ai_result": a[2]
                } for a in answers
            ]
        }

    conn.close()
    return jsonify(result)

# ================= ADMIN: FINAL VERDICT =================

@app.route("/admin/final-verdict/<int:user_id>")
def final_verdict(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get all AI results for this user
    cur.execute("""
        SELECT ai_result FROM tests
        WHERE user_id=?
        ORDER BY id ASC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return jsonify({"final_verdict": "No submissions found."})

    combined_results = "\n".join([r[0] for r in rows])

    prompt = f"""
You are an expert hiring evaluator.

Given the following AI analysis results from a candidate's test,
decide whether the candidate is likely:

- Genuine human candidate
- AI-assisted candidate
- Suspicious / unreliable

Also give:
1. Final decision: Accept / Review / Reject
2. Short reason (3–4 lines)

AI ANALYSIS RESULTS:
{combined_results}
"""

    response = model.generate_content(prompt)

    return jsonify({
        "final_verdict": response.text
    })



# ================= RUN =================

if __name__ == "__main__":
    app.run(port=5000, debug=True)

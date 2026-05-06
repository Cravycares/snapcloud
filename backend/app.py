"""
SnapCloud — Flask REST API
Azure App Service backend
Uses SQLite locally; swap to Azure Cosmos DB via env vars in production.
"""

import os, sqlite3, uuid, hashlib, hmac, base64, json, time
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g
from flask_cors import CORS

# Resolve paths relative to this file so the app works from any working dir
_HERE = os.path.dirname(os.path.abspath(__file__))

# ── Optional Azure SDK imports (graceful fallback) ──────────────────────────
try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
    AZURE_BLOB = True
except ImportError:
    AZURE_BLOB = False

try:
    from azure.cognitiveservices.vision.computervision import ComputerVisionClient
    from msrest.authentication import CognitiveServicesCredentials
    AZURE_CV = True
except ImportError:
    AZURE_CV = False

# ── App init ─────────────────────────────────────────────────────────────────
_FRONTEND = os.path.join(_HERE, "..", "frontend")
app = Flask(__name__, static_folder=_FRONTEND, static_url_path="")
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ── Config from environment variables ────────────────────────────────────────
DB_PATH            = os.environ.get("DB_PATH", os.path.join(_HERE, "snapcloud.db"))
JWT_SECRET         = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
AZURE_STORAGE_CONN = "DefaultEndpointsProtocol=https;AccountName=snapcloudpelumi;AccountKey=7l43liclVGyHFbi9GmBuQHR8grfJB2YjIHtB0HkF18KtFTm5hk6YRY+v9Mq7iK3N+NcsZTP143XO+AStf/EBuA==;EndpointSuffix=core.windows.net"
AZURE_CONTAINER    = os.environ.get("AZURE_BLOB_CONTAINER", "photos")
AZURE_CV_KEY       = os.environ.get("AZURE_COGNITIVE_KEY", "")
AZURE_CV_ENDPOINT  = os.environ.get("AZURE_COGNITIVE_ENDPOINT", "")

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT    NOT NULL,
            email    TEXT    UNIQUE NOT NULL,
            password TEXT    NOT NULL,
            role     TEXT    NOT NULL DEFAULT 'consumer',
            created_at TEXT  DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS photos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id  INTEGER NOT NULL REFERENCES users(id),
            title       TEXT    NOT NULL,
            caption     TEXT,
            location    TEXT,
            people      TEXT,
            image_url   TEXT,
            blob_name   TEXT,
            ai_tags     TEXT    DEFAULT '[]',
            view_count  INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now')),
            updated_at  TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS comments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id   INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            text       TEXT    NOT NULL,
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ratings (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            user_id  INTEGER NOT NULL REFERENCES users(id),
            rating   INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            UNIQUE(photo_id, user_id)
        );
    """)
    # Seed demo users
    pw_creator  = _hash_password("demo1234")
    pw_consumer = _hash_password("demo1234")
    try:
        db.execute("INSERT OR IGNORE INTO users (name,email,password,role) VALUES (?,?,?,?)",
                   ("Jamie Creator", "creator@demo.com", pw_creator, "creator"))
        db.execute("INSERT OR IGNORE INTO users (name,email,password,role) VALUES (?,?,?,?)",
                   ("Sam Consumer", "consumer@demo.com", pw_consumer, "consumer"))
        db.commit()
    except Exception:
        pass
    db.close()

# ── Auth helpers ──────────────────────────────────────────────────────────────
def _hash_password(pw: str) -> str:
    salt = "snapcloud_salt"
    return hmac.new(salt.encode(), pw.encode(), hashlib.sha256).hexdigest()

def _make_token(user_id: int, role: str) -> str:
    payload = {"sub": user_id, "role": role, "exp": int(time.time()) + 86400 * 7}
    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig  = hmac.new(JWT_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"

def _verify_token(token: str):
    try:
        data, sig = token.rsplit(".", 1)
        expected = hmac.new(JWT_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected): return None
        payload = json.loads(base64.urlsafe_b64decode(data + "=="))
        if payload["exp"] < time.time(): return None
        return payload
    except Exception:
        return None

def require_auth(roles=None):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            token = auth.replace("Bearer ", "").strip()
            payload = _verify_token(token)
            if not payload:
                return jsonify({"error": "Unauthorised"}), 401
            if roles and payload["role"] not in roles:
                return jsonify({"error": "Forbidden"}), 403
            g.user_id = payload["sub"]
            g.user_role = payload["role"]
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ── Azure helpers ─────────────────────────────────────────────────────────────
def upload_to_blob(file_bytes: bytes, filename: str, content_type: str) -> str:
    if AZURE_BLOB and AZURE_STORAGE_CONN:
        client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONN)
        blob = client.get_blob_client(container=AZURE_CONTAINER, blob=filename)
        blob.upload_blob(file_bytes, overwrite=True,
                         content_settings=ContentSettings(content_type=content_type))
        return blob.url
    # Fallback: save locally during development
    os.makedirs("uploads", exist_ok=True)
    path = os.path.join("uploads", filename)
    with open(path, "wb") as fh:
        fh.write(file_bytes)
    return f"/uploads/{filename}"

def get_ai_tags(image_url: str) -> list:
    if AZURE_CV and AZURE_CV_KEY and AZURE_CV_ENDPOINT:
        try:
            creds  = CognitiveServicesCredentials(AZURE_CV_KEY)
            client = ComputerVisionClient(AZURE_CV_ENDPOINT, creds)
            result = client.analyze_image(image_url, visual_features=["Tags"])
            return [t.name for t in result.tags if t.confidence > 0.7][:8]
        except Exception:
            pass
    return []   # No CV configured — return empty list

# ── Row helpers ───────────────────────────────────────────────────────────────
def photo_row_to_dict(row, db=None, include_avg=True) -> dict:
    d = dict(row)
    try: d["ai_tags"] = json.loads(d.get("ai_tags") or "[]")
    except Exception: d["ai_tags"] = []
    if include_avg and db:
        r = db.execute("SELECT AVG(rating) as avg, COUNT(*) as cnt FROM ratings WHERE photo_id=?", (d["id"],)).fetchone()
        d["avg_rating"]    = round(r["avg"], 2) if r["avg"] else None
        d["rating_count"]  = r["cnt"]
        d["comment_count"] = db.execute("SELECT COUNT(*) FROM comments WHERE photo_id=?", (d["id"],)).fetchone()[0]
    return d

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

# Serve frontend
@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    from flask import send_from_directory
    uploads_dir = os.path.join(_HERE, "uploads")
    return send_from_directory(uploads_dir, filename)

@app.route("/<path:path>")
def static_files(path):
    return app.send_static_file(path)

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    name  = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    pw    = data.get("password", "")
    role  = data.get("role", "consumer")

    if not name or not email or not pw:
        return jsonify({"error": "Name, email and password are required"}), 400
    if len(pw) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if role not in ("consumer",):  # creators are admin-created only
        role = "consumer"

    db = get_db()
    if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        return jsonify({"error": "An account with this email already exists"}), 409

    db.execute("INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)",
               (name, email, _hash_password(pw), role))
    db.commit()
    return jsonify({"message": "Account created successfully"}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    pw    = data.get("password", "")
    db    = get_db()
    user  = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user or user["password"] != _hash_password(pw):
        return jsonify({"error": "Invalid email or password"}), 401
    token = _make_token(user["id"], user["role"])
    return jsonify({
        "token": token,
        "user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}
    })

# ── Photos ────────────────────────────────────────────────────────────────────
@app.route("/api/photos", methods=["GET"])
def list_photos():
    db      = get_db()
    q       = request.args.get("q", "").strip()
    tag     = request.args.get("tag", "").strip().lower()
    sort    = request.args.get("sort", "recent")
    page    = max(1, int(request.args.get("page", 1)))
    limit   = min(24, int(request.args.get("limit", 8)))
    offset  = (page - 1) * limit

    sql    = "SELECT p.*, u.name as creator_name FROM photos p JOIN users u ON p.creator_id=u.id WHERE 1=1"
    params = []
    if q:
        sql += " AND (p.title LIKE ? OR p.caption LIKE ? OR p.ai_tags LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if tag:
        sql += " AND (p.ai_tags LIKE ? OR p.caption LIKE ?)"
        params += [f"%{tag}%", f"%{tag}%"]

    total = db.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]

    order = "p.created_at DESC"
    if sort == "rating":
        order = "(SELECT AVG(r.rating) FROM ratings r WHERE r.photo_id=p.id) DESC NULLS LAST"
    elif sort == "views":
        order = "p.view_count DESC"

    sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
    rows = db.execute(sql, params + [limit + 1, offset]).fetchall()
    has_more = len(rows) > limit
    photos = [photo_row_to_dict(r, db) for r in rows[:limit]]

    return jsonify({"photos": photos, "total": total, "page": page, "has_more": has_more})


@app.route("/api/photos/mine", methods=["GET"])
@require_auth(["creator"])
def list_mine():
    db    = get_db()
    rows  = db.execute("SELECT * FROM photos WHERE creator_id=? ORDER BY created_at DESC", (g.user_id,)).fetchall()
    photos = [photo_row_to_dict(r, db) for r in rows]
    return jsonify({"photos": photos})


@app.route("/api/photos/<int:photo_id>", methods=["GET"])
def get_photo(photo_id):
    db  = get_db()
    row = db.execute("SELECT p.*,u.name as creator_name FROM photos p JOIN users u ON p.creator_id=u.id WHERE p.id=?", (photo_id,)).fetchone()
    if not row: return jsonify({"error": "Photo not found"}), 404
    db.execute("UPDATE photos SET view_count=view_count+1 WHERE id=?", (photo_id,))
    db.commit()
    return jsonify({"photo": photo_row_to_dict(row, db)})


@app.route("/api/photos", methods=["POST"])
@require_auth(["creator"])
def upload_photo():
    if "photo" not in request.files:
        return jsonify({"error": "No photo file provided"}), 400

    file     = request.files["photo"]
    title    = (request.form.get("title") or "").strip()
    caption  = (request.form.get("caption") or "").strip()
    location = (request.form.get("location") or "").strip()
    people   = (request.form.get("people") or "").strip()

    if not title: return jsonify({"error": "Title is required"}), 400

    file_bytes   = file.read()
    ext          = (file.filename or "jpg").rsplit(".", 1)[-1].lower()
    blob_name    = f"{uuid.uuid4().hex}.{ext}"
    image_url    = upload_to_blob(file_bytes, blob_name, file.content_type or "image/jpeg")
    ai_tags      = get_ai_tags(image_url)

    db = get_db()
    cur = db.execute(
        "INSERT INTO photos (creator_id,title,caption,location,people,image_url,blob_name,ai_tags) VALUES (?,?,?,?,?,?,?,?)",
        (g.user_id, title, caption, location, people, image_url, blob_name, json.dumps(ai_tags))
    )
    db.commit()
    row = db.execute("SELECT * FROM photos WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"photo": photo_row_to_dict(row, db)}), 201


@app.route("/api/photos/<int:photo_id>", methods=["PUT"])
@require_auth(["creator"])
def update_photo(photo_id):
    db  = get_db()
    row = db.execute("SELECT * FROM photos WHERE id=? AND creator_id=?", (photo_id, g.user_id)).fetchone()
    if not row: return jsonify({"error": "Photo not found or not yours"}), 404
    data = request.get_json() or {}
    db.execute("UPDATE photos SET title=?,caption=?,location=?,updated_at=datetime('now') WHERE id=?",
               (data.get("title", row["title"]), data.get("caption", row["caption"]),
                data.get("location", row["location"]), photo_id))
    db.commit()
    return jsonify({"message": "Updated"})


@app.route("/api/photos/<int:photo_id>", methods=["DELETE"])
@require_auth(["creator"])
def delete_photo(photo_id):
    db  = get_db()
    row = db.execute("SELECT * FROM photos WHERE id=? AND creator_id=?", (photo_id, g.user_id)).fetchone()
    if not row: return jsonify({"error": "Photo not found or not yours"}), 404
    db.execute("DELETE FROM photos WHERE id=?", (photo_id,))
    db.commit()
    return jsonify({"message": "Deleted"})

# ── Comments ──────────────────────────────────────────────────────────────────
@app.route("/api/photos/<int:photo_id>/comments", methods=["GET"])
def get_comments(photo_id):
    db   = get_db()
    rows = db.execute(
        "SELECT c.*,u.name as user_name FROM comments c JOIN users u ON c.user_id=u.id WHERE c.photo_id=? ORDER BY c.created_at DESC",
        (photo_id,)).fetchall()
    return jsonify({"comments": [dict(r) for r in rows]})


@app.route("/api/photos/<int:photo_id>/comments", methods=["POST"])
@require_auth(["consumer"])
def add_comment(photo_id):
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text: return jsonify({"error": "Comment text is required"}), 400
    db = get_db()
    if not db.execute("SELECT id FROM photos WHERE id=?", (photo_id,)).fetchone():
        return jsonify({"error": "Photo not found"}), 404
    db.execute("INSERT INTO comments (photo_id,user_id,text) VALUES (?,?,?)", (photo_id, g.user_id, text))
    db.commit()
    return jsonify({"message": "Comment added"}), 201

# ── Ratings ───────────────────────────────────────────────────────────────────
@app.route("/api/photos/<int:photo_id>/rate", methods=["POST"])
@require_auth(["consumer"])
def rate_photo(photo_id):
    data   = request.get_json() or {}
    rating = data.get("rating")
    if not isinstance(rating, int) or not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be 1-5"}), 400
    db = get_db()
    db.execute("INSERT INTO ratings (photo_id,user_id,rating) VALUES (?,?,?) ON CONFLICT(photo_id,user_id) DO UPDATE SET rating=excluded.rating",
               (photo_id, g.user_id, rating))
    db.commit()
    avg = db.execute("SELECT AVG(rating) FROM ratings WHERE photo_id=?", (photo_id,)).fetchone()[0]
    return jsonify({"message": "Rated", "avg_rating": round(avg, 2) if avg else None})

# ── Creators list (sidebar) ───────────────────────────────────────────────────
@app.route("/api/creators", methods=["GET"])
def list_creators():
    db   = get_db()
    rows = db.execute(
        "SELECT u.id, u.name, COUNT(p.id) as photo_count FROM users u LEFT JOIN photos p ON p.creator_id=u.id WHERE u.role='creator' GROUP BY u.id ORDER BY photo_count DESC LIMIT 10"
    ).fetchall()
    return jsonify({"creators": [dict(r) for r in rows]})

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")

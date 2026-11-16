import sqlite3
import secrets
import string
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, redirect, url_for

app = Flask(__name__)
DB_NAME = "licenses.db"

# ==================== Database Setup ====================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_code TEXT UNIQUE NOT NULL,
                tier TEXT NOT NULL,
                duration_days INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'unactivated',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                activated_at DATETIME,
                expires_at DATETIME
            )
        ''')
        # إنشاء مفاتيح أولية تجريبية إذا كان الجدول فارغاً
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM keys")
        if cur.fetchone()[0] == 0:
            sample_keys = [
                ("XYZ-DEMO-VIP1", "VIP", 30),
                ("XYZ-DEMO-BASIC", "Basic", 7),
                ("XYZ-DEMO-LIFE", "Lifetime", 9999)
            ]
            for code, tier, days in sample_keys:
                conn.execute(
                    "INSERT INTO keys (key_code, tier, duration_days, status) VALUES (?, ?, ?, 'unactivated')",
                    (code, tier, days)
                )
        conn.commit()

init_db()

# ==================== Key Generator Helper ====================
def generate_key_string(prefix="XYZ"):
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(secrets.choice(chars) for _ in range(4))
    part2 = ''.join(secrets.choice(chars) for _ in range(4))
    part3 = ''.join(secrets.choice(chars) for _ in range(4))
    return f"{prefix}-{part1}-{part2}-{part3}"

# ==================== API Endpoint: Verify Key ====================
@app.route("/api/verify", methods=["POST"])
def verify_key():
    data = request.get_json(silent=True) or {}
    key_input = data.get("key", "").strip()

    if not key_input:
        return jsonify({"valid": False, "message": "المفتاح مطلوب"}), 400

    now = datetime.now()

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM keys WHERE key_code = ?", (key_input,))
        key_record = cur.fetchone()

        if not key_record:
            return jsonify({"valid": False, "message": "المفتاح غير موجود أو غير صالح"}), 404

        status = key_record["status"]
        tier = key_record["tier"]
        duration = key_record["duration_days"]

        # إذا كان المفتاح محظوراً
        if status == "banned":
            return jsonify({"valid": False, "message": "تم إيقاف هذا المفتاح من قبل الإدارة"}), 403

        # إذا كان المفتاح جديداً (لم يُفعّل بعد) -> يتم تفعيله وبدء عداد الوقت
        if status == "unactivated":
            if tier == "Lifetime" or duration >= 9999:
                expires_at = None
                days_left = 9999
            else:
                expires_at = now + timedelta(days=duration)
                days_left = duration

            conn.execute(
                "UPDATE keys SET status = 'active', activated_at = ?, expires_at = ? WHERE id = ?",
                (now.strftime("%Y-%m-%d %H:%M:%S"), expires_at.strftime("%Y-%m-%d %H:%M:%S") if expires_at else None, key_record["id"])
            )
            conn.commit()

            return jsonify({
                "valid": True,
                "tier": tier,
                "status": "activated_now",
                "expires_at": expires_at.strftime("%Y-%m-%d") if expires_at else "دائم (Lifetime)",
                "days_left": days_left
            })

        # إذا كان مفعلاً سابقاً، نتحقق من انتهاء الصلاحية
        if status == "active":
            if tier == "Lifetime" or not key_record["expires_at"]:
                return jsonify({
                    "valid": True,
                    "tier": tier,
                    "status": "active",
                    "expires_at": "دائم (Lifetime)",
                    "days_left": "Unlimited"
                })

            expires_at = datetime.strptime(key_record["expires_at"], "%Y-%m-%d %H:%M:%S")
            if now > expires_at:
                conn.execute("UPDATE keys SET status = 'expired' WHERE id = ?", (key_record["id"],))
                conn.commit()
                return jsonify({"valid": False, "message": "انتهت صلاحية هذا المفتاح"}), 403

            days_left = (expires_at - now).days + 1
            return jsonify({
                "valid": True,
                "tier": tier,
                "status": "active",
                "expires_at": expires_at.strftime("%Y-%m-%d"),
                "days_left": days_left
            })

        if status == "expired":
            return jsonify({"valid": False, "message": "هذا المفتاح منتهي الصلاحية"}), 403

    return jsonify({"valid": False, "message": "خطأ غير متوقع في التحقق"}), 500


# ==================== Web Dashboard (Admin Panel) ====================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تحكم مفاتيح XYZ</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background-color: #09090B; color: #F4F4F5; padding: 25px; }
        .container { max-width: 1050px; margin: 0 auto; }
        
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; border-bottom: 1px solid #27272A; padding-bottom: 15px; }
        .header h1 { font-size: 24px; color: #E4E4E7; display: flex; align-items: center; gap: 10px; }
        .header h1 span { color: #DC2626; font-weight: 900; }
        
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }
        .stat-card { background: #121216; border: 1px solid #27272A; border-radius: 12px; padding: 18px; }
        .stat-card h3 { font-size: 13px; color: #A1A1AA; margin-bottom: 6px; }
        .stat-card p { font-size: 24px; font-weight: bold; color: #FFFFFF; }
        
        .card { background: #121216; border: 1px solid #27272A; border-radius: 14px; padding: 20px; margin-bottom: 25px; }
        .card h2 { font-size: 18px; margin-bottom: 15px; color: #E4E4E7; display: flex; align-items: center; gap: 8px; }
        
        .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; align-items: flex-end; }
        label { display: block; font-size: 12px; color: #A1A1AA; margin-bottom: 6px; }
        select, input { width: 100%; padding: 10px 14px; background: #070709; border: 1px solid #27272A; border-radius: 8px; color: #FFF; font-size: 13px; outline: none; }
        select:focus, input:focus { border-color: #DC2626; }
        
        .btn { padding: 10px 18px; border-radius: 8px; font-weight: bold; cursor: pointer; border: none; font-size: 13px; transition: 0.2s; }
        .btn-red { background: #DC2626; color: white; width: 100%; }
        .btn-red:hover { background: #B91C1C; }
        .btn-sm { padding: 5px 10px; font-size: 11px; }
        .btn-del { background: #3F1218; color: #EF4444; }
        .btn-del:hover { background: #DC2626; color: white; }
        
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
        th { text-align: right; padding: 12px 14px; background: #18181F; color: #A1A1AA; font-weight: 600; border-bottom: 1px solid #27272A; }
        td { padding: 12px 14px; border-bottom: 1px solid #1F1F24; color: #D4D4D8; }
        tr:hover { background: #16161C; }
        
        .key-text { font-family: 'Consolas', monospace; color: #F4F4F5; font-weight: bold; background: #09090B; padding: 3px 8px; border-radius: 6px; border: 1px solid #27272A; }
        
        .badge { padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: bold; }
        .badge-vip { background: #2D1418; color: #F87171; border: 1px solid #7F1D1D; }
        .badge-basic { background: #1E293B; color: #94A3B8; border: 1px solid #334155; }
        .badge-life { background: #261E0A; color: #FBBF24; border: 1px solid #78350F; }
        
        .status-unact { color: #A1A1AA; }
        .status-active { color: #22C55E; font-weight: bold; }
        .status-expired { color: #EF4444; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><span>XYZ</span> لوحة التحكم بالمفاتيح والتراخيص</h1>
            <span style="color:#A1A1AA; font-size:12px;">منفذ الاتصال: 5000 (Local Server)</span>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <h3>إجمالي المفاتيح</h3>
                <p>{{ total_keys }}</p>
            </div>
            <div class="stat-card">
                <h3>المفاتيح النشطة</h3>
                <p style="color:#22C55E;">{{ active_keys }}</p>
            </div>
            <div class="stat-card">
                <h3>المفاتيح غير المفعلة</h3>
                <p style="color:#A1A1AA;">{{ unact_keys }}</p>
            </div>
            <div class="stat-card">
                <h3>المفاتيح المنتهية</h3>
                <p style="color:#EF4444;">{{ expired_keys }}</p>
            </div>
        </div>

        <div class="card">
            <h2>⚡ إنشاء مفاتيح جديدة</h2>
            <form action="{{ url_for('create_key') }}" method="POST" class="form-grid">
                <div>
                    <label>نوع العضوية (Tier):</label>
                    <select name="tier" id="tierSelect" onchange="autoFillDuration()">
                        <option value="Basic">Basic (عادي)</option>
                        <option value="VIP" selected>VIP (مميز)</option>
                        <option value="Lifetime">Lifetime (مدى الحياة)</option>
                    </select>
                </div>
                <div>
                    <label>المدة بالأيام:</label>
                    <input type="number" name="duration" id="durationInput" value="30" min="1" required>
                </div>
                <div>
                    <label>العدد المطلوب:</label>
                    <input type="number" name="count" value="1" min="1" max="50" required>
                </div>
                <div>
                    <button type="submit" class="btn btn-red">توليد المفاتيح الآن</button>
                </div>
            </form>
        </div>

        <div class="card">
            <h2>🔑 جدول المفاتيح المسجلة</h2>
            <table>
                <thead>
                    <tr>
                        <th>المفتاح (Key Code)</th>
                        <th>العضوية</th>
                        <th>المدة</th>
                        <th>الحالة</th>
                        <th>تاريخ الانتهاء</th>
                        <th>إجراءات</th>
                    </tr>
                </thead>
                <tbody>
                    {% for k in keys_list %}
                    <tr>
                        <td>
                            <span class="key-text">{{ k.key_code }}</span>
                            <button class="btn btn-sm" style="background:#27272A; color:#FFF; margin-right:5px;" onclick="navigator.clipboard.writeText('{{ k.key_code }}'); alert('تم النسخ!');">نسخ</button>
                        </td>
                        <td>
                            {% if k.tier == 'VIP' %}
                                <span class="badge badge-vip">VIP</span>
                            {% elif k.tier == 'Lifetime' %}
                                <span class="badge badge-life">Lifetime</span>
                            {% else %}
                                <span class="badge badge-basic">Basic</span>
                            {% endif %}
                        </td>
                        <td>{{ k.duration_days }} يوم</td>
                        <td>
                            {% if k.status == 'active' %}
                                <span class="status-active">● نشط</span>
                            {% elif k.status == 'expired' %}
                                <span class="status-expired">● منتهي</span>
                            {% else %}
                                <span class="status-unact">○ غير مفعل بعد</span>
                            {% endif %}
                        </td>
                        <td>{{ k.expires_at if k.expires_at else '---' }}</td>
                        <td>
                            <form action="{{ url_for('delete_key', key_id=k.id) }}" method="POST" style="display:inline;">
                                <button type="submit" class="btn btn-sm btn-del" onclick="return confirm('هل أنت متأكد من حذف هذا المفتاح؟')">حذف</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        function autoFillDuration() {
            var tier = document.getElementById("tierSelect").value;
            var input = document.getElementById("durationInput");
            if (tier === "Basic") input.value = 7;
            else if (tier === "VIP") input.value = 30;
            else if (tier === "Lifetime") input.value = 9999;
        }
    </script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM keys ORDER BY id DESC")
        keys_list = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM keys")
        total_keys = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM keys WHERE status = 'active'")
        active_keys = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM keys WHERE status = 'unactivated'")
        unact_keys = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM keys WHERE status = 'expired'")
        expired_keys = cur.fetchone()[0]

    return render_template_string(
        HTML_TEMPLATE,
        keys_list=keys_list,
        total_keys=total_keys,
        active_keys=active_keys,
        unact_keys=unact_keys,
        expired_keys=expired_keys
    )

@app.route("/keys/create", methods=["POST"])
def create_key():
    tier = request.form.get("tier", "Basic")
    try:
        duration = int(request.form.get("duration", 30))
        count = int(request.form.get("count", 1))
    except ValueError:
        duration = 30
        count = 1

    with get_db() as conn:
        for _ in range(count):
            new_key = generate_key_string()
            conn.execute(
                "INSERT INTO keys (key_code, tier, duration_days, status) VALUES (?, ?, ?, 'unactivated')",
                (new_key, tier, duration)
            )
        conn.commit()

    return redirect(url_for("dashboard"))

@app.route("/keys/delete/<int:key_id>", methods=["POST"])
def delete_key(key_id):
    with get_db() as conn:
        conn.execute("DELETE FROM keys WHERE id = ?", (key_id,))
        conn.commit()
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    print("==================================================")
    print("  XYZ License Management Server Running")
    print("  Dashboard: http://127.0.0.1:5000")
    print("==================================================")
    app.run(host="0.0.0.0", port=5000, debug=False)

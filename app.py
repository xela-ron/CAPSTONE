"""
MMSU CCIS Parking & Monitoring System
Main Flask Application - User Side
Combined: Beautiful UI + Working QR Scanner + Entry/Exit Tracking
"""

from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_file
import sqlite3
import hashlib
import os
import json
import qrcode
import io
import base64
from datetime import datetime
from functools import wraps
import pytz
import time

PH_TZ = pytz.timezone("Asia/Manila")

def ph_now():
    """Returns current Philippine time as a formatted string."""
    return datetime.now(PH_TZ).strftime("%Y-%m-%d %H:%M:%S")

def ph_today():
    """Returns current Philippine date string for DB queries."""
    return datetime.now(PH_TZ).strftime("%Y-%m-%d")

app = Flask(__name__)
app.secret_key = "mmsu_ccis_parking_2024_secret"
DB_FILE = "rfid_logs.db"
last_rfid_scan = None

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no    TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name     TEXT,
            college       TEXT,
            department    TEXT,
            email         TEXT,
            position      TEXT DEFAULT 'Student',
            vehicle_model TEXT,
            vehicle_color TEXT,
            vehicle_type  TEXT,
            tag_id        TEXT,
            is_admin      INTEGER DEFAULT 0,
            created_at    TEXT DEFAULT (datetime('now', '+8 hours'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS rfid_scans (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_id    TEXT NOT NULL,
            scan_time TEXT NOT NULL,
            rssi      TEXT,
            antenna   TEXT,
            scan_type TEXT DEFAULT 'entry'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tag_registry (
            tag_id       TEXT PRIMARY KEY,
            name         TEXT,
            student_no   TEXT,
            department   TEXT,
            course       TEXT,
            vehicle_type TEXT,
            position     TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT,
            message    TEXT,
            created_at TEXT DEFAULT (datetime('now', '+8 hours')),
            created_by TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS qr_scans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no TEXT NOT NULL,
            scan_time  TEXT NOT NULL,
            method     TEXT DEFAULT 'qr'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS violations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no  TEXT,
            description TEXT,
            date        TEXT DEFAULT (datetime('now', '+8 hours')),
            recorded_by TEXT,
            status      TEXT DEFAULT 'pending'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS currently_inside (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no TEXT UNIQUE NOT NULL,
            entry_time TEXT NOT NULL,
            slot_type  TEXT
        )
    """)

    # VISITOR TABLES
    conn.execute("""
        CREATE TABLE IF NOT EXISTS visitors (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id  TEXT UNIQUE NOT NULL,
            name        TEXT DEFAULT 'Visitor',
            qr_code     TEXT,
            is_active   INTEGER DEFAULT 1,
            created_at  TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS visitor_scans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id  TEXT NOT NULL,
            scan_time   TEXT NOT NULL,
            scan_type   TEXT DEFAULT 'entry'
        )
    """)

    # Add missing columns safely
    for col in ["rssi", "antenna", "scan_type"]:
        try:
            conn.execute(f"ALTER TABLE rfid_scans ADD COLUMN {col} TEXT")
        except: pass

    # Create default admin
    admin_hash = hashlib.sha256("admin123".encode()).hexdigest()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO users (student_no, password_hash, full_name, position, is_admin)
            VALUES ('admin', ?, 'System Administrator', 'Admin', 1)
        """, (admin_hash,))
    except: pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS parking_slots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_type  TEXT UNIQUE NOT NULL,
            capacity   INTEGER NOT NULL,
            occupied   INTEGER DEFAULT 0
        )
    """)

    slots = [
        ('faculty_car',   31),
        ('faculty_moto',  15),
        ('student_car',   14),
        ('student_moto',  15),
    ]
    for slot_type, capacity in slots:
        conn.execute("""
            INSERT OR IGNORE INTO parking_slots (slot_type, capacity, occupied)
            VALUES (?, ?, 0)
        """, (slot_type, capacity))

    # Create 5 fixed visitor QR codes with actual QR images
    for i in range(1, 6):
        visitor_id = f"VISITOR{i}"
        existing = conn.execute("SELECT * FROM visitors WHERE visitor_id=?", (visitor_id,)).fetchone()
        if not existing:
            # Generate QR code image
            qr_img = qrcode.make(visitor_id)
            buf = io.BytesIO()
            qr_img.save(buf, format="PNG")
            qr_base64 = base64.b64encode(buf.getvalue()).decode()
            conn.execute("""
                INSERT INTO visitors (visitor_id, name, qr_code, created_at, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (visitor_id, f"Visitor {i}", qr_base64, ph_now()))

    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


# ============================================================
#  LANDING HTML (UPDATED with bg.jpg and logo.png)
# ============================================================
LANDING_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MMSU CCIS Parking System</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Inter',sans-serif;height:100vh;overflow:hidden;position:relative}
  .bg{position:absolute;inset:0;background:url('/static/bg.jpg') center/cover no-repeat fixed}
  .overlay{position:absolute;inset:0;background:rgba(0,0,0,0.5)}
  .container{position:relative;z-index:2;height:100vh;display:flex;align-items:center;justify-content:center}
  .card{background:rgba(255,255,255,0.95);backdrop-filter:blur(10px);border-radius:28px;padding:44px 40px;width:420px;text-align:center;box-shadow:0 32px 80px rgba(0,0,0,0.5),0 0 0 1px rgba(244,162,97,0.2);border:1px solid rgba(0,180,216,0.2)}
  .card h2{color:#0a1628;margin-bottom:6px;font-size:20px;font-weight:700;letter-spacing:-0.01em}
  .card h2 span{color:#00b4d8}
  .subtitle{color:#5a6a7a;font-size:12px;margin-bottom:32px;letter-spacing:2px;text-transform:uppercase;font-weight:500}
  .btn{display:block;width:100%;margin:10px 0;padding:15px;background:linear-gradient(135deg,#0a1628 0%,#1b2a4a 100%);color:white;text-decoration:none;border-radius:14px;font-weight:600;font-size:15px;transition:all 0.3s;border:1px solid rgba(0,180,216,0.3);box-shadow:0 4px 15px rgba(10,22,40,0.3)}
  .btn:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,180,216,0.4);border-color:#00b4d8}
  .btn-outline{background:transparent;color:#0a1628;border:2px solid #f4a261;box-shadow:none}
  .btn-outline:hover{background:rgba(244,162,97,0.1);border-color:#f4a261;box-shadow:0 4px 15px rgba(244,162,97,0.3);color:#0a1628}
  .hint{color:#7a8a9a;font-size:11px;margin-top:-3px;margin-bottom:8px}
  .logo-wrapper{margin-bottom:24px;width:100px;height:100px;margin-left:auto;margin-right:auto;border-radius:50%;overflow:hidden}
  .logo-wrapper img{width:100%;height:100%;display:block;object-fit:cover;object-position:center}
</style>
</head>
<body>
  <div class="bg"></div>
  <div class="overlay"></div>
  <div class="container">
    <div class="card">
      <div class="logo-wrapper">
        <img src="/static/logo.jpg" alt="MMSU Logo">
      </div>
      <h2>Mariano Marcos State University</h2>
      <div class="subtitle"><span style="color:#00b4d8">CCIS</span> PARKING & MONITORING</div>
      <a href="/login" class="btn">Sign In</a>
      <div class="hint">Already have an account?</div>
      <a href="/register" class="btn btn-outline">Register</a>
      <div class="hint">Create a new account</div>
    </div>
  </div>
</body>
</html>'''


# ============================================================
#  LOGIN HTML
# ============================================================
LOGIN_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign In - MMSU CCIS Parking</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Inter',sans-serif;height:100vh;overflow:hidden;position:relative}
  .bg{position:absolute;inset:0;background:url('/static/bg.jpg') center/cover no-repeat fixed}
  .overlay{position:absolute;inset:0;background:rgba(0,0,0,0.5)}
  .container{position:relative;z-index:2;height:100vh;display:flex;align-items:center;justify-content:center}
  .card{background:rgba(255,255,255,0.96);backdrop-filter:blur(10px);border-radius:24px;padding:40px;width:420px;box-shadow:0 32px 80px rgba(0,0,0,0.5),0 0 0 1px rgba(244,162,97,0.15);border:1px solid rgba(0,180,216,0.15)}
  h2{color:#0a1628;margin-bottom:6px;font-size:22px;font-weight:700;text-align:center;letter-spacing:-0.01em}
  h2 span{color:#00b4d8}
  .sub{text-align:center;color:#6a7a8a;font-size:13px;margin-bottom:28px}
  .field{margin-bottom:18px}
  label{display:block;font-size:13px;font-weight:600;color:#1b2a4a;margin-bottom:6px;letter-spacing:0.02em}
  input{width:100%;padding:14px 16px;border:2px solid #e0e8f0;border-radius:12px;font-size:14px;font-family:'Inter',sans-serif;transition:all 0.2s;outline:none;background:#fafcff}
  input:focus{border-color:#00b4d8;box-shadow:0 0 0 3px rgba(0,180,216,0.15)}
  .btn{width:100%;padding:15px;background:linear-gradient(135deg,#0a1628 0%,#1b2a4a 100%);color:white;border:none;border-radius:14px;font-size:15px;font-weight:600;cursor:pointer;transition:all 0.3s;margin-top:12px;box-shadow:0 4px 15px rgba(10,22,40,0.3);border:1px solid rgba(0,180,216,0.3)}
  .btn:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,180,216,0.4);border-color:#00b4d8}
  .error{background:rgba(220,38,38,0.08);border-left:4px solid #dc2626;color:#991b1b;padding:12px 16px;border-radius:10px;font-size:13px;margin-bottom:20px}
  .success{background:rgba(0,180,216,0.08);border-left:4px solid #00b4d8;color:#0a1628;padding:12px 16px;border-radius:10px;margin-bottom:18px;font-size:13px}
  .back{text-align:center;margin-top:20px;font-size:13px;color:#6a7a8a}
  .back a{color:#00b4d8;font-weight:600;text-decoration:none;transition:color 0.2s}
  .back a:hover{color:#f4a261}
  .logo-icon{margin-bottom:24px;width:100px;height:100px;margin-left:auto;margin-right:auto;border-radius:50%;overflow:hidden}
  .logo-icon img{width:100%;height:100%;display:block;object-fit:cover;object-position:center}
</style>
</head>
<body>
  <div class="bg"></div>
  <div class="overlay"></div>
  <div class="container">
    <div class="card">
      <div class="logo-icon">
        <img src="/static/logo.jpg" alt="MMSU Logo">
      </div>
      <h2>Welcome <span>Back</span></h2>
      <div class="sub">Sign in to your CCIS Parking account</div>
      {% if error %}<div class="error">{{ error }}</div>{% endif %}
      {% if success %}<div class="success">✓ {{ success }}</div>{% endif %}
      <form method="POST">
        <div class="field">
          <label>Student / Faculty Number</label>
          <input type="text" name="student_no" placeholder="e.g. 22-021049" required>
        </div>
        <div class="field">
          <label>Password</label>
          <input type="password" name="password" placeholder="Enter your password" required>
        </div>
        <button type="submit" class="btn">Sign In</button>
      </form>
      <div class="back">Don't have an account? <a href="/register">Register here</a></div>
      <div class="back" style="margin-top:10px"><a href="/">← Back to Home</a></div>
    </div>
  </div>
</body>
</html>'''


# ============================================================
#  REGISTER HTML
# ============================================================
REGISTER_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Register - MMSU CCIS Parking</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Inter',sans-serif;min-height:100vh;position:relative}
  .bg{position:fixed;inset:0;background:url('/static/bg.jpg') center/cover no-repeat fixed;z-index:0}
  .overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1}
  .container{position:relative;z-index:2;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px 16px}
  .card{background:rgba(255,255,255,0.97);backdrop-filter:blur(10px);border-radius:24px;padding:36px;width:100%;max-width:680px;box-shadow:0 32px 80px rgba(0,0,0,0.5),0 0 0 1px rgba(244,162,97,0.15);border:1px solid rgba(0,180,216,0.15)}
  h2{color:#0a1628;margin-bottom:6px;font-size:22px;font-weight:700;text-align:center}
  h2 span{color:#00b4d8}
  .sub{text-align:center;color:#6a7a8a;font-size:13px;margin-bottom:24px}
  .section-title{font-size:12px;font-weight:700;color:#00b4d8;text-transform:uppercase;letter-spacing:1px;margin-bottom:16px;padding-bottom:8px;border-bottom:2px solid rgba(244,162,97,0.3)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:8px}
  .field{margin-bottom:16px}
  .field.full{grid-column:1/-1}
  label{display:block;font-size:12px;font-weight:600;color:#1b2a4a;margin-bottom:5px}
  input,select{width:100%;padding:12px 14px;border:2px solid #e0e8f0;border-radius:10px;font-size:13px;font-family:'Inter',sans-serif;transition:all 0.2s;outline:none;background:#fafcff}
  input:focus,select:focus{border-color:#00b4d8;box-shadow:0 0 0 3px rgba(0,180,216,0.12)}
  .btn{width:100%;padding:15px;background:linear-gradient(135deg,#0a1628 0%,#1b2a4a 100%);color:white;border:none;border-radius:14px;font-size:15px;font-weight:600;cursor:pointer;transition:all 0.3s;margin-top:12px;box-shadow:0 4px 15px rgba(10,22,40,0.3);border:1px solid rgba(0,180,216,0.3)}
  .btn:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,180,216,0.4);border-color:#00b4d8}
  .error{background:rgba(220,38,38,0.08);border-left:4px solid #dc2626;color:#991b1b;padding:12px 16px;border-radius:10px;font-size:13px;margin-bottom:20px}
  .back{text-align:center;margin-top:18px;font-size:13px;color:#6a7a8a}
  .back a{color:#00b4d8;font-weight:600;text-decoration:none}
  .back a:hover{color:#f4a261}
  .divider{margin:20px 0 16px}
  .logo-icon{margin-bottom:24px;width:100px;height:100px;margin-left:auto;margin-right:auto;border-radius:50%;overflow:hidden}
  .logo-icon img{width:100%;height:100%;display:block;object-fit:cover;object-position:center}
</style>
</head>
<body>
  <div class="bg"></div>
  <div class="overlay"></div>
  <div class="container">
    <div class="card">
      <div class="logo-icon">
        <img src="/static/logo.jpg" alt="MMSU Logo">
      </div>
      <h2>Create <span>Account</span></h2>
      <div class="sub">Register for MMSU CCIS Parking & Monitoring</div>
      {% if error %}<div class="error">{{ error }}</div>{% endif %}
      <form method="POST">
        <div class="section-title">Personal Information</div>
        <div class="grid">
          <div class="field">
            <label>Student / Faculty Number *</label>
            <input type="text" name="student_no" placeholder="e.g. 22-021049" required>
          </div>
          <div class="field">
            <label>Position *</label>
            <select name="position" required>
              <option value="">Select position</option>
              <option value="Student">Student</option>
              <option value="Faculty">Faculty</option>
              <option value="Staff">Staff</option>
            </select>
          </div>
          <div class="field full">
            <label>Full Name *</label>
            <input type="text" name="full_name" placeholder="e.g. Juan Dela Cruz" required>
          </div>
          <div class="field">
            <label>College</label>
            <input type="text" name="college" placeholder="e.g. CCIS">
          </div>
          <div class="field">
            <label>Department</label>
            <input type="text" name="department" placeholder="e.g. Information Technology">
          </div>
          <div class="field full">
            <label>Email Address</label>
            <input type="email" name="email" placeholder="e.g. juan@mmsu.edu.ph">
          </div>
        </div>
        <div class="divider"></div>
        <div class="section-title">Vehicle Details</div>
        <div class="grid">
          <div class="field">
            <label>Vehicle Model</label>
            <input type="text" name="vehicle_model" placeholder="e.g. Honda Click">
          </div>
          <div class="field">
            <label>Vehicle Color</label>
            <input type="text" name="vehicle_color" placeholder="e.g. Red">
          </div>
          <div class="field full">
            <label>Vehicle Type *</label>
            <select name="vehicle_type" required>
              <option value="">Select vehicle type</option>
              <option value="Motorcycle">Motorcycle</option>
              <option value="Car">Car</option>
              <option value="SUV">SUV</option>
              <option value="Van">Van</option>
            </select>
          </div>
        </div>
        <div class="divider"></div>
        <div class="section-title">Account Security</div>
        <div class="grid">
          <div class="field">
            <label>Password *</label>
            <input type="password" name="password" placeholder="Create a password" required>
          </div>
          <div class="field">
            <label>Confirm Password *</label>
            <input type="password" name="confirm_password" placeholder="Repeat password" required>
          </div>
        </div>
        <button type="submit" class="btn">Create Account</button>
      </form>
      <div class="back">Already have an account? <a href="/login">Sign in here</a></div>
      <div class="back" style="margin-top:8px"><a href="/">← Back to Home</a></div>
    </div>
  </div>
</body>
</html>'''

# ============================================================
#  DASHBOARD HTML (UPDATED WITH VISITOR QR TAB)
# ============================================================
DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard - MMSU CCIS Parking</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Inter',sans-serif;background:#f0f4f8;min-height:100vh}
  nav{background:linear-gradient(135deg,#0a1628 0%,#1b2a4a 100%);padding:0 32px;display:flex;align-items:center;justify-content:space-between;height:70px;box-shadow:0 4px 20px rgba(0,0,0,0.2);border-bottom:2px solid #f4a261}
  .nav-left{display:flex;align-items:center;gap:16px}
  .nav-logo{width:50px;height:50px;border-radius:50%;display:flex;align-items:center;justify-content:center;overflow:hidden;background:transparent}
  .nav-logo img{width:100%;height:100%;object-fit:cover}
  .nav-title{color:white;font-weight:600;font-size:1rem;line-height:1.3}
  .nav-title span{display:block;font-size:0.7rem;font-weight:400;opacity:0.8;color:#00b4d8}
  .nav-right{display:flex;align-items:center;gap:20px}
  .nav-user{color:white;font-size:1rem;opacity:0.95}
  .nav-clock{color:#f4a261;font-size:0.85rem;font-weight:600;background:rgba(255,255,255,0.08);padding:6px 14px;border-radius:30px;letter-spacing:0.03em;border:1px solid rgba(244,162,97,0.3)}
  .nav-logout{color:white;text-decoration:none;font-size:0.8rem;background:rgba(0,180,216,0.15);padding:7px 16px;border-radius:30px;transition:all 0.2s;border:1px solid rgba(0,180,216,0.3);font-weight:500}
  .nav-logout:hover{background:rgba(0,180,216,0.3);border-color:#00b4d8}
  .layout{display:flex;min-height:calc(100vh - 70px)}
  .sidebar{width:260px;background:linear-gradient(180deg,#0a1628 0%,#1b2a4a 100%);padding:28px 0;flex-shrink:0;border-right:1px solid rgba(244,162,97,0.15)}
  .sidebar-item{display:flex;align-items:center;gap:12px;padding:13px 24px;color:rgba(255,255,255,0.7);font-size:0.88rem;cursor:pointer;transition:all 0.2s;text-decoration:none;font-weight:500}
  .sidebar-item:hover{background:rgba(0,180,216,0.1);color:white;border-left:3px solid #00b4d8}
  .sidebar-item.active{background:rgba(0,180,216,0.15);color:white;border-left:4px solid #f4a261}
  .sidebar-icon{font-size:1.1rem;width:24px;text-align:center}
  .sidebar-divider{height:1px;background:rgba(244,162,97,0.15);margin:16px 16px}
  .main{flex:1;padding:28px 32px;overflow-y:auto}
  .page{display:none}
  .page.active{display:block}
  .greeting{margin-bottom:28px}
  .greeting h1{font-size:2.2rem;color:#0a1628;font-weight:700;letter-spacing:-0.02em}
  .greeting p{color:#5a6a7a;font-size:1.1rem;margin-top:6px}
  .stat-card{background:white;border-radius:18px;padding:22px;box-shadow:0 4px 15px rgba(0,0,0,0.05);border:1px solid rgba(0,180,216,0.1);transition:transform 0.2s}
  .stat-card:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,180,216,0.1)}
  .stat-card .icon{font-size:1.8rem;margin-bottom:10px}
  .stat-card .val{font-size:2rem;font-weight:700;color:#0a1628}
  .stat-card .lbl{font-size:0.75rem;color:#6a7a8a;margin-top:4px;text-transform:uppercase;letter-spacing:0.05em}
  .profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-bottom:28px}
  .info-card{background:white;border-radius:18px;padding:24px;box-shadow:0 4px 15px rgba(0,0,0,0.05);border:1px solid rgba(0,180,216,0.1)}
  .info-card h3{font-size:0.8rem;font-weight:700;color:#00b4d8;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:18px;padding-bottom:10px;border-bottom:2px solid rgba(244,162,97,0.3)}
  .info-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #eef2f6;font-size:0.88rem}
  .info-row:last-child{border-bottom:none}
  .info-label{color:#5a6a7a;font-weight:500}
  .info-value{font-weight:600;color:#0a1628;text-align:right}
  .badge{display:inline-block;padding:4px 14px;border-radius:30px;font-size:0.7rem;font-weight:600}
  .badge-student{background:rgba(0,180,216,0.12);color:#0088a0}
  .badge-faculty{background:rgba(244,162,97,0.15);color:#d4882a}
  .badge-staff{background:rgba(244,162,97,0.1);color:#c47a1a}
  .table-card{background:white;border-radius:18px;padding:22px;box-shadow:0 4px 15px rgba(0,0,0,0.05);border:1px solid rgba(0,180,216,0.1)}
  .table-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
  .table-header h3{font-size:0.95rem;font-weight:700;color:#0a1628}
  table{width:100%;border-collapse:collapse;font-size:0.85rem}
  th{text-align:left;padding:12px 12px;background:#f0f4f8;color:#1b2a4a;font-weight:600;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.06em;border-bottom:2px solid rgba(0,180,216,0.2)}
  td{padding:12px 12px;border-bottom:1px solid #eef2f6;color:#2a3a4a}
  tr:hover td{background:rgba(0,180,216,0.03)}
  .tag-in{color:#00b4d8;font-weight:600;font-size:0.75rem;background:rgba(0,180,216,0.1);padding:4px 12px;border-radius:30px}
  .tag-out{color:#f4a261;font-weight:600;font-size:0.75rem;background:rgba(244,162,97,0.1);padding:4px 12px;border-radius:30px}
  .empty{text-align:center;padding:40px;color:#8a9aaa;font-size:0.9rem}
  .qr-card{background:white;border-radius:24px;padding:36px;box-shadow:0 8px 30px rgba(0,0,0,0.08);text-align:center;max-width:450px;margin:0 auto;border:1px solid rgba(0,180,216,0.15)}
  .qr-card h3{color:#0a1628;margin-bottom:8px;font-weight:700}
  .qr-card p{color:#6a7a8a;font-size:0.85rem;margin-bottom:24px}
  .qr-img{width:220px;height:220px;border:3px solid #f4a261;border-radius:16px;padding:10px;margin:0 auto 20px;background:white}
  .qr-btn{background:linear-gradient(135deg,#0a1628 0%,#1b2a4a 100%);color:white;border:none;padding:14px 32px;border-radius:12px;font-size:0.9rem;font-weight:600;cursor:pointer;transition:all 0.3s;border:1px solid rgba(0,180,216,0.3)}
  .qr-btn:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,180,216,0.3);border-color:#00b4d8}
  .qr-details{background:rgba(0,180,216,0.04);border-radius:14px;padding:18px;text-align:left;margin-top:18px;font-size:0.85rem;border:1px solid rgba(0,180,216,0.1)}
  .qr-details .qr-row{display:flex;justify-content:space-between;padding:5px 0;color:#2a3a4a}
  .qr-details .qr-row span:first-child{color:#5a6a7a;font-weight:500}
  .viol-alert{background:rgba(244,162,97,0.05);border:1px solid rgba(244,162,97,0.2);border-left:4px solid #f4a261;border-radius:14px;padding:18px 20px;margin-bottom:14px}
  .viol-alert-title{display:flex;align-items:center;gap:8px;font-weight:700;color:#d4882a;font-size:0.9rem;margin-bottom:6px}
  .viol-alert-desc{color:#2a3a4a;font-size:0.87rem;margin-bottom:8px}
  .viol-alert-meta{display:flex;gap:14px;font-size:0.75rem;color:#8a9aaa}
  .viol-alert-status{display:inline-block;padding:3px 12px;border-radius:30px;font-size:0.7rem;font-weight:700}
  .viol-status-pending{background:rgba(244,162,97,0.15);color:#d4882a}
  .top-alert-bar{background:rgba(244,162,97,0.08);border-bottom:2px solid #f4a261;padding:12px 32px;display:flex;align-items:center;gap:12px;font-size:0.88rem;color:#d4882a;font-weight:600;display:none}
  .top-alert-bar.show{display:flex}
  .viol-badge{background:rgba(244,162,97,0.12);color:#d4882a;padding:4px 12px;border-radius:30px;font-size:0.7rem;font-weight:600}
  .notice-card{background:white;border-radius:16px;padding:20px;box-shadow:0 2px 10px rgba(0,0,0,0.04);margin-bottom:14px;border-left:4px solid #00b4d8;border:1px solid rgba(0,180,216,0.1);border-left-width:4px}
  .notice-title{font-weight:700;color:#0a1628;margin-bottom:6px}
  .notice-msg{color:#4a5a6a;font-size:0.88rem}
  .notice-date{color:#8a9aaa;font-size:0.75rem;margin-top:8px}
  #log-search{padding:8px 14px;border:2px solid #e0e8f0;border-radius:10px;font-size:0.85rem;outline:none;width:200px;background:#fafcff}
  #log-search:focus{border-color:#00b4d8}
  </style>
</head>
<body>
<nav>
  <div class="nav-left">
    <div class="nav-logo">
      <img src="/static/logo.jpg" alt="MMSU">
    </div>
    <div class="nav-title">
      MMSU CCIS Parking
      <span>Monitoring System</span>
    </div>
  </div>
  <div class="nav-right">
    <span class="nav-user">Hi, {{ user.full_name.split()[0] if user.full_name else user.student_no }}</span>
    <span class="nav-clock" id="ph-clock">--:--:--</span>
    <a href="/logout" class="nav-logout">Sign Out</a>
  </div>
</nav>

<div class="top-alert-bar" id="top-alert-bar">
  ⚠️ You have <span id="top-alert-count">0</span> pending violation(s). <a href="#" onclick="showPage('violations',event)" style="color:#d4882a;font-weight:700;margin-left:8px;text-decoration:underline">View Details →</a>
</div>

<div class="layout">
  <div class="sidebar">
    <a class="sidebar-item active" data-page="dashboard" onclick="showPage('dashboard',event)" href="#">
      <span class="sidebar-icon">📊</span> Dashboard
    </a>
    <a class="sidebar-item" data-page="logs" onclick="showPage('logs',event)" href="#">
      <span class="sidebar-icon">📋</span> My Logs
    </a>
    <a class="sidebar-item" data-page="violations" onclick="showPage('violations',event)" href="#">
      <span class="sidebar-icon">⚠️</span> Violations
    </a>
    <a class="sidebar-item" data-page="qrcode" onclick="showPage('qrcode',event)" href="#">
      <span class="sidebar-icon">🔲</span> My QR Code
    </a>
    <div class="sidebar-divider"></div>
    <a class="sidebar-item" data-page="notices" onclick="showPage('notices',event)" href="#">
      <span class="sidebar-icon">📢</span> Notices
    </a>
  </div>

  <div class="main">
    <!-- DASHBOARD PAGE -->
    <div class="page active" id="page-dashboard">
      <div class="greeting">
        <h1>Welcome, {{ user.full_name.split()[0] if user.full_name else 'User' }}!</h1>
        <p>Here's your parking activity summary</p>
      </div>

      <div style="margin-bottom:28px">
        <div style="font-size:0.75rem;font-weight:700;color:#00b4d8;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:16px">
          Available Parking Slots
        </div>
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:18px" id="parking-slots-grid"></div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:28px">
        <div class="stat-card">
          <div class="icon">📅</div>
          <div class="val" id="stat-total">—</div>
          <div class="lbl">Total Entries</div>
        </div>
        <div class="stat-card">
          <div class="icon">🕒</div>
          <div class="val" id="stat-today">—</div>
          <div class="lbl">Today's Visits (PHT)</div>
        </div>
        <div class="stat-card">
          <div class="icon">⚠️</div>
          <div class="val" id="stat-violations">—</div>
          <div class="lbl">Violations</div>
        </div>
      </div>

      <div class="profile-grid">
        <div class="info-card">
          <h3>Personal Information</h3>
          <div class="info-row"><span class="info-label">ID Number</span><span class="info-value">{{ user.student_no }}</span></div>
          <div class="info-row"><span class="info-label">Full Name</span><span class="info-value">{{ user.full_name or '—' }}</span></div>
          <div class="info-row"><span class="info-label">College</span><span class="info-value">{{ user.college or '—' }}</span></div>
          <div class="info-row"><span class="info-label">Department</span><span class="info-value">{{ user.department or '—' }}</span></div>
          <div class="info-row"><span class="info-label">Email</span><span class="info-value">{{ user.email or '—' }}</span></div>
          <div class="info-row"><span class="info-label">Position</span><span class="info-value">
            <span class="badge badge-{{ user.position.lower() if user.position else 'student' }}">{{ user.position or 'Student' }}</span>
          </span></div>
        </div>
        <div class="info-card">
          <h3>Vehicle Details</h3>
          <div class="info-row"><span class="info-label">Model</span><span class="info-value">{{ user.vehicle_model or '—' }}</span></div>
          <div class="info-row"><span class="info-label">Color</span><span class="info-value">{{ user.vehicle_color or '—' }}</span></div>
          <div class="info-row"><span class="info-label">Type</span><span class="info-value">{{ user.vehicle_type or '—' }}</span></div>
          <div class="info-row"><span class="info-label">RFID Tag</span><span class="info-value">
            {% if user.tag_id %}<span style="font-family:monospace;font-size:0.8rem;color:#00b4d8">{{ user.tag_id[:16] }}...</span>
            {% else %}<span style="color:#f4a261">Not assigned yet</span>{% endif %}
          </span></div>
        </div>
      </div>

      <div id="dashboard-violations"></div>

      <div class="table-card">
        <div class="table-header">
          <h3>Recent Activity</h3>
          <a href="#" onclick="showPage('logs')" style="font-size:0.82rem;color:#00b4d8;text-decoration:none;font-weight:600">View all →</a>
        </div>
        <table>
          <thead>
            <tr>
              <th>Date (PHT)</th>
              <th>Entry Time</th>
              <th>Exit Time</th>
            </tr>
          </thead>
          <tbody id="recent-logs"></tbody>
        </table>
      </div>
    </div>

    <!-- LOGS PAGE -->
    <div class="page" id="page-logs">
      <div class="greeting">
        <h1>My Access Logs</h1>
        <p>Your complete vehicle entry and exit history <span style="font-size:0.78rem;color:#8a9aaa">(All times in PHT)</span></p>
      </div>
      <div class="table-card">
        <div class="table-header">
          <h3>Access Records</h3>
          <input type="text" id="log-search" placeholder="Search..." oninput="filterLogs()">
        </div>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Date (PHT)</th>
              <th>Entry Time</th>
              <th>Exit Time</th>
            </tr>
          </thead>
          <tbody id="logs-table"></tbody>
        </table>
      </div>
    </div>

    <!-- VIOLATIONS PAGE -->
    <div class="page" id="page-violations">
      <div class="greeting">
        <h1>My Violations</h1>
        <p>Violations recorded against your account</p>
      </div>
      <div class="table-card">
        <table>
          <thead>
            <tr>
              <th>Date (PHT)</th>
              <th>Description</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="violations-table"></tbody>
        </table>
      </div>
    </div>

    <!-- QR CODE PAGE -->
    <div class="page" id="page-qrcode">
      <div class="greeting">
        <h1>My QR Code</h1>
        <p>Use this QR code for parking access</p>
      </div>
      <div class="qr-card">
        <h3>Access QR Code</h3>
        <p>Present this QR code at the gate for vehicle entry/exit</p>
        <img id="qr-image" class="qr-img" src="" alt="QR Code">
        <br>
        <button class="qr-btn" onclick="downloadQR()">📥 Download QR Code</button>
        <div class="qr-details">
          <div class="qr-row"><span>Name</span><span>{{ user.full_name or '—' }}</span></div>
          <div class="qr-row"><span>ID Number</span><span>{{ user.student_no }}</span></div>
          <div class="qr-row"><span>Position</span><span>{{ user.position or '—' }}</span></div>
          <div class="qr-row"><span>College</span><span>{{ user.college or '—' }}</span></div>
          <div class="qr-row"><span>Vehicle Type</span><span>{{ user.vehicle_type or '—' }}</span></div>
        </div>
      </div>
    </div>

    <!-- NOTICES PAGE -->
    <div class="page" id="page-notices">
      <div class="greeting">
        <h1>Notices & Alerts</h1>
        <p>Violations and important announcements</p>
      </div>
      <div id="notices-list"></div>
    </div>


<script>
  let allLogs = [];

  function to12hr(timeStr) {
    if (!timeStr || timeStr === '—') return '—';
    const parts = timeStr.split(':');
    if (parts.length < 2) return timeStr;
    const h = parseInt(parts[0]);
    const m = parts[1];
    const s = parts.length > 2 ? parts[2].split(' ')[0] : '00';
    const ampm = h >= 12 ? 'PM' : 'AM';
    const hr12 = h % 12 || 12;
    return `${hr12}:${m}:${s} ${ampm}`;
  }

  function updateClock() {
    const now = new Date();
    const ph = new Date(now.toLocaleString('en-US', {timeZone: 'Asia/Manila'}));
    const pad = n => String(n).padStart(2,'0');
    const h = ph.getHours();
    const ampm = h >= 12 ? 'PM' : 'AM';
    const hr12 = h % 12 || 12;
    document.getElementById('ph-clock').textContent = `${hr12}:${pad(ph.getMinutes())}:${pad(ph.getSeconds())} ${ampm} PHT`;
  }
  updateClock();
  setInterval(updateClock, 1000);

  function showPage(name, e) {
    if (e) e.preventDefault();
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.sidebar-item').forEach(s => s.classList.remove('active'));
    document.getElementById('page-' + name).classList.add('active');
    const sidebarItem = document.querySelector(`.sidebar-item[data-page="${name}"]`);
    if (sidebarItem) sidebarItem.classList.add('active');
    if (name === 'logs') fetchLogs();
    if (name === 'qrcode') loadQR();
    if (name === 'violations') fetchViolations();
    if (name === 'notices') fetchNotices();
  }

  async function fetchStats() {
    const res = await fetch('/api/user/stats');
    const data = await res.json();
    document.getElementById('stat-total').textContent = data.total || 0;
    document.getElementById('stat-today').textContent = data.today || 0;
    document.getElementById('stat-violations').textContent = data.violations || 0;
  }

  async function fetchRecentLogs() {
    const res = await fetch('/api/user/logs-paired?limit=5');
    const data = await res.json();
    const tbody = document.getElementById('recent-logs');
    if (!data.logs || !data.logs.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty">No activity yet<\/td><\/tr>';
      return;
    }
    tbody.innerHTML = data.logs.map(r => {
      return `<tr>
        <td>${r.date}<\/td>
        <td>${r.entry_time ? to12hr(r.entry_time) : '—'}<\/td>
        <td>${r.exit_time ? to12hr(r.exit_time) : '—'}<\/td>
      <\/tr>`;
    }).join('');
  }

  async function fetchLogs() {
    const res = await fetch('/api/user/logs-paired?limit=200');
    const data = await res.json();
    allLogs = data.logs || [];
    renderLogs(allLogs);
  }

  function renderLogs(logs) {
    const tbody = document.getElementById('logs-table');
    if (!logs.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">No logs found<\/td><\/tr>';
      return;
    }
    tbody.innerHTML = logs.map((r,i) => {
      return `<tr>
        <td>${i+1}<\/td>
        <td>${r.date}<\/td>
        <td>${r.entry_time ? to12hr(r.entry_time) : '—'}<\/td>
        <td>${r.exit_time ? to12hr(r.exit_time) : '—'}<\/td>
      <\/tr>`;
    }).join('');
  }

  function filterLogs() {
    const q = document.getElementById('log-search').value.toLowerCase();
    renderLogs(allLogs.filter(r => (r.date||'').toLowerCase().includes(q) || 
                                    (r.entry_time||'').toLowerCase().includes(q) ||
                                    (r.exit_time||'').toLowerCase().includes(q)));
  }

  async function fetchViolations() {
    const res = await fetch('/api/user/violations');
    const data = await res.json();
    const tbody = document.getElementById('violations-table');
    if (!data.violations || !data.violations.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty">No violations recorded ✅<\/td><\/tr>';
    } else {
      tbody.innerHTML = data.violations.map(v => `
        <tr>
          <td>${v.date||'—'}<\/td>
          <td>${v.description||'—'}<\/td>
          <td><span class="viol-badge viol-${(v.status||'pending').toLowerCase()}">${v.status||'Pending'}<\/span><\/td>
        <\/tr>
      `).join('');
    }

    const pending = (data.violations || []).filter(v => (v.status||'').toLowerCase() === 'pending');
    const bar = document.getElementById('top-alert-bar');
    const cnt = document.getElementById('top-alert-count');
    if (pending.length > 0) {
      bar.classList.add('show');
      cnt.textContent = pending.length;
    } else {
      bar.classList.remove('show');
    }

    const dvDiv = document.getElementById('dashboard-violations');
    if (dvDiv) {
      if (pending.length > 0) {
        dvDiv.innerHTML = `
          <div style="margin-bottom:22px">
            <div style="font-size:0.75rem;font-weight:700;color:#f4a261;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:14px">
              ⚠️ Pending Violations (${pending.length})
            </div>
            ${pending.map(v => `
              <div class="viol-alert">
                <div class="viol-alert-title">⚠️ Parking Violation</div>
                <div class="viol-alert-desc">${v.description||'—'}</div>
                <div class="viol-alert-meta">
                  <span>📅 ${v.date||'—'}</span>
                  <span class="viol-alert-status viol-status-pending">Pending</span>
                </div>
              </div>`).join('')}
          </div>`;
      } else {
        dvDiv.innerHTML = '';
      }
    }
  }

  async function loadQR() {
    const res = await fetch('/api/user/qr');
    const data = await res.json();
    document.getElementById('qr-image').src = 'data:image/png;base64,' + data.qr;
  }

  function downloadQR() {
    const img = document.getElementById('qr-image');
    const a = document.createElement('a');
    a.href = img.src;
    a.download = 'my_qrcode.png';
    a.click();
  }

  async function fetchNotices() {
    fetchViolations();
    const div = document.getElementById('notices-list');
    const [violRes, noticeRes] = await Promise.all([
      fetch('/api/user/violations'),
      fetch('/api/user/notices')
    ]);
    const violData = await violRes.json();
    const noticeData = await noticeRes.json();

    let html = '';
    const violations = violData.violations || [];

    if (violations.length > 0) {
      html += `<div style="font-size:0.75rem;font-weight:700;color:#f4a261;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:14px">⚠️ Your Violations</div>`;
      html += violations.map(v => {
        const resolved = (v.status||'').toLowerCase() === 'resolved';
        return `
        <div class="notice-card" style="border-left-color:${resolved ? '#00b4d8' : '#f4a261'};background:${resolved ? 'rgba(0,180,216,0.03)' : 'rgba(244,162,97,0.03)'}">
          <div class="notice-title" style="color:${resolved ? '#0088a0' : '#d4882a'}">${resolved ? '✅' : '⚠️'} Parking Violation</div>
          <div class="notice-msg">${v.description||'—'}</div>
          <div class="notice-date">📅 ${v.date||'—'} <span style="background:${resolved ? 'rgba(0,180,216,0.12)' : 'rgba(244,162,97,0.12)'};color:${resolved ? '#0088a0' : '#d4882a'};padding:3px 12px;border-radius:30px;margin-left:10px">${v.status||'Pending'}</span></div>
        </div>`;
      }).join('');
    }

    const notices = noticeData.notices || [];
    if (notices.length > 0) {
      if (violations.length > 0) {
        html += `<div style="font-size:0.75rem;font-weight:700;color:#00b4d8;text-transform:uppercase;letter-spacing:0.1em;margin:24px 0 14px">📢 From Administration</div>`;
      }
      html += notices.map(n => `
        <div class="notice-card">
          <div class="notice-title">📢 ${n.title}</div>
          <div class="notice-msg">${n.message}</div>
          <div class="notice-date">📅 ${n.created_at} (PHT)</div>
        </div>`).join('');
    }

    if (!html) {
      html = '<div class="empty" style="background:white;border-radius:18px;padding:40px;text-align:center;color:#8a9aaa">No notices or violations yet ✅</div>';
    }
    div.innerHTML = html;
  }


  const userPosition = "{{ user.position or 'Student' }}".toLowerCase();
  const isFaculty = ['faculty','staff'].includes(userPosition);
  const slotConfig = isFaculty
    ? [{type:'faculty_car', label:'Faculty Cars', icon:'🚗', total:31, color:'#00b4d8'},
       {type:'faculty_moto', label:'Faculty Motorcycles', icon:'🏍️', total:15, color:'#00b4d8'}]
    : [{type:'student_car', label:'Student Cars', icon:'🚗', total:14, color:'#f4a261'},
       {type:'student_moto', label:'Student Motorcycles', icon:'🏍️', total:15, color:'#f4a261'}];

  function buildParkingCards() {
    const grid = document.getElementById('parking-slots-grid');
    grid.innerHTML = slotConfig.map(s => `
      <div class="stat-card" id="slot-${s.type}" style="border-top:4px solid ${s.color};text-align:center">
        <div style="font-size:2rem;margin-bottom:8px">${s.icon}</div>
        <div style="font-size:0.75rem;font-weight:600;color:#5a6a7a;text-transform:uppercase;margin-bottom:12px">${s.label}</div>
        <div style="display:flex;align-items:baseline;justify-content:center;gap:4px">
          <span id="slot-${s.type}-avail" style="font-size:2.2rem;font-weight:700;color:${s.color}">—</span>
          <span style="color:#8a9aaa;font-size:1rem">/ ${s.total}</span>
        </div>
        <div style="font-size:0.7rem;color:#8a9aaa;margin-top:6px">Available Slots</div>
        <div style="background:#e0e8f0;border-radius:30px;height:7px;margin-top:14px;overflow:hidden">
          <div id="slot-${s.type}-bar" style="height:100%;border-radius:30px;background:${s.color};width:100%;transition:width 0.5s"></div>
        </div>
        <div id="slot-${s.type}-status" style="margin-top:10px;font-size:0.75rem;font-weight:600"></div>
      </div>
    `).join('');
  }

  async function fetchParkingSlots() {
    const res = await fetch('/api/parking/slots');
    const data = await res.json();
    slotConfig.forEach(s => {
      const slot = data[s.type];
      if (!slot) return;
      const availEl = document.getElementById('slot-' + s.type + '-avail');
      const barEl = document.getElementById('slot-' + s.type + '-bar');
      const cardEl = document.getElementById('slot-' + s.type);
      const statusEl = document.getElementById('slot-' + s.type + '-status');
      if (!availEl) return;
      const color = slot.status === 'ok' ? s.color : slot.status === 'warning' ? '#f4a261' : '#dc2626';
      availEl.textContent = slot.available;
      availEl.style.color = color;
      barEl.style.width = (slot.available / slot.capacity * 100) + '%';
      barEl.style.background = color;
      cardEl.style.borderTopColor = color;
      cardEl.style.background = slot.status === 'full' ? 'rgba(244,162,97,0.03)' : '';
      if (statusEl) {
        statusEl.textContent = slot.status === 'full' ? '🚫 PARKING FULL' : slot.status === 'warning' ? '⚠️ ALMOST FULL' : '✅ Available';
        statusEl.style.color = slot.status === 'full' ? '#dc2626' : slot.status === 'warning' ? '#f4a261' : '#5a6a7a';
      }
    });
  }

  buildParkingCards();
  fetchStats();
  fetchRecentLogs();
  fetchParkingSlots();
  fetchViolations();
  setInterval(fetchStats, 30000);
  setInterval(fetchParkingSlots, 5000);
  setInterval(fetchViolations, 30000);
</script>
</body>
</html>'''

# ============================================================
#  QR SCANNER HTML (UPDATED TO SUPPORT VISITORS)
# ============================================================
# ============================================================
#  QR SCANNER HTML (UPDATED WITH ALARM SOUND)
# ============================================================
# ============================================================
#  QR SCANNER HTML (UPDATED WITH 30-SECOND LOUD ALARM)
# ============================================================
QR_SCANNER_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MMSU CCIS Parking — Gate Kiosk</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js"></script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%;overflow:hidden}
  body{font-family:'Inter',sans-serif;background:#0a1628;color:white;display:flex;flex-direction:column}
  .topbar{background:linear-gradient(135deg,#0a1628 0%,#1b2a4a 100%);padding:0 28px;display:flex;align-items:center;justify-content:space-between;height:65px;flex-shrink:0;box-shadow:0 4px 20px rgba(0,0,0,0.3);border-bottom:2px solid #f4a261}
  .topbar-left{display:flex;align-items:center;gap:14px}
  .topbar-logo{width:42px;height:42px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;overflow:hidden;border:2px solid #f4a261}
  .topbar-logo img{width:100%;height:100%;object-fit:cover}
  .topbar-title{font-size:1rem;color:white;line-height:1.3;font-weight:600}
  .topbar-title span{display:block;font-size:0.7rem;font-weight:400;opacity:0.8;color:#00b4d8}
  .topbar-right{display:flex;align-items:center;gap:16px}
  .topbar-clock{font-size:0.95rem;font-weight:600;color:#f4a261;background:rgba(255,255,255,0.06);padding:7px 16px;border-radius:30px;border:1px solid rgba(244,162,97,0.25)}
  .topbar-mmsu{width:40px;height:40px;border-radius:50%;overflow:hidden;border:2px solid #f4a261}
  .topbar-mmsu img{width:100%;height:100%;object-fit:cover}
  .kiosk{flex:1;display:grid;grid-template-columns:1fr 1fr;overflow:hidden}
  .cam-side{background:#0d1f2d;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;gap:16px;border-right:1px solid rgba(0,180,216,0.15)}
  .cam-label{font-size:0.75rem;font-weight:700;color:#00b4d8;text-transform:uppercase;letter-spacing:0.15em}
  .cam-wrap{position:relative;width:100%;max-width:460px;border-radius:20px;overflow:hidden;background:#000;border:3px solid #00b4d8;box-shadow:0 0 40px rgba(0,180,216,0.3)}
  video{width:100%;display:block;aspect-ratio:4/3;object-fit:cover}
  canvas{display:none}
  .cam-overlay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none}
  .cam-box{width:200px;height:200px;position:relative}
  .cam-box::before,.cam-box::after{content:'';position:absolute;width:35px;height:35px;border-color:#00b4d8;border-style:solid}
  .cam-box::before{top:0;left:0;border-width:4px 0 0 4px;border-radius:8px 0 0 0}
  .cam-box::after{top:0;right:0;border-width:4px 4px 0 0;border-radius:0 8px 0 0}
  .cam-box-bl,.cam-box-br{position:absolute;width:35px;height:35px;border-color:#00b4d8;border-style:solid}
  .cam-box-bl{bottom:0;left:0;border-width:0 0 4px 4px;border-radius:0 0 0 8px}
  .cam-box-br{bottom:0;right:0;border-width:0 4px 4px 0;border-radius:0 0 8px 0}
  .scan-beam{position:absolute;left:8px;right:8px;height:2px;background:linear-gradient(90deg,transparent,#f4a261,transparent);animation:beam 2s ease-in-out infinite}
  @keyframes beam{0%{top:8px}100%{top:calc(100% - 8px)}}
  .cam-instruction{font-size:0.9rem;color:#8a9aaa;text-align:center}
  .cam-instruction strong{display:block;color:#e0e8f0;font-size:1rem;margin-bottom:4px}
  .cam-status{display:flex;align-items:center;gap:10px;font-size:0.8rem;color:#8a9aaa}
  .dot{width:9px;height:9px;border-radius:50%;background:#00b4d8;flex-shrink:0}
  .dot.pulse{animation:dp 1.4s infinite}
  @keyframes dp{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.4;transform:scale(0.7)}}
  .dot.err{background:#ef4444;animation:none}
  .dot.scanning{background:#f4a261;animation:dp 0.8s infinite}
  .mode-buttons{display:flex;gap:12px;margin-top:8px}
  .mode-btn{padding:12px 24px;border:none;border-radius:12px;cursor:pointer;font-weight:600;font-size:0.9rem;transition:all 0.3s;flex:1}
  .mode-btn.entrance{background:#00b4d8;color:#0a1628}
  .mode-btn.entrance.active{background:#0096b0;box-shadow:0 0 20px rgba(0,180,216,0.5);transform:scale(1.02)}
  .mode-btn.entrance:hover{background:#00a0c0}
  .mode-btn.exit{background:#f4a261;color:#0a1628}
  .mode-btn.exit.active{background:#d4882a;box-shadow:0 0 20px rgba(244,162,97,0.5);transform:scale(1.02)}
  .mode-btn.exit:hover{background:#e09050}
  .result-side{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px;transition:background 0.5s;position:relative;overflow:hidden}
  .result-side.idle{background:#0a1628}
  .result-side.granted{background:rgba(0,180,216,0.08)}
  .result-side.denied{background:rgba(220,38,38,0.06)}
  .result-side.full{background:rgba(244,162,97,0.06)}
  .result-side.exit-ok{background:rgba(0,180,216,0.06)}
  .idle-state{text-align:center;animation:fadein 0.5s ease}
  @keyframes fadein{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
  .idle-icon{font-size:4rem;margin-bottom:18px;opacity:0.25}
  .idle-title{font-size:1.4rem;font-weight:600;color:#6a7a8a;margin-bottom:10px}
  .idle-sub{font-size:0.9rem;color:#4a5a6a}
  .scan-result{display:none;width:100%;max-width:420px;animation:slidein 0.4s ease}
  @keyframes slidein{from{opacity:0;transform:scale(0.95)}to{opacity:1;transform:scale(1)}}
  .welcome-msg{text-align:center;margin-bottom:22px}
  .welcome-emoji{font-size:3.5rem;margin-bottom:12px;display:block}
  .welcome-text{font-size:1.8rem;font-weight:700;line-height:1.2;margin-bottom:8px}
  .welcome-text.green{color:#00b4d8}
  .welcome-text.red{color:#ef4444}
  .welcome-text.orange{color:#f4a261}
  .welcome-text.blue{color:#00b4d8}
  .welcome-sub{font-size:0.9rem;color:#8a9aaa}
  .user-card{background:rgba(255,255,255,0.04);border:1px solid rgba(0,180,216,0.15);border-radius:18px;padding:18px;margin-bottom:14px;backdrop-filter:blur(10px)}
  .user-top{display:flex;align-items:center;gap:14px;margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid rgba(255,255,255,0.06)}
  .avatar{width:50px;height:50px;border-radius:50%;background:linear-gradient(135deg,#00b4d8 0%,#1b2a4a 100%);display:flex;align-items:center;justify-content:center;font-size:1.1rem;font-weight:700;flex-shrink:0;border:2px solid rgba(244,162,97,0.5)}
  .uname{font-size:1rem;font-weight:600;color:#f0f4f8}
  .uid{font-size:0.78rem;color:#8a9aaa;margin-top:3px}
  .detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .detail-item .dl{font-size:0.67rem;color:#6a7a8a;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:3px}
  .detail-item .dv{font-size:0.85rem;font-weight:600;color:#c8d8e8}
  .slot-bar{background:linear-gradient(135deg,rgba(0,180,216,0.12),rgba(244,162,97,0.08));border:2px solid rgba(0,180,216,0.4);border-radius:16px;padding:18px 22px;display:flex;justify-content:space-between;align-items:center;margin-top:4px;box-shadow:0 4px 16px rgba(0,180,216,0.15)}
  .slot-bar .sl{font-size:1rem;font-weight:700;color:#e0f0ff;text-transform:uppercase;letter-spacing:0.04em}
  .slot-bar .sv{font-size:1.6rem;font-weight:800;color:#00e5ff;text-shadow:0 0 12px rgba(0,229,255,0.5)}
  .slot-bar .sv.full{color:#f4a261;text-shadow:0 0 12px rgba(244,162,97,0.5)}
  .scan-ts{text-align:center;font-size:0.72rem;color:#6a7a8a;margin-top:12px}
  .countdown{position:absolute;bottom:16px;right:20px;font-size:0.72rem;color:#6a7a8a}
  .recent-ticker{position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.4);padding:10px 24px;display:flex;align-items:center;gap:12px;font-size:0.75rem;color:#8a9aaa;border-top:1px solid rgba(244,162,97,0.15)}
  .ticker-label{color:#00b4d8;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;flex-shrink:0}
  .ticker-item{color:#b8c8d8}
  .ticker-entry{color:#00b4d8}
  .ticker-exit{color:#f4a261}
  .debug-panel{position:absolute;top:80px;left:12px;background:rgba(10,22,40,0.9);color:#00b4d8;padding:8px 14px;border-radius:10px;font-size:0.7rem;font-family:monospace;z-index:100;pointer-events:none;border:1px solid rgba(0,180,216,0.3)}
  .mode-indicator{text-align:center;padding:10px;border-radius:12px;font-size:0.9rem;font-weight:600;width:100%}
  .mode-indicator.entrance{background:rgba(0,180,216,0.15);color:#00b4d8;border:1px solid rgba(0,180,216,0.3)}
  .mode-indicator.exit{background:rgba(244,162,97,0.12);color:#f4a261;border:1px solid rgba(244,162,97,0.3)}
  .cooldown-overlay{position:absolute;inset:0;background:rgba(10,22,40,0.85);display:flex;align-items:center;justify-content:center;z-index:50;display:none;backdrop-filter:blur(8px)}
  .cooldown-box{background:#1b2a4a;padding:35px 45px;border-radius:24px;text-align:center;border:2px solid #f4a261;box-shadow:0 20px 50px rgba(0,0,0,0.5)}
  .cooldown-box h3{color:#f4a261;font-size:1.6rem;margin-bottom:12px}
  .cooldown-box p{color:#b8c8d8;font-size:1rem;margin-bottom:18px}
  .cooldown-timer{font-size:3.5rem;font-weight:700;color:#f4a261}
  /* Alarm flashing effect */
  @keyframes alarmFlash {
    0% { background: rgba(220,38,38,0); border-color: #ef4444; }
    25% { background: rgba(220,38,38,0.4); border-color: #ef4444; }
    50% { background: rgba(220,38,38,0.8); border-color: #ff0000; }
    75% { background: rgba(220,38,38,0.4); border-color: #ef4444; }
    100% { background: rgba(220,38,38,0); border-color: #ef4444; }
  }
  .alarm-active {
    animation: alarmFlash 0.3s ease infinite !important;
  }
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-left">
    <div class="topbar-logo">
      <img src="/static/logo.jpg" alt="MMSU">
    </div>
    <div class="topbar-title">
      MMSU CCIS Parking Gate
      <span>Select Mode - Scan QR Code</span>
    </div>
  </div>
  <div class="topbar-right">
    <div class="topbar-clock" id="clock">--:-- -- PHT</div>
    <div class="topbar-mmsu">
      <img src="/static/logo.jpg" alt="MMSU">
    </div>
  </div>
</div>

<div class="kiosk">
  <div class="cam-side">
    <div class="cam-label">📷 QR Code Scanner</div>
    <div class="cam-wrap">
      <video id="video" autoplay playsinline></video>
      <canvas id="canvas"></canvas>
      <div class="cam-overlay">
        <div class="cam-box">
          <div class="cam-box-bl"></div>
          <div class="cam-box-br"></div>
          <div class="scan-beam"></div>
        </div>
      </div>
      <div class="debug-panel" id="debug">Select mode and scan QR</div>
      <div class="cooldown-overlay" id="cooldown-overlay">
        <div class="cooldown-box">
          <h3>⏳ Please Wait</h3>
          <p>Next scan available in</p>
          <div class="cooldown-timer" id="cooldown-timer">5</div>
          <p style="margin-top:18px;font-size:0.85rem">seconds</p>
        </div>
      </div>
    </div>
    <div class="cam-instruction">
      <strong>Select Mode First, Then Scan QR</strong>
    </div>
    <div class="cam-status">
      <div class="dot pulse" id="status-dot"></div>
      <span id="status-text">Initializing camera...</span>
    </div>
    <div id="mode-indicator" class="mode-indicator entrance">🚗 ENTRANCE MODE - Ready to Scan</div>
    <div class="mode-buttons">
      <button class="mode-btn entrance active" id="entrance-mode-btn" onclick="switchToEntranceMode()">🚗 Entrance</button>
      <button class="mode-btn exit" id="exit-mode-btn" onclick="switchToExitMode()">🚪 Exit</button>
    </div>
  </div>

  <div class="result-side idle" id="result-side">
    <div class="idle-state" id="idle-state">
      <div class="idle-icon">🏢</div>
      <div class="idle-title">Ready to Scan</div>
      <div class="idle-sub">Select mode above and show QR code</div>
    </div>

    <div class="scan-result" id="scan-result" style="position:relative">
      <div class="welcome-msg">
        <span class="welcome-emoji" id="res-emoji">✅</span>
        <div class="welcome-text green" id="res-welcome">Welcome!</div>
        <div class="welcome-sub" id="res-sub">Entry has been logged</div>
      </div>
      <div class="user-card">
        <div class="user-top">
          <div class="avatar" id="res-avatar">?</div>
          <div>
            <div class="uname" id="res-name">—</div>
            <div class="uid" id="res-id">—</div>
          </div>
        </div>
        <div class="detail-grid">
          <div class="detail-item"><div class="dl">Position</div><div class="dv" id="res-position">—</div></div>
          <div class="detail-item"><div class="dl">College</div><div class="dv" id="res-college">—</div></div>
          <div class="detail-item"><div class="dl">Vehicle</div><div class="dv" id="res-vehicle">—</div></div>
          <div class="detail-item"><div class="dl">Department</div><div class="dv" id="res-dept">—</div></div>
        </div>
      </div>
      <div class="slot-bar">
        <span class="sl" id="res-slot-label">Parking Slot</span>
        <span class="sv" id="res-slot-val">—</span>
      </div>
      <div class="scan-ts" id="res-time">—</div>
      <div class="countdown" id="countdown"></div>
    </div>

    <div class="recent-ticker">
      <span class="ticker-label">📡 Recent</span>
      <span id="ticker-content" class="ticker-item">No scans yet</span>
    </div>
  </div>
</div>

<script>
  (function() {
    console.log('QR Scanner starting...');

    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d');
    const statusText = document.getElementById('status-text');
    const statusDot = document.getElementById('status-dot');
    const debugEl = document.getElementById('debug');
    const modeIndicator = document.getElementById('mode-indicator');
    const cooldownOverlay = document.getElementById('cooldown-overlay');
    const cooldownTimer = document.getElementById('cooldown-timer');
    const entranceBtn = document.getElementById('entrance-mode-btn');
    const exitBtn = document.getElementById('exit-mode-btn');

    let stream = null;
    let scanning = true;
    let lastQR = '';
    let lastQRTime = 0;
    let resetTimer = null;
    let countdownInterval = null;
    let currentMode = 'entry';
    let cooldownActive = false;
    let cooldownInterval = null;
    let cooldownSeconds = 0;
    let cameraReady = false;

    const SCAN_COOLDOWN = 5;

    // ========== ALARM VARIABLES ==========
    let alarmInterval = null;
    let alarmTimeout = null;
    let isAlarmPlaying = false;

    // ========== LOUD, REPEATING ALARM SOUND (30 seconds, war siren effect) ==========
    function playAlarmSound() {
      console.log('🔊 Playing LOUD repeating alarm for unregistered scan!');

      // Stop any existing alarm
      stopAlarm();

      // 1. Speak "Access Denied" loudly
      const accessDeniedMsg = new SpeechSynthesisUtterance('ACCESS DENIED!');
      accessDeniedMsg.rate = 0.9;
      accessDeniedMsg.pitch = 1.2;
      accessDeniedMsg.volume = 1;
      accessDeniedMsg.lang = 'en-US';
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(accessDeniedMsg);

      isAlarmPlaying = true;

      // 2. Create war siren effect using Web Audio API
      let audioContext = null;
      let sirenInterval = null;

      try {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();

        // Function to play a siren sweep (rising and falling tone)
        function playSirenSweep(duration, startFreq, endFreq, volume) {
          const now = audioContext.currentTime;
          const osc = audioContext.createOscillator();
          const gain = audioContext.createGain();

          osc.type = 'sawtooth'; // Harsher sound for alarm
          osc.connect(gain);
          gain.connect(audioContext.destination);

          osc.frequency.setValueAtTime(startFreq, now);
          osc.frequency.exponentialRampToValueAtTime(endFreq, now + duration);

          gain.gain.setValueAtTime(volume, now);
          gain.gain.exponentialRampToValueAtTime(0.00001, now + duration);

          osc.start();
          osc.stop(now + duration);

          return { osc, gain };
        }

        // Play repeating siren pattern for 30 seconds
        let sweepCount = 0;
        const totalDuration = 30000; // 30 seconds
        const startTime = Date.now();

        function playNextSweep() {
          if (!isAlarmPlaying) return;
          if (Date.now() - startTime >= totalDuration) {
            stopAlarm();
            return;
          }

          // Play "whoop-whoop" style siren (up and down)
          // First sweep: rising tone (400Hz -> 1200Hz)
          playSirenSweep(0.8, 400, 1200, 0.5);
          // Second sweep: falling tone (1200Hz -> 400Hz) after a short delay
          setTimeout(() => {
            if (isAlarmPlaying) {
              playSirenSweep(0.8, 1200, 400, 0.5);
            }
          }, 200);

          sweepCount++;
          // Schedule next pair of sweeps
          sirenInterval = setTimeout(playNextSweep, 1600);
        }

        playNextSweep();

        // Also add a constant high-pitch beep in the background for urgency
        const constantBeep = audioContext.createOscillator();
        const beepGain = audioContext.createGain();
        constantBeep.type = 'square';
        constantBeep.frequency.value = 880;
        constantBeep.connect(beepGain);
        beepGain.connect(audioContext.destination);
        beepGain.gain.value = 0.15;
        constantBeep.start();

        // Store references to stop later
        window._alarmBeep = constantBeep;
        window._alarmBeepGain = beepGain;
        window._alarmSirenInterval = sirenInterval;
        window._alarmAudioContext = audioContext;

      } catch(e) {
        console.log('Web Audio API error:', e);
        // Fallback: use simple beeps
        fallbackAlarm();
      }

      // 3. Also repeat voice warning every 5 seconds during the 30-second alarm
      let voiceCount = 0;
      const voiceInterval = setInterval(() => {
        if (!isAlarmPlaying) {
          clearInterval(voiceInterval);
          return;
        }
        if (voiceCount < 6) { // Say "Access Denied" up to 6 times during alarm
          const repeatMsg = new SpeechSynthesisUtterance('ACCESS DENIED!');
          repeatMsg.rate = 0.9;
          repeatMsg.pitch = 1.2;
          repeatMsg.volume = 1;
          window.speechSynthesis.speak(repeatMsg);
          voiceCount++;
        }
      }, 5000);

      window._alarmVoiceInterval = voiceInterval;

      // 4. Set timeout to stop everything after 30 seconds
      alarmTimeout = setTimeout(() => {
        stopAlarm();
      }, 30000);
    }

    function stopAlarm() {
      console.log('🔊 Stopping alarm');
      isAlarmPlaying = false;

      // Stop voice interval
      if (window._alarmVoiceInterval) {
        clearInterval(window._alarmVoiceInterval);
        window._alarmVoiceInterval = null;
      }

      // Stop siren interval
      if (window._alarmSirenInterval) {
        clearTimeout(window._alarmSirenInterval);
        window._alarmSirenInterval = null;
      }

      // Stop Web Audio context
      if (window._alarmAudioContext) {
        try {
          window._alarmAudioContext.close();
        } catch(e) {}
        window._alarmAudioContext = null;
      }

      // Stop constant beep
      if (window._alarmBeep) {
        try {
          window._alarmBeep.stop();
        } catch(e) {}
        window._alarmBeep = null;
      }

      if (alarmTimeout) {
        clearTimeout(alarmTimeout);
        alarmTimeout = null;
      }

      // Remove visual alarm class
      const side = document.getElementById('result-side');
      if (side) {
        side.classList.remove('alarm-active');
      }
    }

    // Fallback alarm using simple AudioContext beeps if main alarm fails
    function fallbackAlarm() {
      let beepCount = 0;
      const fallbackInterval = setInterval(() => {
        if (!isAlarmPlaying) {
          clearInterval(fallbackInterval);
          return;
        }
        try {
          const ctx = new (window.AudioContext || window.webkitAudioContext)();
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.frequency.value = 1000;
          gain.gain.value = 0.5;
          osc.start();
          gain.gain.exponentialRampToValueAtTime(0.00001, ctx.currentTime + 0.5);
          osc.stop(ctx.currentTime + 0.5);
          setTimeout(() => ctx.close(), 600);
        } catch(e) {}
        beepCount++;
        if (beepCount >= 20) clearInterval(fallbackInterval);
      }, 1500);

      window._alarmFallbackInterval = fallbackInterval;

      alarmTimeout = setTimeout(() => {
        if (window._alarmFallbackInterval) clearInterval(window._alarmFallbackInterval);
        isAlarmPlaying = false;
        const side = document.getElementById('result-side');
        if (side) side.classList.remove('alarm-active');
      }, 30000);
    }

    window.switchToEntranceMode = function() {
      currentMode = 'entry';
      entranceBtn.classList.add('active');
      exitBtn.classList.remove('active');
      modeIndicator.className = 'mode-indicator entrance';
      modeIndicator.innerHTML = '🚗 ENTRANCE MODE - Ready to Scan';
      if (cameraReady) {
        statusText.textContent = '🚗 Entrance Mode - Ready';
      }
      console.log('Switched to Entrance Mode');
    };

    window.switchToExitMode = function() {
      currentMode = 'exit';
      exitBtn.classList.add('active');
      entranceBtn.classList.remove('active');
      modeIndicator.className = 'mode-indicator exit';
      modeIndicator.innerHTML = '🚪 EXIT MODE - Ready to Scan';
      if (cameraReady) {
        statusText.textContent = '🚪 Exit Mode - Ready';
      }
      console.log('Switched to Exit Mode');
    };

    function startCooldown() {
      cooldownActive = true;
      cooldownSeconds = SCAN_COOLDOWN;
      cooldownOverlay.style.display = 'flex';
      cooldownTimer.textContent = cooldownSeconds;
      scanning = false;

      cooldownInterval = setInterval(() => {
        cooldownSeconds--;
        cooldownTimer.textContent = cooldownSeconds;

        if (cooldownSeconds <= 0) {
          clearInterval(cooldownInterval);
          cooldownActive = false;
          cooldownOverlay.style.display = 'none';
          scanning = true;
          statusDot.className = 'dot pulse';
          if (cameraReady) {
            statusText.textContent = currentMode === 'entry' ? '🚗 Entrance Mode - Ready' : '🚪 Exit Mode - Ready';
          }
          debugEl.textContent = 'Ready to scan';
        }
      }, 1000);
    }

    function updateClock() {
      const now = new Date();
      const ph = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Manila' }));
      const pad = n => String(n).padStart(2, '0');
      const h = ph.getHours();
      const ampm = h >= 12 ? 'PM' : 'AM';
      const hr12 = h % 12 || 12;
      const clockEl = document.getElementById('clock');
      if (clockEl) {
        clockEl.textContent = `${hr12}:${pad(ph.getMinutes())}:${pad(ph.getSeconds())} ${ampm} PHT`;
      }
    }
    updateClock();
    setInterval(updateClock, 1000);

    function speak(text) {
      if (!window.speechSynthesis) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'en-PH'; u.rate = 0.95; u.pitch = 1.0; u.volume = 1.0;
      window.speechSynthesis.speak(u);
    }

    async function startCamera() {
      try {
        console.log('Requesting camera...');
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'environment' }
        });
        video.srcObject = stream;
        video.addEventListener('loadedmetadata', () => {
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          console.log('Camera ready');
          cameraReady = true;
          statusDot.className = 'dot pulse';
          statusText.textContent = '🚗 Entrance Mode - Ready';
          debugEl.textContent = 'Select mode and scan QR';
          startScanning();
        });
      } catch (err) {
        console.error('Camera error:', err);
        statusDot.className = 'dot err';
        statusText.textContent = 'Camera error: ' + err.message;
        debugEl.textContent = 'Error: ' + err.message;
      }
    }

    function startScanning() {
      scanning = true;
      scanLoop();
    }

    function scanLoop() {
      if (!scanning) {
        requestAnimationFrame(scanLoop);
        return;
      }

      if (video.readyState === video.HAVE_ENOUGH_DATA) {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(imageData.data, imageData.width, imageData.height);
        if (code) {
          console.log('QR DETECTED!', code.data);
          debugEl.textContent = `Detected: ${code.data}`;
          statusDot.className = 'dot scanning';
          handleQRCode(code.data);
        }
      }
      requestAnimationFrame(scanLoop);
    }

    function handleQRCode(qrData) {
      const now = Date.now();

      if (cooldownActive) {
        console.log('Cooldown active, skipping scan');
        debugEl.textContent = 'Please wait for cooldown...';
        return;
      }

      if (qrData === lastQR && now - lastQRTime < 3000) {
        console.log('Skipping duplicate scan');
        return;
      }

      lastQR = qrData;
      lastQRTime = now;
      statusText.textContent = 'Processing...';
      debugEl.textContent = `Processing: ${qrData} | Mode: ${currentMode}`;

      fetch('/api/qr/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ qr_data: qrData, mode: currentMode })
      })
      .then(res => res.json())
      .then(data => {
        console.log('Server response:', data);
        showResult(data);
        statusDot.className = 'dot pulse';
        startCooldown();
      })
      .catch(err => {
        console.error('API error:', err);
        statusText.textContent = 'Server error';
        statusDot.className = 'dot err';
        debugEl.textContent = 'Error: ' + err.message;
        startCooldown();
      });
    }
    let lastShowResultTime = 0;
    let isShowingResult = false;

    function showResult(data) {
        const now = Date.now();
        
        // Prevent showing the same result too quickly (within 3 seconds)
        if (isShowingResult) {
            console.log('[SHOW RESULT] Skipping - too soon or already showing');
            return;
        }
        
        isShowingResult = true;
        lastShowResultTime = now;
        
        console.log('[SHOW RESULT] Showing:', data);
        
        clearTimeout(resetTimer);
        clearInterval(countdownInterval);
        document.getElementById('idle-state').style.display = 'none';
        document.getElementById('scan-result').style.display = 'block';
        const side = document.getElementById('result-side');

        if (data.status === 'not_found') {
            playAlarmSound();
            side.classList.add('alarm-active');
            side.className = 'result-side denied';
            document.getElementById('res-emoji').textContent = '❌';
            document.getElementById('res-welcome').textContent = 'Access Denied';
            document.getElementById('res-welcome').className = 'welcome-text red';
            document.getElementById('res-sub').textContent = 'QR Code / RFID not registered';
            document.getElementById('res-name').textContent = 'Unknown';
            document.getElementById('res-id').textContent = '—';
            document.getElementById('res-avatar').textContent = '?';
            document.getElementById('res-position').textContent = '—';
            document.getElementById('res-college').textContent = '—';
            document.getElementById('res-vehicle').textContent = '—';
            document.getElementById('res-dept').textContent = '—';
            document.getElementById('res-slot-val').textContent = '—';
            speak('Access denied. This code is not registered.');
            startCountdown(5);
            setTimeout(() => { isShowingResult = false; }, 5000);
            return;
        }

        if (data.status === 'already_inside') {
            side.className = 'result-side denied';
            document.getElementById('res-emoji').textContent = '⛔';
            document.getElementById('res-welcome').textContent = 'Already Inside!';
            document.getElementById('res-welcome').className = 'welcome-text red';
            document.getElementById('res-sub').textContent = 'Please exit first';
            const u = data.user;
            const firstName = (u.full_name || '').split(' ')[0] || u.student_no;
            document.getElementById('res-name').textContent = u.full_name || '—';
            document.getElementById('res-id').textContent = u.student_no;
            document.getElementById('res-avatar').textContent = (u.full_name || 'U').split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
            document.getElementById('res-position').textContent = u.position || '—';
            document.getElementById('res-college').textContent = u.department || '—';
            document.getElementById('res-vehicle').textContent = u.vehicle_type || '—';
            document.getElementById('res-dept').textContent = u.department || '—';
            document.getElementById('res-slot-val').textContent = '—';
            speak(`${firstName}, you are already inside. Please exit first.`);
            startCountdown(5);
            setTimeout(() => { isShowingResult = false; }, 5000);
            return;
        }

        if (data.status === 'not_inside') {
            side.className = 'result-side denied';
            document.getElementById('res-emoji').textContent = '❓';
            document.getElementById('res-welcome').textContent = 'Not Inside!';
            document.getElementById('res-welcome').className = 'welcome-text red';
            document.getElementById('res-sub').textContent = 'No active entry found';
            const u = data.user;
            const firstName = (u.full_name || '').split(' ')[0] || u.student_no;
            document.getElementById('res-name').textContent = u.full_name || '—';
            document.getElementById('res-id').textContent = u.student_no;
            document.getElementById('res-avatar').textContent = (u.full_name || 'U').split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
            document.getElementById('res-position').textContent = u.position || '—';
            document.getElementById('res-college').textContent = u.department || '—';
            document.getElementById('res-vehicle').textContent = u.vehicle_type || '—';
            document.getElementById('res-dept').textContent = u.department || '—';
            document.getElementById('res-slot-val').textContent = '—';
            speak(`${firstName}, no active entry found. Please enter first.`);
            startCountdown(5);
            setTimeout(() => { isShowingResult = false; }, 5000);
            return;
        }

        if (data.status === 'full') {
            side.className = 'result-side full';
            document.getElementById('res-emoji').textContent = '⚠️';
            document.getElementById('res-welcome').textContent = 'Parking Full!';
            document.getElementById('res-welcome').className = 'welcome-text orange';
            document.getElementById('res-sub').textContent = 'No available slots';
            const u = data.user;
            const firstName = (u.full_name || '').split(' ')[0] || u.student_no;
            const initials = (u.full_name || 'U').split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
            document.getElementById('res-avatar').textContent = initials;
            document.getElementById('res-name').textContent = u.full_name || '—';
            document.getElementById('res-id').textContent = u.student_no + ' · ' + (u.position || 'Student');
            document.getElementById('res-position').textContent = u.position || '—';
            document.getElementById('res-college').textContent = u.department || '—';
            document.getElementById('res-vehicle').textContent = u.vehicle_type || '—';
            document.getElementById('res-dept').textContent = u.department || '—';
            document.getElementById('res-slot-label').textContent = data.slot ? data.slot.label : 'Parking';
            document.getElementById('res-slot-val').textContent = 'FULL';
            document.getElementById('res-slot-val').className = 'sv full';
            speak(`Welcome ${firstName}. However, parking is currently full.`);
            startCountdown(8);
            setTimeout(() => { isShowingResult = false; }, 8000);
            return;
        }

        // Normal entry/exit flow
        const u = data.user;
        const isExit = data.scan_type === 'exit';
        const firstName = (u.full_name || u.name || u.visitor_id || '').split(' ')[0] || 'Visitor';
        const initials = (u.full_name || u.name || 'V').split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();

        document.getElementById('res-avatar').textContent = initials;
        document.getElementById('res-name').textContent = u.full_name || u.name || u.visitor_id || 'Visitor';
        document.getElementById('res-id').textContent = u.student_no || u.visitor_id || '—';
        document.getElementById('res-position').textContent = u.position || 'Visitor';
        document.getElementById('res-college').textContent = u.department || u.college || '—';
        document.getElementById('res-vehicle').textContent = u.vehicle_type || '—';
        document.getElementById('res-dept').textContent = u.department || u.purpose || '—';
        document.getElementById('res-time').textContent = (isExit ? 'Exit' : 'Entry') + ' logged at ' + data.scan_time + ' (PHT)';

        if (isExit) {
            side.className = 'result-side exit-ok';
            document.getElementById('res-emoji').textContent = '👋';
            document.getElementById('res-welcome').textContent = `Thank you, ${firstName}!`;
            document.getElementById('res-welcome').className = 'welcome-text blue';
            document.getElementById('res-sub').textContent = 'Drive safe! See you next time.';
            document.getElementById('res-slot-label').textContent = 'Slot Released';
            document.getElementById('res-slot-val').textContent = data.slot ? data.slot.label : '—';
            document.getElementById('res-slot-val').className = 'sv';
            speak(`Thank you, ${firstName}! Drive safe. See you next time.`);
        } else {
            side.className = 'result-side granted';
            document.getElementById('res-emoji').textContent = '✅';
            document.getElementById('res-welcome').textContent = `Welcome to CCIS, ${firstName}!`;
            document.getElementById('res-welcome').className = 'welcome-text green';
            document.getElementById('res-sub').textContent = 'Access granted. Entry logged successfully.';
            if (data.slot) {
                document.getElementById('res-slot-label').textContent = data.slot.label;
                document.getElementById('res-slot-val').textContent = data.slot.available + ' / ' + data.slot.capacity + ' slots left';
            }
            speak(`Welcome to CCIS, ${firstName}! Access granted.`);
        }

        startCountdown(8);
        setTimeout(() => { isShowingResult = false; }, 8000);
    }

    function startCountdown(secs) {
      let t = secs;
      const countdownEl = document.getElementById('countdown');
      if (countdownEl) {
        countdownEl.textContent = 'Resetting in ' + t + 's...';
      }
      countdownInterval = setInterval(() => {
        t--;
        if (countdownEl) {
          countdownEl.textContent = t > 0 ? 'Resetting in ' + t + 's...' : '';
        }
        if (t <= 0) clearInterval(countdownInterval);
      }, 1000);
      resetTimer = setTimeout(() => {
        document.getElementById('idle-state').style.display = 'block';
        document.getElementById('scan-result').style.display = 'none';
        document.getElementById('result-side').className = 'result-side idle';
        if (cameraReady) {
          statusText.textContent = currentMode === 'entry' ? '🚗 Entrance Mode - Ready' : '🚪 Exit Mode - Ready';
        }
        debugEl.textContent = 'Ready to scan';
      }, secs * 1000);
    }
// ========== POLL RFID SCANS FROM SERVER ==========
const seenScanIds = new Set();
let isProcessingRFID = false;

async function pollRFID() {
    if (isProcessingRFID) return;
    try {
        isProcessingRFID = true;
        const res = await fetch('/api/latest-scan');
        const data = await res.json();

        // Only process if scan exists AND we haven't seen this ID before
        if (data.scan && data.scan.id && !seenScanIds.has(data.scan.id)) {
            seenScanIds.add(data.scan.id);
            if (seenScanIds.size > 50) seenScanIds.clear(); // prevent memory leak

            const scan = data.scan;
            const rfidStatus = scan.status || 'ok';
            const isExit = (scan.scan_type || '').toLowerCase().includes('exit');

            const userData = {
                full_name: scan.name || scan.tag_id || 'Unknown',
                student_no: scan.student_no || scan.tag_id || '',
                position: scan.position || 'Student',
                department: scan.department || 'CCIS',
                college: scan.college || 'CCIS',
                vehicle_type: scan.vehicle_type || 'Car',
            };

            showResult({
                status: rfidStatus,
                scan_type: isExit ? 'exit' : 'entry',
                scan_time: scan.scan_time,
                user: userData,
                slot: null
            });
        }
    } catch (e) {
        console.error('[RFID POLL] Error:', e);
    } finally {
        setTimeout(() => { isProcessingRFID = false; }, 1000);
    }
}

setInterval(pollRFID, 3000);
    
    startCamera();
  })();
</script>
</body>
</html>'''


# ============================================================
#  ROUTES
# ============================================================

@app.route("/")
def landing():
    if 'user_id' in session:
        if session.get('is_admin'):
            return redirect('/admin')
        return redirect('/dashboard')
    return LANDING_HTML

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        student_no = request.form.get("student_no", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE student_no=? AND password_hash=?",
            (student_no, hash_password(password))
        ).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['student_no'] = user['student_no']
            session['is_admin'] = bool(user['is_admin'])
            if user['is_admin']:
                return redirect('http://127.0.0.1:5001')
            return redirect('/dashboard')
        return render_template_string(LOGIN_HTML, error="Invalid ID number or password.", success=None)

    success = "Account created successfully! You can now sign in." if request.args.get("registered") else None
    return render_template_string(LOGIN_HTML, error=None, success=success)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        if f.get("password") != f.get("confirm_password"):
            return render_template_string(REGISTER_HTML, error="Passwords do not match.", success=None)

        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO users (student_no, password_hash, full_name, college, department,
                    email, position, vehicle_model, vehicle_color, vehicle_type, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f.get("student_no", "").strip(),
                hash_password(f.get("password", "")),
                f.get("full_name", "").strip(),
                f.get("college", "").strip(),
                f.get("department", "").strip(),
                f.get("email", "").strip(),
                f.get("position", "Student"),
                f.get("vehicle_model", "").strip(),
                f.get("vehicle_color", "").strip(),
                f.get("vehicle_type", "").strip(),
                ph_now()
            ))
            conn.commit()
            conn.close()
            return redirect('/login?registered=1')
        except sqlite3.IntegrityError:
            conn.close()
            return render_template_string(REGISTER_HTML, error="ID number already registered.", success=None)

    return render_template_string(REGISTER_HTML, error=None, success=None)

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    conn.close()
    return render_template_string(DASHBOARD_HTML, user=user)

@app.route("/logout")
def logout():
    session.clear()
    return redirect('/')

@app.route("/api/user/stats")
@login_required
def api_user_stats():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    today = ph_today()
    sno = user['student_no']
    tid = user['tag_id'] or ""
    total = conn.execute(
        "SELECT COUNT(*) FROM rfid_scans WHERE tag_id=? OR tag_id=?",
        (tid, sno)
    ).fetchone()[0]
    today_c = conn.execute(
        "SELECT COUNT(*) FROM rfid_scans WHERE (tag_id=? OR tag_id=?) AND scan_time LIKE ?",
        (tid, sno, f"{today}%")
    ).fetchone()[0]
    viols = conn.execute("SELECT COUNT(*) FROM violations WHERE student_no=?", (sno,)).fetchone()[0]
    conn.close()
    return jsonify({"total": total, "today": today_c, "violations": viols})

@app.route("/api/user/logs")
@login_required
def api_user_logs():
    limit = request.args.get("limit", 100, type=int)
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    sno = user['student_no']
    tid = user['tag_id'] or ""
    rows = conn.execute(
        "SELECT * FROM rfid_scans WHERE tag_id=? OR tag_id=? ORDER BY id DESC LIMIT ?",
        (tid, sno, limit)
    ).fetchall()
    logs = [dict(r) for r in rows]
    conn.close()
    return jsonify({"logs": logs})

@app.route("/api/user/logs-paired")
@login_required
def api_user_logs_paired():
    limit = request.args.get("limit", 100, type=int)
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    sno = user['student_no']
    tid = user['tag_id'] or ""

    # Get all entry scans
    entries = conn.execute(
        """SELECT scan_time, date(scan_time) as scan_date, time(scan_time) as scan_time_only 
           FROM rfid_scans 
           WHERE (tag_id=? OR tag_id=?) AND scan_type LIKE '%entry%' 
           ORDER BY scan_time DESC LIMIT ?""",
        (tid, sno, limit)
    ).fetchall()

    paired_logs = []
    for entry in entries:
        entry_date = entry['scan_date']
        entry_time = entry['scan_time_only']
        entry_full = entry['scan_time']

        # Find matching exit scan for the same date (same session)
        exit_scan = conn.execute(
            """SELECT time(scan_time) as exit_time 
               FROM rfid_scans 
               WHERE (tag_id=? OR tag_id=?) 
               AND scan_type LIKE '%exit%' 
               AND date(scan_time) = ? 
               AND scan_time > ?
               ORDER BY scan_time LIMIT 1""",
            (tid, sno, entry_date, entry_full)
        ).fetchone()

        paired_logs.append({
            'date': entry_date,
            'entry_time': entry_time,
            'exit_time': exit_scan['exit_time'] if exit_scan else None
        })

    conn.close()
    return jsonify({"logs": paired_logs})

@app.route("/api/user/violations")
@login_required
def api_user_violations():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    rows = conn.execute(
        "SELECT * FROM violations WHERE student_no=? ORDER BY date DESC",
        (user['student_no'],)
    ).fetchall()
    conn.close()
    return jsonify({"violations": [dict(r) for r in rows]})

@app.route("/api/user/notices")
@login_required
def api_user_notices():
    conn = get_db()
    rows = conn.execute("SELECT * FROM notices ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify({"notices": [dict(r) for r in rows]})

@app.route("/api/user/qr")
@login_required
def api_user_qr():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    conn.close()
    qr_img = qrcode.make(user['student_no'])
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return jsonify({"qr": base64.b64encode(buf.read()).decode()})

@app.route("/admin")
@admin_required
def admin():
    return redirect("http://127.0.0.1:5001")

@app.route("/qr-scanner")
def qr_scanner():
    return QR_SCANNER_HTML

# ============================================================
#  VISITOR API ENDPOINTS
# ============================================================
@app.route("/api/visitors")
def api_get_visitors():
    conn = get_db()
    rows = conn.execute("SELECT * FROM visitors ORDER BY visitor_id").fetchall()
    conn.close()
    return jsonify({"visitors": [dict(r) for r in rows]})

@app.route("/api/visitors/toggle", methods=["POST"])
def api_toggle_visitor():
    d = request.json
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("UPDATE visitors SET is_active=? WHERE visitor_id=?", (d.get("is_active"), d.get("visitor_id")))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

# ============================================================
#  UPDATED QR SCAN ROUTE (SUPPORTS VISITORS)
# ============================================================
@app.route("/api/qr/scan", methods=["POST"])
def api_qr_scan():
    d = request.json
    qr_data = d.get("qr_data", "").strip()
    scan_mode = d.get("mode", "entry")
    source = d.get("source", "qr")
    rfid_status = d.get("status", None)

    conn = get_db()

    # ========== HANDLE RFID WITH SPECIAL STATUS (already_inside, not_found) ==========
    if source == "rfid" and rfid_status:
        global last_rfid_scan
        user = conn.execute("SELECT * FROM users WHERE tag_id=? OR student_no=?", (qr_data, qr_data)).fetchone()
        conn.close()

        # ===== STORE FOR KIOSK POLLING — WITH STATUS =====
        last_rfid_scan = {
            "id": int(time.time() * 1000),
            "tag_id": qr_data,
            "name": user["full_name"] if user else "Unknown",
            "scan_time": ph_now(),
            "scan_type": scan_mode,
            "status": rfid_status,  # <-- key: already_inside / not_found / ok
            "position": user["position"] if user else "Student",
            "department": user["department"] if user else "CCIS",
            "college": user["college"] if user else "CCIS",
            "vehicle_type": user["vehicle_type"] if user else "Car",
            "student_no": user["student_no"] if user else qr_data,
        }

        if user:
            return jsonify({
                "status": rfid_status,
                "scan_type": scan_mode,
                "scan_time": ph_now(),
                "user": {
                    "student_no": user["student_no"],
                    "full_name": user["full_name"],
                    "position": user["position"] or "Student",
                    "college": user["college"] or "—",
                    "department": user["department"] or "—",
                    "vehicle_type": user["vehicle_type"] or "Car",
                },
                "slot": None
            })
        else:
            return jsonify({
                "status": rfid_status,
                "scan_type": scan_mode,
                "scan_time": ph_now(),
                "user": {
                    "student_no": qr_data,
                    "full_name": "Unknown",
                    "position": "Visitor",
                    "college": "—",
                    "department": "—",
                    "vehicle_type": "Car",
                },
                "slot": None
            })

    # ========== CHECK VISITOR QR ==========
    visitor = conn.execute("SELECT * FROM visitors WHERE visitor_id=? AND is_active=1", (qr_data,)).fetchone()

    if visitor:
        scan_time = ph_now()
        last_scan = conn.execute(
            "SELECT scan_type FROM rfid_scans WHERE tag_id=? ORDER BY id DESC LIMIT 1",
            (visitor["visitor_id"],)
        ).fetchone()
        last_type = (last_scan["scan_type"] or "") if last_scan else ""

        if scan_mode == "exit":
            if last_type not in ("entry", "qr_entry", "rfid_entry"):
                conn.close()
                return jsonify({"status": "not_inside", "scan_type": "exit",
                                "user": {"visitor_id": visitor["visitor_id"],
                                         "name": visitor["name"] or visitor["visitor_id"]}})
            scan_type = "qr_exit"
        else:
            if last_type in ("entry", "qr_entry", "rfid_entry"):
                conn.close()
                return jsonify({"status": "already_inside", "scan_type": "entry",
                                "user": {"visitor_id": visitor["visitor_id"],
                                         "name": visitor["name"] or visitor["visitor_id"]}})
            scan_type = "qr_entry"

        is_exit = scan_type == "qr_exit"
        conn.execute("INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna, scan_type) VALUES (?, ?, ?, ?, ?)",
                     (visitor["visitor_id"], scan_time, "QR", "QR", scan_type))
        conn.execute("INSERT INTO visitor_scans (visitor_id, scan_time, scan_type) VALUES (?, ?, ?)",
                     (visitor["visitor_id"], scan_time, "exit" if is_exit else "entry"))
        conn.commit()
        conn.close()

        return jsonify({
            "status": "ok",
            "scan_time": scan_time,
            "scan_type": "exit" if is_exit else "entry",
            "user": {
                "visitor_id": visitor["visitor_id"],
                "name": visitor["name"] or visitor["visitor_id"],
                "full_name": visitor["name"] or visitor["visitor_id"],
                "position": "Visitor",
                "college": "—",
                "department": "—",
                "vehicle_type": "Car"
            },
            "slot": None
        })

    # ========== CHECK REGULAR USER ==========
    user = conn.execute("SELECT * FROM users WHERE student_no=?", (qr_data,)).fetchone()

    if not user:
        conn.close()
        return jsonify({"status": "not_found"})

    # Check if user is already inside
    inside = conn.execute("SELECT * FROM currently_inside WHERE student_no=?", (qr_data,)).fetchone()
    is_inside = inside is not None

    # ========== ALREADY INSIDE - Return status for kiosk ==========
    if scan_mode == "entry" and is_inside:
        conn.close()
        return jsonify({
            "status": "already_inside",
            "scan_type": "entry",
            "scan_time": ph_now(),
            "user": {
                "student_no": user["student_no"],
                "full_name": user["full_name"],
                "position": user["position"] or "Student",
                "college": user["college"] or "—",
                "department": user["department"] or "—",
                "vehicle_type": user["vehicle_type"] or "Car",
            },
            "slot": None
        })

    # ========== NOT INSIDE for exit ==========
    if scan_mode == "exit" and not is_inside:
        conn.close()
        return jsonify({
            "status": "not_inside",
            "scan_type": "exit",
            "scan_time": ph_now(),
            "user": {
                "student_no": user["student_no"],
                "full_name": user["full_name"],
                "position": user["position"] or "Student",
                "college": user["college"] or "—",
                "department": user["department"] or "—",
                "vehicle_type": user["vehicle_type"] or "Car",
            },
            "slot": None
        })

    # ========== PROCESS ENTRY/EXIT ==========
    scan_time = ph_now()
    position = (user["position"] or "Student").lower()
    vehicle_type = (user["vehicle_type"] or "").lower()
    is_moto = vehicle_type in ["motorcycle", "motor", "bike"]
    is_staff = position in ["faculty", "staff"]
    slot_type = ("faculty" if is_staff else "student") + ("_moto" if is_moto else "_car")
    slot_labels = {
        "faculty_car": "Faculty/PWD Cars",
        "faculty_moto": "Faculty Motorcycles",
        "student_car": "Student Cars",
        "student_moto": "Student Motorcycles"
    }

    if scan_mode == "entry":
        slot = conn.execute("SELECT * FROM parking_slots WHERE slot_type=?", (slot_type,)).fetchone()
        slot_info = None

        if slot:
            available = slot["capacity"] - slot["occupied"]
            if available <= 0:
                conn.close()
                return jsonify({
                    "status": "full",
                    "scan_time": scan_time,
                    "scan_type": "entry",
                    "user": {
                        "student_no": user["student_no"],
                        "full_name": user["full_name"],
                        "position": user["position"],
                        "college": user["college"],
                        "department": user["department"],
                        "vehicle_type": user["vehicle_type"],
                    },
                    "slot": {"label": slot_labels.get(slot_type, slot_type), "available": 0,
                             "capacity": slot["capacity"], "status": "full"}
                })
            else:
                conn.execute("UPDATE parking_slots SET occupied = MIN(occupied + 1, capacity) WHERE slot_type=?",
                             (slot_type,))
                available -= 1
                status = "full" if available <= 0 else "warning" if available < slot["capacity"] * 0.2 else "ok"
                slot_info = {"label": slot_labels.get(slot_type, slot_type), "available": max(0, available),
                             "capacity": slot["capacity"], "status": status}

        conn.execute("INSERT INTO currently_inside (student_no, entry_time, slot_type) VALUES (?, ?, ?)",
                     (qr_data, scan_time, slot_type))
        conn.execute("INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna, scan_type) VALUES (?, ?, ?, ?, ?)",
                     (user["student_no"], scan_time, "QR", "QR", "qr_entry"))
        conn.execute("INSERT INTO qr_scans (student_no, scan_time, method) VALUES (?, ?, 'qr')",
                     (qr_data, scan_time))
        conn.commit()
        conn.close()

        return jsonify({
            "status": "ok",
            "scan_time": scan_time,
            "scan_type": "entry",
            "user": {
                "student_no": user["student_no"],
                "full_name": user["full_name"],
                "position": user["position"],
                "college": user["college"],
                "department": user["department"],
                "vehicle_type": user["vehicle_type"],
            },
            "slot": slot_info
        })

    else:  # exit mode
        exit_slot_type = inside["slot_type"] if inside else slot_type
        conn.execute("UPDATE parking_slots SET occupied = MAX(occupied - 1, 0) WHERE slot_type=?", (exit_slot_type,))
        conn.execute("DELETE FROM currently_inside WHERE student_no=?", (qr_data,))
        conn.execute("INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna, scan_type) VALUES (?, ?, ?, ?, ?)",
                     (user["student_no"], scan_time, "QR", "QR", "qr_exit"))
        conn.commit()
        conn.close()

        return jsonify({
            "status": "ok",
            "scan_time": scan_time,
            "scan_type": "exit",
            "user": {
                "student_no": user["student_no"],
                "full_name": user["full_name"],
                "position": user["position"],
                "college": user["college"],
                "department": user["department"],
                "vehicle_type": user["vehicle_type"],
            },
            "slot": None
        })

@app.route("/api/parking/slots")
def api_parking_slots():
    conn = get_db()
    rows = conn.execute("SELECT * FROM parking_slots").fetchall()
    conn.close()
    slots = {}
    for r in rows:
        available = r["capacity"] - r["occupied"]
        pct = (r["occupied"] / r["capacity"] * 100) if r["capacity"] > 0 else 0
        status = "full" if available <= 0 else "warning" if pct >= 80 else "ok"
        slots[r["slot_type"]] = {
            "capacity": r["capacity"],
            "occupied": r["occupied"],
            "available": max(0, available),
            "pct": round(pct),
            "status": status
        }
    return jsonify(slots)

@app.route("/api/parking/update", methods=["POST"])
def api_parking_update():
    d = request.json
    student_no = d.get("student_no", "")
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE student_no=?", (student_no,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"status": "error", "message": "User not found"})
    position = (user["position"] or "Student").lower()
    vehicle_type = (user["vehicle_type"] or "").lower()
    is_moto = vehicle_type in ["motorcycle", "motor", "bike"]
    slot_type = ("faculty" if position in ["faculty","staff","admin"] else "student") + ("_moto" if is_moto else "_car")
    slot = conn.execute("SELECT * FROM parking_slots WHERE slot_type=?", (slot_type,)).fetchone()
    if slot and slot["occupied"] >= slot["capacity"]:
        conn.close()
        return jsonify({"status": "full", "slot_type": slot_type})
    conn.execute(
        "UPDATE parking_slots SET occupied = MIN(occupied+1, capacity) WHERE slot_type=?",
        (slot_type,)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "slot_type": slot_type})

@app.route("/api/parking/exit", methods=["POST"])
def api_parking_exit():
    d = request.json
    student_no = d.get("student_no", "")
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE student_no=?", (student_no,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"status": "error", "message": "User not found"})
    position = (user["position"] or "Student").lower()
    vehicle_type = (user["vehicle_type"] or "").lower()
    is_moto = vehicle_type in ["motorcycle", "motor", "bike"]
    slot_type = ("faculty" if position in ["faculty","staff","admin"] else "student") + ("_moto" if is_moto else "_car")
    conn.execute(
        "UPDATE parking_slots SET occupied = MAX(occupied-1, 0) WHERE slot_type=?",
        (slot_type,)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "slot_type": slot_type})

@app.route("/api/parking/reset", methods=["POST"])
def api_parking_reset():
    conn = get_db()
    conn.execute("UPDATE parking_slots SET occupied=0")
    conn.execute("DELETE FROM currently_inside")
    conn.commit()
    conn.close()
    return jsonify({"status": "reset"})

@app.route("/api/inside/status")
def api_inside_status():
    conn = get_db()
    rows = conn.execute("""
        SELECT ci.*, u.full_name, u.vehicle_type, u.position 
        FROM currently_inside ci
        LEFT JOIN users u ON ci.student_no = u.student_no
        ORDER BY ci.entry_time DESC
    """).fetchall()
    conn.close()
    return jsonify({"inside": [dict(r) for r in rows]})

@app.route("/api/inside/clear", methods=["POST"])
def api_inside_clear():
    conn = get_db()
    conn.execute("DELETE FROM currently_inside")
    conn.commit()
    conn.close()
    return jsonify({"status": "cleared"})


@app.route("/api/rfid/notify", methods=["POST"])
def api_rfid_notify():
    """Receive RFID scan notifications from logger script and store for kiosk"""
    global last_rfid_scan
    data = request.json

    tag_id = data.get("tag_id", "")
    name = data.get("name", "Unknown")
    scan_time = data.get("scan_time", ph_now())
    scan_type = data.get("scan_type", "entry")
    message = data.get("message", "")
    position = data.get("position", "Student")
    department = data.get("department", "CCIS")
    vehicle_type = data.get("vehicle_type", "Car")

    # Generate a unique ID for this scan
    scan_id = int(time.time() * 1000)

    # Store the scan to be retrieved by the kiosk
    last_rfid_scan = {
        "id": scan_id,
        "tag_id": tag_id,
        "name": name,
        "scan_time": scan_time,
        "scan_type": scan_type,
        "position": position,
        "department": department,
        "vehicle_type": vehicle_type,
        "message": message,
        "student_no": tag_id if name == "Unknown" else ""
    }

    print(f"[RFID NOTIFY] Received: {name} - {scan_type}")
    print(f"[RFID NOTIFY] Stored scan with ID: {scan_id}")

    return jsonify({"status": "ok", "scan_id": scan_id})


# ========== ADD THIS ENDPOINT HERE (BEFORE if __name__ == "__main__") ==========
@app.route("/api/latest-scan")
def api_latest_scan():
    """Return the latest scan for the kiosk to display and speak — ONE TIME ONLY"""
    global last_rfid_scan

    if last_rfid_scan:
        current_time = int(time.time() * 1000)
        if current_time - last_rfid_scan["id"] < 10000:
            scan = last_rfid_scan
            last_rfid_scan = None  # <-- CONSUME IT: cleared after one read
            return jsonify({"scan": scan})

    # Nothing to show — DO NOT fall back to DB (that causes infinite re-triggering)
    return jsonify({"scan": None})


# ========== MAIN ENTRY POINT ==========
if __name__ == "__main__":
    init_db()
    print("=" * 50)
    print("  MMSU CCIS Parking System")
    print("  http://localhost:5000")
    print("  QR Scanner Kiosk: http://localhost:5000/qr-scanner")
    print("  Visitor QR Codes: VISITOR1, VISITOR2, VISITOR3, VISITOR4, VISITOR5")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
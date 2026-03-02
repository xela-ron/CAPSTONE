"""
MMSU CCIS Parking & Monitoring System
Main Flask Application - User Side
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

app = Flask(__name__)
app.secret_key = "mmsu_ccis_parking_2024_secret"
DB_FILE = "rfid_logs.db"

# ── DB INIT ────────────────────────────────────────────────────────────────────
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
            created_at    TEXT DEFAULT (datetime('now'))
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
            created_at TEXT DEFAULT (datetime('now')),
            created_by TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS violations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no  TEXT,
            description TEXT,
            date        TEXT DEFAULT (datetime('now')),
            recorded_by TEXT,
            status      TEXT DEFAULT 'pending'
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

# ── LANDING PAGE ───────────────────────────────────────────────────────────────
LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MMSU CCIS Parking System</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;height:100vh;overflow:hidden;position:relative}
  .bg{position:absolute;inset:0;background:url('/static/bg.jpg') center/cover no-repeat;filter:brightness(0.45)}
  .overlay{position:absolute;inset:0;background:linear-gradient(135deg,rgba(1,50,32,0.7) 0%,rgba(0,0,0,0.5) 100%)}
  .container{position:relative;z-index:2;height:100vh;display:flex;align-items:center;justify-content:center}
  .card{background:white;border-radius:20px;padding:52px 48px;width:420px;text-align:center;box-shadow:0 32px 80px rgba(0,0,0,0.4)}
  .logo{width:110px;height:110px;border-radius:50%;object-fit:cover;margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,0.15)}
  .title{font-family:'Playfair Display',serif;font-size:1.15rem;color:#1a3a2a;line-height:1.4;margin-bottom:6px}
  .subtitle{font-size:0.8rem;color:#6b7280;margin-bottom:36px;letter-spacing:0.05em;text-transform:uppercase}
  .btn{display:block;width:100%;padding:14px;border-radius:12px;font-size:0.95rem;font-weight:600;cursor:pointer;transition:all 0.2s;text-decoration:none;border:none;margin-bottom:12px}
  .btn-primary{background:#1a5c36;color:white}
  .btn-primary:hover{background:#145028;transform:translateY(-1px);box-shadow:0 8px 24px rgba(26,92,54,0.4)}
  .btn-outline{background:white;color:#1a5c36;border:2px solid #1a5c36}
  .btn-outline:hover{background:#f0faf4;transform:translateY(-1px)}
  .hint{font-size:0.78rem;color:#9ca3af;margin-top:-6px;margin-bottom:12px}
</style>
</head>
<body>
  <div class="bg"></div>
  <div class="overlay"></div>
  <div class="container">
    <div class="card">
      <img src="/static/logo.jpg" class="logo" alt="MMSU Logo">
      <div class="title">Mariano Marcos State University</div>
      <div class="subtitle">CCIS Parking & Monitoring System</div>
      <a href="/login" class="btn btn-primary">Sign In</a>
      <div class="hint">Already have an account?</div>
      <a href="/register" class="btn btn-outline">Register</a>
      <div class="hint">Create an account</div>
    </div>
  </div>
</body>
</html>"""

# ── LOGIN PAGE ─────────────────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign In - MMSU CCIS Parking</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;height:100vh;overflow:hidden;position:relative}
  .bg{position:absolute;inset:0;background:url('/static/bg.jpg') center/cover no-repeat;filter:brightness(0.45)}
  .overlay{position:absolute;inset:0;background:linear-gradient(135deg,rgba(1,50,32,0.7) 0%,rgba(0,0,0,0.5) 100%)}
  .container{position:relative;z-index:2;height:100vh;display:flex;align-items:center;justify-content:center}
  .card{background:white;border-radius:20px;padding:48px 44px;width:420px;box-shadow:0 32px 80px rgba(0,0,0,0.4)}
  .logo-row{text-align:center;margin-bottom:28px}
  .logo{width:80px;height:80px;border-radius:50%;object-fit:cover}
  h2{font-family:'Playfair Display',serif;font-size:1.4rem;color:#1a3a2a;text-align:center;margin-bottom:6px}
  .sub{text-align:center;color:#6b7280;font-size:0.82rem;margin-bottom:28px}
  .field{margin-bottom:16px}
  label{display:block;font-size:0.82rem;font-weight:500;color:#374151;margin-bottom:6px}
  input{width:100%;padding:12px 14px;border:1.5px solid #d1d5db;border-radius:10px;font-size:0.92rem;font-family:'DM Sans',sans-serif;transition:border 0.2s;outline:none}
  input:focus{border-color:#1a5c36}
  .btn{width:100%;padding:14px;background:#1a5c36;color:white;border:none;border-radius:12px;font-size:0.95rem;font-weight:600;cursor:pointer;transition:all 0.2s;margin-top:8px}
  .btn:hover{background:#145028;transform:translateY(-1px);box-shadow:0 8px 24px rgba(26,92,54,0.3)}
  .error{background:#fef2f2;border:1px solid #fecaca;color:#dc2626;padding:10px 14px;border-radius:8px;font-size:0.85rem;margin-bottom:16px}
  .back{text-align:center;margin-top:20px;font-size:0.83rem;color:#6b7280}
  .back a{color:#1a5c36;font-weight:600;text-decoration:none}
</style>
</head>
<body>
  <div class="bg"></div>
  <div class="overlay"></div>
  <div class="container">
    <div class="card">
      <div class="logo-row"><img src="/static/logo.jpg" class="logo" alt="MMSU"></div>
      <h2>Welcome Back</h2>
      <div class="sub">Sign in to your CCIS Parking account</div>
      {% if error %}<div class="error">{{ error }}</div>{% endif %}
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
      <div class="back" style="margin-top:8px"><a href="/">Back to Home</a></div>
    </div>
  </div>
</body>
</html>"""

# ── REGISTER PAGE ──────────────────────────────────────────────────────────────
REGISTER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Register - MMSU CCIS Parking</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;min-height:100vh;position:relative}
  .bg{position:fixed;inset:0;background:url('/static/bg.jpg') center/cover no-repeat;filter:brightness(0.45);z-index:0}
  .overlay{position:fixed;inset:0;background:linear-gradient(135deg,rgba(1,50,32,0.7) 0%,rgba(0,0,0,0.5) 100%);z-index:1}
  .container{position:relative;z-index:2;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px 16px}
  .card{background:white;border-radius:20px;padding:44px;width:100%;max-width:680px;box-shadow:0 32px 80px rgba(0,0,0,0.4)}
  .logo-row{text-align:center;margin-bottom:20px}
  .logo{width:70px;height:70px;border-radius:50%;object-fit:cover}
  h2{font-family:'Playfair Display',serif;font-size:1.5rem;color:#1a3a2a;text-align:center;margin-bottom:4px}
  .sub{text-align:center;color:#6b7280;font-size:0.83rem;margin-bottom:28px}
  .section-title{font-size:0.78rem;font-weight:600;color:#1a5c36;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:14px;padding-bottom:6px;border-bottom:2px solid #dcfce7}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:8px}
  .field{margin-bottom:14px}
  .field.full{grid-column:1/-1}
  label{display:block;font-size:0.82rem;font-weight:500;color:#374151;margin-bottom:5px}
  input,select{width:100%;padding:11px 13px;border:1.5px solid #d1d5db;border-radius:10px;font-size:0.9rem;font-family:'DM Sans',sans-serif;transition:border 0.2s;outline:none;background:white}
  input:focus,select:focus{border-color:#1a5c36}
  .btn{width:100%;padding:14px;background:#1a5c36;color:white;border:none;border-radius:12px;font-size:0.95rem;font-weight:600;cursor:pointer;transition:all 0.2s;margin-top:8px}
  .btn:hover{background:#145028;box-shadow:0 8px 24px rgba(26,92,54,0.3)}
  .error{background:#fef2f2;border:1px solid #fecaca;color:#dc2626;padding:10px 14px;border-radius:8px;font-size:0.85rem;margin-bottom:16px}
  .success{background:#f0fdf4;border:1px solid #bbf7d0;color:#15803d;padding:10px 14px;border-radius:8px;font-size:0.85rem;margin-bottom:16px}
  .back{text-align:center;margin-top:16px;font-size:0.83rem;color:#6b7280}
  .back a{color:#1a5c36;font-weight:600;text-decoration:none}
  .divider{margin:20px 0 16px}
</style>
</head>
<body>
  <div class="bg"></div>
  <div class="overlay"></div>
  <div class="container">
    <div class="card">
      <div class="logo-row"><img src="/static/logo.jpg" class="logo" alt="MMSU"></div>
      <h2>Create Account</h2>
      <div class="sub">Register for MMSU CCIS Parking & Monitoring System</div>
      {% if error %}<div class="error">{{ error }}</div>{% endif %}
      {% if success %}<div class="success">{{ success }}</div>{% endif %}
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
              <option value="Truck">Truck</option>
              <option value="Bicycle">Bicycle</option>
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
    </div>
  </div>
</body>
</html>"""

# ── USER DASHBOARD ─────────────────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard - MMSU CCIS Parking</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;background:#f0f4f0;min-height:100vh}

  /* NAVBAR */
  nav{background:#1a5c36;padding:0 32px;display:flex;align-items:center;justify-content:space-between;height:64px;box-shadow:0 2px 12px rgba(0,0,0,0.15)}
  .nav-left{display:flex;align-items:center;gap:12px}
  .nav-logo{width:40px;height:40px;border-radius:50%;object-fit:cover}
  .nav-title{color:white;font-weight:600;font-size:0.95rem;line-height:1.2}
  .nav-title span{display:block;font-size:0.72rem;font-weight:400;opacity:0.75}
  .nav-right{display:flex;align-items:center;gap:16px}
  .nav-user{color:white;font-size:0.85rem;opacity:0.9}
  .nav-logout{color:white;text-decoration:none;font-size:0.82rem;background:rgba(255,255,255,0.15);padding:6px 14px;border-radius:20px;transition:background 0.2s}
  .nav-logout:hover{background:rgba(255,255,255,0.25)}

  /* LAYOUT */
  .layout{display:flex;min-height:calc(100vh - 64px)}
  
  /* SIDEBAR */
  .sidebar{width:220px;background:#145028;padding:24px 0;flex-shrink:0}
  .sidebar-item{display:flex;align-items:center;gap:10px;padding:12px 24px;color:rgba(255,255,255,0.75);font-size:0.88rem;cursor:pointer;transition:all 0.2s;text-decoration:none}
  .sidebar-item:hover,.sidebar-item.active{background:rgba(255,255,255,0.1);color:white}
  .sidebar-item.active{border-left:3px solid #4ade80}
  .sidebar-icon{font-size:1rem;width:20px;text-align:center}
  .sidebar-divider{height:1px;background:rgba(255,255,255,0.1);margin:12px 16px}

  /* MAIN */
  .main{flex:1;padding:28px 32px;overflow-y:auto}
  .page{display:none}
  .page.active{display:block}

  /* GREETING */
  .greeting{margin-bottom:24px}
  .greeting h1{font-family:'Playfair Display',serif;font-size:1.6rem;color:#1a3a2a}
  .greeting p{color:#6b7280;font-size:0.88rem;margin-top:4px}

  /* CARDS ROW */
  .cards-row{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
  .stat-card{background:white;border-radius:14px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,0.06)}
  .stat-card .icon{font-size:1.6rem;margin-bottom:8px}
  .stat-card .val{font-size:1.8rem;font-weight:700;color:#1a5c36}
  .stat-card .lbl{font-size:0.78rem;color:#6b7280;margin-top:2px}

  /* PROFILE CARD */
  .profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px}
  .info-card{background:white;border-radius:14px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,0.06)}
  .info-card h3{font-size:0.78rem;font-weight:600;color:#1a5c36;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:16px;padding-bottom:8px;border-bottom:2px solid #dcfce7}
  .info-row{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #f3f4f6;font-size:0.87rem}
  .info-row:last-child{border-bottom:none}
  .info-label{color:#6b7280}
  .info-value{font-weight:500;color:#1a3a2a;text-align:right}
  .badge{display:inline-block;padding:3px 12px;border-radius:999px;font-size:0.75rem;font-weight:600}
  .badge-student{background:#dcfce7;color:#15803d}
  .badge-faculty{background:#dbeafe;color:#1d4ed8}
  .badge-staff{background:#fef3c7;color:#b45309}

  /* TABS */
  .tabs{display:flex;gap:0;margin-bottom:20px;background:white;border-radius:12px;padding:6px;box-shadow:0 2px 8px rgba(0,0,0,0.06);width:fit-content}
  .tab{padding:8px 20px;cursor:pointer;font-size:0.87rem;font-weight:500;color:#6b7280;border-radius:8px;transition:all 0.2s}
  .tab.active{background:#1a5c36;color:white}

  /* TABLE */
  .table-card{background:white;border-radius:14px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,0.06)}
  .table-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
  .table-header h3{font-size:0.9rem;font-weight:600;color:#1a3a2a}
  table{width:100%;border-collapse:collapse;font-size:0.85rem}
  th{text-align:left;padding:10px 12px;background:#f9fafb;color:#6b7280;font-weight:600;font-size:0.78rem;text-transform:uppercase;letter-spacing:0.04em;border-bottom:1px solid #e5e7eb}
  td{padding:11px 12px;border-bottom:1px solid #f3f4f6;color:#374151}
  tr:last-child td{border-bottom:none}
  tr:hover td{background:#f9fafb}
  .tag-in{color:#15803d;font-weight:600;font-size:0.78rem;background:#dcfce7;padding:3px 10px;border-radius:999px}
  .tag-out{color:#b45309;font-weight:600;font-size:0.78rem;background:#fef3c7;padding:3px 10px;border-radius:999px}
  .empty{text-align:center;padding:40px;color:#9ca3af;font-size:0.88rem}

  /* QR SECTION */
  .qr-card{background:white;border-radius:14px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,0.06);text-align:center;max-width:400px;margin:0 auto}
  .qr-card h3{font-family:'Playfair Display',serif;color:#1a3a2a;margin-bottom:6px}
  .qr-card p{color:#6b7280;font-size:0.85rem;margin-bottom:24px}
  .qr-img{width:220px;height:220px;border:3px solid #1a5c36;border-radius:12px;padding:8px;margin:0 auto 20px}
  .qr-btn{background:#1a5c36;color:white;border:none;padding:12px 28px;border-radius:10px;font-size:0.9rem;font-weight:600;cursor:pointer;transition:all 0.2s}
  .qr-btn:hover{background:#145028}
  .qr-details{background:#f0fdf4;border-radius:10px;padding:16px;text-align:left;margin-top:16px;font-size:0.83rem}
  .qr-details .qr-row{display:flex;justify-content:space-between;padding:4px 0;color:#374151}
  .qr-details .qr-row span:first-child{color:#6b7280}

  /* NOTICES */
  .notice-card{background:white;border-radius:14px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,0.06);margin-bottom:12px;border-left:4px solid #1a5c36}
  .notice-title{font-weight:600;color:#1a3a2a;margin-bottom:4px}
  .notice-msg{color:#4b5563;font-size:0.87rem}
  .notice-date{color:#9ca3af;font-size:0.78rem;margin-top:6px}

  /* VIOLATIONS */
  .viol-badge{background:#fef2f2;color:#dc2626;padding:3px 10px;border-radius:999px;font-size:0.75rem;font-weight:600}
  .viol-pending{background:#fef3c7;color:#b45309}
</style>
</head>
<body>
<nav>
  <div class="nav-left">
    <img src="/static/logo.jpg" class="nav-logo" alt="MMSU">
    <div class="nav-title">
      MMSU CCIS Parking
      <span>Monitoring System</span>
    </div>
  </div>
  <div class="nav-right">
    <span class="nav-user">Hi, {{ user.full_name.split()[0] if user.full_name else user.student_no }}</span>
    <a href="/logout" class="nav-logout">Sign Out</a>
  </div>
</nav>

<div class="layout">
  <!-- SIDEBAR -->
  <div class="sidebar">
    <a class="sidebar-item active" onclick="showPage('dashboard')" href="#">
      <span class="sidebar-icon">&#9632;</span> Dashboard
    </a>
    <a class="sidebar-item" onclick="showPage('logs')" href="#">
      <span class="sidebar-icon">&#9679;</span> My Logs
    </a>
    <a class="sidebar-item" onclick="showPage('violations')" href="#">
      <span class="sidebar-icon">&#9888;</span> Violations
    </a>
    <a class="sidebar-item" onclick="showPage('qrcode')" href="#">
      <span class="sidebar-icon">&#9641;</span> My QR Code
    </a>
    <div class="sidebar-divider"></div>
    <a class="sidebar-item" onclick="showPage('notices')" href="#">
      <span class="sidebar-icon">&#9993;</span> Notices
    </a>
  </div>

  <!-- MAIN CONTENT -->
  <div class="main">

    <!-- DASHBOARD PAGE -->
    <div class="page active" id="page-dashboard">
      <div class="greeting">
        <h1>Welcome, {{ user.full_name.split()[0] if user.full_name else 'User' }}!</h1>
        <p>Here's your parking activity summary</p>
      </div>

      <div class="cards-row">
        <div class="stat-card">
          <div class="icon">&#128197;</div>
          <div class="val" id="stat-total">—</div>
          <div class="lbl">Total Entries</div>
        </div>
        <div class="stat-card">
          <div class="icon">&#128338;</div>
          <div class="val" id="stat-today">—</div>
          <div class="lbl">Today's Visits</div>
        </div>
        <div class="stat-card">
          <div class="icon">&#9888;</div>
          <div class="val" id="stat-violations">—</div>
          <div class="lbl">Violations</div>
        </div>
        <div class="stat-card">
          <div class="icon">&#128276;</div>
          <div class="val" id="stat-notices">—</div>
          <div class="lbl">New Notices</div>
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
            {% if user.tag_id %}<span style="font-family:monospace;font-size:0.78rem;color:#1a5c36">{{ user.tag_id[:16] }}...</span>
            {% else %}<span style="color:#f59e0b">Not assigned yet</span>{% endif %}
          </span></div>
        </div>
      </div>

      <!-- Recent Logs Preview -->
      <div class="table-card">
        <div class="table-header">
          <h3>Recent Activity</h3>
          <a href="#" onclick="showPage('logs')" style="font-size:0.82rem;color:#1a5c36;text-decoration:none">View all</a>
        </div>
        <table>
          <thead><tr><th>Date</th><th>Time In</th><th>Time Out</th><th>Status</th></tr></thead>
          <tbody id="recent-logs"></tbody>
        </table>
      </div>
    </div>

    <!-- LOGS PAGE -->
    <div class="page" id="page-logs">
      <div class="greeting">
        <h1>My Access Logs</h1>
        <p>Your complete vehicle entry and exit history</p>
      </div>
      <div class="tabs">
        <div class="tab active" onclick="switchTab(this,'logs')">All Logs</div>
        <div class="tab" onclick="switchTab(this,'history')">Vehicle History</div>
      </div>
      <div class="table-card">
        <div class="table-header">
          <h3>Access Records</h3>
          <input type="text" id="log-search" placeholder="Search..." oninput="filterLogs()" style="padding:6px 12px;border:1.5px solid #d1d5db;border-radius:8px;font-size:0.83rem;outline:none;width:180px">
        </div>
        <table>
          <thead><tr><th>#</th><th>Date</th><th>Time</th><th>Type</th><th>RSSI</th></tr></thead>
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
          <thead><tr><th>Date</th><th>Description</th><th>Status</th></tr></thead>
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
        <p>Present this QR code to the guard for vehicle entry</p>
        <img id="qr-image" class="qr-img" src="" alt="QR Code">
        <br>
        <button class="qr-btn" onclick="downloadQR()">Download QR Code</button>
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
        <p>Important announcements from administration</p>
      </div>
      <div id="notices-list"></div>
    </div>

  </div>
</div>

<script>
  let allLogs = [];

  function showPage(name) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.sidebar-item').forEach(s => s.classList.remove('active'));
    document.getElementById('page-' + name).classList.add('active');
    event.target.closest('.sidebar-item').classList.add('active');
    if (name === 'logs') fetchLogs();
    if (name === 'qrcode') loadQR();
    if (name === 'violations') fetchViolations();
    if (name === 'notices') fetchNotices();
  }

  function switchTab(el, tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    el.classList.add('active');
  }

  // Stats
  async function fetchStats() {
    const res  = await fetch('/api/user/stats');
    const data = await res.json();
    document.getElementById('stat-total').textContent      = data.total;
    document.getElementById('stat-today').textContent      = data.today;
    document.getElementById('stat-violations').textContent = data.violations;
    document.getElementById('stat-notices').textContent    = data.notices;
  }

  // Recent logs
  async function fetchRecentLogs() {
    const res  = await fetch('/api/user/logs?limit=5');
    const data = await res.json();
    const tbody = document.getElementById('recent-logs');
    if (!data.logs.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">No activity yet</td></tr>';
      return;
    }
    tbody.innerHTML = data.logs.map(r => {
      const dt = r.scan_time ? r.scan_time.split(' ') : ['—','—'];
      return `<tr>
        <td>${dt[0]}</td>
        <td>${dt[1]||'—'}</td>
        <td>—</td>
        <td><span class="tag-in">Entry</span></td>
      </tr>`;
    }).join('');
  }

  // All logs
  async function fetchLogs() {
    const res  = await fetch('/api/user/logs?limit=200');
    const data = await res.json();
    allLogs = data.logs;
    renderLogs(allLogs);
  }

  function renderLogs(logs) {
    const tbody = document.getElementById('logs-table');
    if (!logs.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No logs found</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map((r,i) => {
      const dt = r.scan_time ? r.scan_time.split(' ') : ['—','—'];
      return `<tr>
        <td>${i+1}</td>
        <td>${dt[0]}</td>
        <td>${dt[1]||'—'}</td>
        <td><span class="tag-in">Entry</span></td>
        <td style="color:#f59e0b;font-size:0.8rem">${r.rssi||'—'}</td>
      </tr>`;
    }).join('');
  }

  function filterLogs() {
    const q = document.getElementById('log-search').value.toLowerCase();
    renderLogs(allLogs.filter(r => r.scan_time.toLowerCase().includes(q)));
  }

  // Violations
  async function fetchViolations() {
    const res  = await fetch('/api/user/violations');
    const data = await res.json();
    const tbody = document.getElementById('violations-table');
    if (!data.violations.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty">No violations recorded</td></tr>';
      return;
    }
    tbody.innerHTML = data.violations.map(v => `<tr>
      <td>${v.date}</td>
      <td>${v.description}</td>
      <td><span class="viol-badge viol-${v.status}">${v.status}</span></td>
    </tr>`).join('');
  }

  // QR Code
  async function loadQR() {
    const res  = await fetch('/api/user/qr');
    const data = await res.json();
    document.getElementById('qr-image').src = 'data:image/png;base64,' + data.qr;
  }

  function downloadQR() {
    const img = document.getElementById('qr-image');
    const a   = document.createElement('a');
    a.href     = img.src;
    a.download = 'my_qrcode.png';
    a.click();
  }

  // Notices
  async function fetchNotices() {
    const res  = await fetch('/api/user/notices');
    const data = await res.json();
    const div  = document.getElementById('notices-list');
    if (!data.notices.length) {
      div.innerHTML = '<div class="empty" style="background:white;border-radius:14px;padding:40px">No notices yet</div>';
      return;
    }
    div.innerHTML = data.notices.map(n => `
      <div class="notice-card">
        <div class="notice-title">${n.title}</div>
        <div class="notice-msg">${n.message}</div>
        <div class="notice-date">${n.created_at}</div>
      </div>`).join('');
  }

  // Init
  fetchStats();
  fetchRecentLogs();
  setInterval(fetchStats, 30000);
</script>
</body>
</html>"""

# ── ROUTES ─────────────────────────────────────────────────────────────────────
@app.route("/")
def landing():
    if 'user_id' in session:
        if session.get('is_admin'):
            return redirect('/admin')
        return redirect('/dashboard')
    return LANDING_HTML

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        student_no = request.form.get("student_no","").strip()
        password   = request.form.get("password","")
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE student_no=? AND password_hash=?",
            (student_no, hash_password(password))
        ).fetchone()
        conn.close()
        if user:
            session['user_id']    = user['id']
            session['student_no'] = user['student_no']
            session['is_admin']   = bool(user['is_admin'])
            if user['is_admin']:
                return redirect('/admin')
            return redirect('/dashboard')
        return render_template_string(LOGIN_HTML, error="Invalid ID number or password.")
    return render_template_string(LOGIN_HTML, error=None)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        f = request.form
        if f.get("password") != f.get("confirm_password"):
            return render_template_string(REGISTER_HTML, error="Passwords do not match.", success=None)
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO users (student_no, password_hash, full_name, college, department,
                    email, position, vehicle_model, vehicle_color, vehicle_type)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                f.get("student_no","").strip(),
                hash_password(f.get("password","")),
                f.get("full_name","").strip(),
                f.get("college","").strip(),
                f.get("department","").strip(),
                f.get("email","").strip(),
                f.get("position","Student"),
                f.get("vehicle_model","").strip(),
                f.get("vehicle_color","").strip(),
                f.get("vehicle_type","").strip()
            ))
            conn.commit()
            conn.close()
            return render_template_string(REGISTER_HTML, error=None,
                success="Account created! You can now sign in.")
        except sqlite3.IntegrityError:
            conn.close()
            return render_template_string(REGISTER_HTML,
                error="ID number already registered.", success=None)
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

# ── USER API ROUTES ────────────────────────────────────────────────────────────
@app.route("/api/user/stats")
@login_required
def api_user_stats():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    today = datetime.now().strftime("%Y-%m-%d")
    total = 0; today_c = 0
    if user['tag_id']:
        total   = conn.execute("SELECT COUNT(*) FROM rfid_scans WHERE tag_id=?", (user['tag_id'],)).fetchone()[0]
        today_c = conn.execute("SELECT COUNT(*) FROM rfid_scans WHERE tag_id=? AND scan_time LIKE ?",
                               (user['tag_id'], f"{today}%")).fetchone()[0]
    viols   = conn.execute("SELECT COUNT(*) FROM violations WHERE student_no=?", (user['student_no'],)).fetchone()[0]
    notices = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    conn.close()
    return jsonify({"total": total, "today": today_c, "violations": viols, "notices": notices})

@app.route("/api/user/logs")
@login_required
def api_user_logs():
    limit = request.args.get("limit", 100, type=int)
    conn  = get_db()
    user  = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    logs  = []
    if user['tag_id']:
        rows = conn.execute(
            "SELECT * FROM rfid_scans WHERE tag_id=? ORDER BY id DESC LIMIT ?",
            (user['tag_id'], limit)
        ).fetchall()
        logs = [dict(r) for r in rows]
    conn.close()
    return jsonify({"logs": logs})

@app.route("/api/user/violations")
@login_required
def api_user_violations():
    conn  = get_db()
    user  = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    rows  = conn.execute(
        "SELECT * FROM violations WHERE student_no=? ORDER BY date DESC",
        (user['student_no'],)
    ).fetchall()
    conn.close()
    return jsonify({"violations": [dict(r) for r in rows]})

@app.route("/api/user/notices")
@login_required
def api_user_notices():
    conn  = get_db()
    rows  = conn.execute("SELECT * FROM notices ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify({"notices": [dict(r) for r in rows]})

@app.route("/api/user/qr")
@login_required
def api_user_qr():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    conn.close()
    qr_data = json.dumps({
        "student_no":   user['student_no'],
        "name":         user['full_name'],
        "position":     user['position'],
        "college":      user['college'],
        "department":   user['department'],
        "vehicle_type": user['vehicle_type'],
        "vehicle_model":user['vehicle_model'],
        "tag_id":       user['tag_id']
    })
    qr_img = qrcode.make(qr_data)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    qr_b64 = base64.b64encode(buf.read()).decode()
    return jsonify({"qr": qr_b64})

# Admin redirect
@app.route("/admin")
@admin_required
def admin():
    return redirect("http://127.0.0.1:5001")

# Static files
@app.route("/static/<path:filename>")
def static_files(filename):
    return send_file(f"static/{filename}")

if __name__ == "__main__":
    init_db()
    print("Starting MMSU CCIS Parking System at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)

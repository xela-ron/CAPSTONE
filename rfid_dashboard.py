"""
RFID Web Dashboard - QB0A M-Series
Student/Employee Vehicle Tracking System
Visit http://localhost:5001
"""

from flask import Flask, jsonify, render_template_string, request, send_file
import sqlite3
import io
import csv
import qrcode
import base64
from datetime import datetime
import pytz
import time

PH_TZ = pytz.timezone("Asia/Manila")

def ph_now():
    return datetime.now(PH_TZ).strftime("%Y-%m-%d %H:%M:%S")

app = Flask(__name__)
DB_FILE = "rfid_logs.db"
last_rfid_scan = None

# ============================================================
#  DATABASE FUNCTIONS
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)

    # rfid_scans table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rfid_scans (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_id    TEXT NOT NULL,
            scan_time TEXT NOT NULL,
            rssi      TEXT,
            antenna   TEXT,
            scan_type TEXT DEFAULT 'rfid'
        )
    """)

    # tag_registry table
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

    # users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no   TEXT UNIQUE NOT NULL,
            full_name    TEXT,
            position     TEXT DEFAULT 'Student',
            college      TEXT,
            department   TEXT,
            vehicle_type TEXT,
            tag_id       TEXT,
            is_admin     INTEGER DEFAULT 0,
            created_at   TEXT
        )
    """)

    # violations table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS violations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no  TEXT,
            description TEXT,
            date        TEXT,
            status      TEXT DEFAULT 'Pending'
        )
    """)

    # parking_slots table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parking_slots (
            slot_type TEXT PRIMARY KEY,
            capacity  INTEGER,
            occupied  INTEGER DEFAULT 0
        )
    """)

    # qr_scans table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS qr_scans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no TEXT NOT NULL,
            scan_time  TEXT NOT NULL,
            method     TEXT DEFAULT 'qr'
        )
    """)

    # visitors table with fixed QR codes
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

    # visitor_scans table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS visitor_scans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id  TEXT NOT NULL,
            scan_time   TEXT NOT NULL,
            scan_type   TEXT DEFAULT 'entry'
        )
    """)

    # Insert default parking slots
    for slot_type, cap in [('faculty_car',31), ('faculty_moto',15), ('student_car',14), ('student_moto',15)]:
        conn.execute("""
            INSERT OR IGNORE INTO parking_slots (slot_type, capacity, occupied) VALUES (?,?,0)
        """, (slot_type, cap))

    # Add missing columns safely
    for col in ["rssi", "antenna", "scan_type"]:
        try:
            conn.execute(f"ALTER TABLE rfid_scans ADD COLUMN {col} TEXT")
        except:
            pass

    # Create 5 fixed visitor QR codes
    for i in range(1, 6):
        visitor_id = f"VISITOR{i}"
        existing = conn.execute("SELECT * FROM visitors WHERE visitor_id=?", (visitor_id,)).fetchone()
        if not existing:
            try:
                import qrcode, io, base64
                qr_img = qrcode.make(visitor_id)
                buf = io.BytesIO()
                qr_img.save(buf, format="PNG")
                qr_b64 = base64.b64encode(buf.getvalue()).decode()
            except:
                qr_b64 = ""
            conn.execute("""
                        INSERT INTO visitors (visitor_id, name, qr_code, created_at, is_active)
                        VALUES (?, ?, ?, ?, 1)
                    """, (visitor_id, f"Visitor {i}", qr_b64, ph_now()))

    conn.commit()
    conn.close()

# ============================================================
#  DASHBOARD HTML TEMPLATE
# ============================================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MMSU CCIS — Parking Admin Dashboard</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', sans-serif; background: #f0f4f8; color: #0a1628; min-height: 100vh; }
    header { background: linear-gradient(135deg, #0a1628 0%, #1b2a4a 100%); padding: 0 32px; display: flex; align-items: center; justify-content: space-between; height: 70px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); border-bottom: 2px solid #f4a261; }
    .header-left { display: flex; align-items: center; gap: 16px; }
    .header-logo { width: 45px; height: 45px; border-radius: 50%; overflow: hidden; border: 2px solid #f4a261; }
    .header-logo img { width: 100%; height: 100%; object-fit: cover; }
    header h1 { font-size: 1.1rem; color: white; font-weight: 600; letter-spacing: -0.01em; line-height: 1.3; }
    header h1 span { display: block; font-size: 0.72rem; font-weight: 400; opacity: 0.8; color: #00b4d8; margin-top: 2px; }
    .header-right { display: flex; align-items: center; gap: 16px; }
    .live-badge { background: #00b4d8; color: #0a1628; border-radius: 30px; padding: 6px 16px; font-size: 0.78rem; font-weight: 700; letter-spacing: 0.05em; animation: pulse 2s infinite; box-shadow: 0 0 15px rgba(0,180,216,0.3); }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
    .clock-badge { background: rgba(255,255,255,0.08); color: #f4a261; border-radius: 30px; padding: 6px 16px; font-size: 0.85rem; font-weight: 600; border: 1px solid rgba(244,162,97,0.3); }
    .header-mmsu { width: 40px; height: 40px; border-radius: 50%; overflow: hidden; border: 2px solid #f4a261; }
    .header-mmsu img { width: 100%; height: 100%; object-fit: cover; }
    .tabs { display: flex; align-items: center; padding: 0 32px; background: white; border-bottom: 1px solid rgba(0,180,216,0.15); box-shadow: 0 2px 8px rgba(0,0,0,0.04); flex-wrap: wrap; }
    .tab { padding: 16px 24px; cursor: pointer; font-weight: 600; font-size: 0.88rem; color: #5a6a7a; border-bottom: 3px solid transparent; margin-bottom: -1px; transition: all 0.2s; user-select: none; }
    .tab.active { color: #00b4d8; border-bottom-color: #f4a261; }
    .tab:hover { color: #0a1628; background: rgba(0,180,216,0.05); }
    .page { display: none; padding: 28px 32px; }
    .page.active { display: block; }
    .stats { display: flex; gap: 18px; margin-bottom: 28px; flex-wrap: wrap; }
    .stat-card { background: white; border-radius: 18px; padding: 22px 26px; flex: 1; min-width: 140px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.04); border: 1px solid rgba(0,180,216,0.1); transition: transform 0.2s; }
    .stat-card:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,180,216,0.1); }
    .stat-card .value { font-size: 2.2rem; font-weight: 700; color: #0a1628; }
    .stat-card .label { font-size: 0.75rem; color: #6a7a8a; margin-top: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
    .controls { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 18px; }
    input[type=text], select { background: white; border: 2px solid #e0e8f0; color: #0a1628; padding: 10px 16px; border-radius: 12px; font-size: 0.88rem; font-family: 'Inter', sans-serif; outline: none; transition: border 0.2s; }
    input[type=text]:focus, select:focus { border-color: #00b4d8; box-shadow: 0 0 0 3px rgba(0,180,216,0.1); }
    input[type=text] { width: 260px; }
    button { background: linear-gradient(135deg, #0a1628 0%, #1b2a4a 100%); color: white; border: none; padding: 10px 20px; border-radius: 12px; cursor: pointer; font-size: 0.88rem; font-weight: 600; font-family: 'Inter', sans-serif; transition: all 0.3s; border: 1px solid rgba(0,180,216,0.3); box-shadow: 0 4px 12px rgba(10,22,40,0.15); }
    button:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(0,180,216,0.25); border-color: #00b4d8; }
    button.green { background: #00b4d8; color: #0a1628; border: none; }
    button.green:hover { background: #0096b0; box-shadow: 0 8px 20px rgba(0,180,216,0.4); }
    button.red { background: #dc2626; border-color: rgba(220,38,38,0.3); }
    button.red:hover { background: #b91c1c; border-color: #dc2626; box-shadow: 0 8px 20px rgba(220,38,38,0.2); }
    button.orange { background: #f4a261; color: #0a1628; border: none; }
    button.orange:hover { background: #d4882a; box-shadow: 0 8px 20px rgba(244,162,97,0.3); }
    .table-wrap { background: white; border-radius: 18px; overflow-x: auto; box-shadow: 0 4px 15px rgba(0,0,0,0.04); border: 1px solid rgba(0,180,216,0.1); }
    table { width: 100%; border-collapse: collapse; min-width: 600px; }
    thead th { background: #f0f4f8; padding: 13px 14px; text-align: left; font-size: 0.75rem; color: #0a1628; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 700; border-bottom: 2px solid rgba(0,180,216,0.2); }
    tbody tr { border-bottom: 1px solid #eef2f6; transition: background 0.15s; }
    tbody tr:last-child { border-bottom: none; }
    tbody tr:hover { background: rgba(0,180,216,0.03); }
    td { padding: 12px 14px; font-size: 0.87rem; color: #2a3a4a; }
    td.tag { font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', monospace; color: #00b4d8; font-weight: 600; font-size: 0.78rem; }
    td.time { color: #6a7a8a; font-size: 0.82rem; }
    td.name { font-weight: 600; color: #0a1628; }
    .badge-pos { display: inline-block; padding: 4px 12px; border-radius: 30px; font-size: 0.73rem; font-weight: 700; }
    .pos-student { background: rgba(0,180,216,0.12); color: #0088a0; }
    .pos-faculty { background: rgba(244,162,97,0.15); color: #d4882a; }
    .pos-staff   { background: rgba(244,162,97,0.1); color: #c47a1a; }
    .pos-visitor { background: rgba(0,180,216,0.08); color: #0096b0; }
    .parking-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 18px; margin-bottom: 24px; }
    .park-card { background: white; border-radius: 18px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.04); border: 1px solid rgba(0,180,216,0.1); text-align: center; transition: transform 0.2s; }
    .park-card:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,180,216,0.1); }
    #scan-alert { display: none; position: fixed; top: 24px; right: 24px; z-index: 500; background: white; border: 2px solid #00b4d8; border-radius: 18px; padding: 20px 26px; min-width: 320px; box-shadow: 0 16px 40px rgba(0,0,0,0.15); animation: slidein 0.3s ease; border-left: 5px solid #f4a261; }
    @keyframes slidein { from{transform:translateX(120%)} to{transform:translateX(0)} }
    .qr-code-img { width: 80px; height: 80px; cursor: pointer; border: 2px solid #00b4d8; border-radius: 10px; padding: 5px; background: white; }
    .qr-code-img:hover { transform: scale(1.05); transition: 0.2s; }
    .visitor-status { display: inline-block; padding: 3px 10px; border-radius: 30px; font-size: 0.7rem; font-weight: 600; }
    .visitor-qr-img { width: 70px; height: 70px; cursor: pointer; border: 2px solid #00b4d8; border-radius: 8px; padding: 4px; background: white; transition: transform 0.2s; }
    .visitor-qr-img:hover { transform: scale(1.1); }
    .status-active { background: rgba(0,180,216,0.12); color: #0088a0; }
    .status-inactive { background: rgba(220,38,38,0.12); color: #dc2626; }
    .print-card { background: white; border-radius: 16px; padding: 20px; text-align: center; margin-bottom: 20px; border: 1px solid #e0e8f0; }
  </style>
</head>
<body>

<div id="scan-alert">
  <div class="alert-tag-label">📶 Visitor Detected</div>
  <div class="alert-name" id="alert-name">—</div>
  <div class="alert-details" id="alert-details">—</div>
  <div class="alert-tagid" id="alert-tag">—</div>
</div>

<header>
  <div class="header-left">
    <div class="header-logo">
      <img src="/static/logo.jpg" alt="MMSU">
    </div>
    <h1>MMSU CCIS Parking System
      <span>Admin Dashboard</span>
    </h1>
  </div>
  <div class="header-right">
    <span class="clock-badge" id="ph-clock">--:-- -- PHT</span>
    <span class="live-badge">● LIVE</span>
  </div>
</header>

<div class="tabs">
  <div class="tab active" onclick="showTab('scans')">Live Scans</div>
  <div class="tab" onclick="showTab('tags')">Registered Tags</div>
  <div class="tab" onclick="showTab('users')">Users</div>
  <div class="tab" onclick="showTab('violations')">Violations</div>
  <div class="tab" onclick="showTab('visitors')">👥 Visitor QR Codes</div>
  <a href="/qr-scanner" target="_blank" class="tab-link" style="margin-left: auto; background: linear-gradient(135deg, #00b4d8 0%, #0096b0 100%); color: #0a1628; padding: 10px 22px; border-radius: 12px; text-decoration: none; font-size: 0.85rem; font-weight: 600; transition: all 0.3s;">
    📷 QR Scanner
  </a>
</div>

<div class="page active" id="page-scans">
  <div class="stats">
    <div class="stat-card"><div class="value" id="total-scans">-</div><div class="label">Total Scans</div></div>
    <div class="stat-card"><div class="value" id="unique-tags">-</div><div class="label">Unique Tags</div></div>
    <div class="stat-card"><div class="value" id="today-scans">-</div><div class="label">Today's Scans</div></div>
    <div class="stat-card"><div class="value" id="registered-count">-</div><div class="label">Registered Tags</div></div>
  </div>

  <div class="parking-grid">
    <div class="park-card" id="adm-faculty_car" style="border-top: 4px solid #00b4d8;">
      <div style="font-size:1.8rem;margin-bottom:8px">🚗</div>
      <div style="font-size:0.72rem;color:#6a7a8a;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px">Faculty / PWD Cars</div>
      <div style="font-size:2rem;font-weight:700;color:#00b4d8"><span id="adm-faculty_car-avail">—</span><span style="font-size:1rem;color:#8a9aaa">/31</span></div>
      <div style="background:#e0e8f0;border-radius:30px;height:6px;margin-top:12px;overflow:hidden">
        <div id="adm-faculty_car-bar" style="height:100%;border-radius:30px;background:#00b4d8;width:100%;transition:width 0.4s"></div>
      </div>
    </div>
    <div class="park-card" id="adm-faculty_moto" style="border-top: 4px solid #00b4d8;">
      <div style="font-size:1.8rem;margin-bottom:8px">🏍️</div>
      <div style="font-size:0.72rem;color:#6a7a8a;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px">Faculty Motorcycles</div>
      <div style="font-size:2rem;font-weight:700;color:#00b4d8"><span id="adm-faculty_moto-avail">—</span><span style="font-size:1rem;color:#8a9aaa">/15</span></div>
      <div style="background:#e0e8f0;border-radius:30px;height:6px;margin-top:12px;overflow:hidden">
        <div id="adm-faculty_moto-bar" style="height:100%;border-radius:30px;background:#00b4d8;width:100%;transition:width 0.4s"></div>
      </div>
    </div>
    <div class="park-card" id="adm-student_car" style="border-top: 4px solid #f4a261;">
      <div style="font-size:1.8rem;margin-bottom:8px">🚗</div>
      <div style="font-size:0.72rem;color:#6a7a8a;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px">Student Cars</div>
      <div style="font-size:2rem;font-weight:700;color:#f4a261"><span id="adm-student_car-avail">—</span><span style="font-size:1rem;color:#8a9aaa">/14</span></div>
      <div style="background:#e0e8f0;border-radius:30px;height:6px;margin-top:12px;overflow:hidden">
        <div id="adm-student_car-bar" style="height:100%;border-radius:30px;background:#f4a261;width:100%;transition:width 0.4s"></div>
      </div>
    </div>
    <div class="park-card" id="adm-student_moto" style="border-top: 4px solid #f4a261;">
      <div style="font-size:1.8rem;margin-bottom:8px">🏍️</div>
      <div style="font-size:0.72rem;color:#6a7a8a;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px">Student Motorcycles</div>
      <div style="font-size:2rem;font-weight:700;color:#f4a261"><span id="adm-student_moto-avail">—</span><span style="font-size:1rem;color:#8a9aaa">/15</span></div>
      <div style="background:#e0e8f0;border-radius:30px;height:6px;margin-top:12px;overflow:hidden">
        <div id="adm-student_moto-bar" style="height:100%;border-radius:30px;background:#f4a261;width:100%;transition:width 0.4s"></div>
      </div>
    </div>
  </div>

  <div style="margin-bottom:20px;display:flex;align-items:center;gap:12px">
    <button onclick="resetParking()" style="background:#6a7a8a;font-size:0.82rem;padding:8px 16px">↻ Reset Parking Counters</button>
    <span style="font-size:0.78rem;color:#8a9aaa">Reset at the start of each day</span>
  </div>

  <div class="controls">
    <input type="text" id="search-scan" placeholder="🔍 Search name or tag..." oninput="filterScans()">
    <button class="green" onclick="exportCSV()">⬇ Export CSV</button>
    <button onclick="fetchScans()" style="background:#5a6a7a">↻ Refresh</button>
    <button class="red" onclick="clearConfirm()">🗑 Clear All</button>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>#</th><th>Name</th><th>Student No.</th><th>Department</th>
        <th>Course</th><th>Vehicle</th><th>Position</th>
        <th>Date (PHT)</th><th>Time (PHT)</th><th>Type</th><th>RSSI</th><th>Tag ID</th>
      </tr></thead>
      <tbody id="scan-table"></tbody>
    </table>
  </div>
  <div id="status-bar">🕐 Auto-refreshes every 3 seconds &nbsp;|&nbsp; PH Time: <span id="ph-clock-bar">—</span></div>
</div>

<div class="page" id="page-tags">
  <div class="controls">
    <input type="text" id="search-tag" placeholder="🔍 Search tags..." oninput="filterTags()">
    <button class="green" onclick="openRegisterModal()">+ Register New Tag</button>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Tag ID</th><th>Name</th><th>Student No.</th><th>Department</th>
        <th>Course</th><th>Vehicle</th><th>Position</th><th>Actions</th>
      </tr></thead>
      <tbody id="tag-table"></tbody>
    </table>
  </div>
</div>

<div class="page" id="page-users">
  <div class="controls">
    <input type="text" id="search-user" placeholder="🔍 Search users..." oninput="filterUsers()" style="width:280px">
  </div>
  <div class="table-wrap">
    <tr>
      <thead><tr>
        <th>Student No.</th><th>Full Name</th><th>Position</th><th>College</th>
        <th>Vehicle</th><th>RFID Tag</th><th>Registered</th><th>Actions</th>
      </tr></thead>
      <tbody id="users-table"></tbody>
    </table>
  </div>
</div>

<div class="page" id="page-violations">
  <div class="controls">
    <input type="text" id="search-viol" placeholder="🔍 Search violations..." oninput="filterViolations()" style="width:280px">
    <button class="green" onclick="openAddViolation()">+ Add Violation</button>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>#</th><th>Student No.</th><th>Full Name</th>
        <th>Violation</th><th>Date</th><th>Status</th><th>Actions</th>
      </tr></thead>
      <tbody id="violations-table"></tbody>
    </table>
  </div>
</div>

<!-- VISITORS PAGE -->
<div class="page" id="page-visitors">
  <div class="print-card">
    <h4>📋 Visitor QR Codes - Print & Laminate</h4>
    <p style="font-size:0.85rem; color:#6a7a8a; margin-bottom:15px;">
      These are fixed visitor IDs. Print them, laminate, and hand to visitors when they arrive.
    </p>
    <button onclick="printAllVisitorQR()" style="background:linear-gradient(135deg,#0a1628,#1b2a4a);color:white;border:none;padding:10px 22px;border-radius:12px;font-size:0.85rem;font-weight:600;cursor:pointer;border:1px solid rgba(0,180,216,0.3)">🖨️ Print All QR Codes</button>
  </div>
  
  <div class="controls">
    <input type="text" id="search-visitor" placeholder="🔍 Search visitors..." oninput="filterVisitors()" style="width:280px">
    <button class="orange" onclick="fetchVisitors()">↻ Refresh</button>
  </div>
  
  <div class="stats" style="margin-bottom: 20px;">
    <div class="stat-card"><div class="value" id="total-visitors">-</div><div class="label">Total Visitors</div></div>
    <div class="stat-card"><div class="value" id="today-visits">-</div><div class="label">Today's Visits</div></div>
  </div>
  
<div class="table-wrap">
    <table>
      <thead><tr>
        <th>QR Code</th><th>Visitor ID</th><th>Name</th>
        <th>Status</th><th>Created</th><th>Actions</th>
      </tr></thead>
      <tbody id="visitors-table"></tbody>
    </table>
  </div>
</div>

<div class="modal-bg" id="modal-bg" style="display: none;">
  <div class="modal">
    <h2 id="modal-title">Register <span>New Tag</span></h2>
    <input type="hidden" id="modal-tag-id-original">
    <div class="form-row"><label>Tag ID (EPC)</label><input type="text" id="f-tag-id" placeholder="e.g. 0102030405060708090A0B0C"></div>
    <div class="form-row"><label>Full Name</label><input type="text" id="f-name" placeholder="e.g. Juan Dela Cruz"></div>
    <div class="form-row"><label>Student / Employee Number</label><input type="text" id="f-student-no" placeholder="e.g. 2021-00123"></div>
    <div class="form-row"><label>Department</label><input type="text" id="f-department" placeholder="e.g. College of Engineering"></div>
    <div class="form-row"><label>Course</label><input type="text" id="f-course" placeholder="e.g. BS Computer Engineering"></div>
    <div class="form-row"><label>Vehicle Type</label><input type="text" id="f-vehicle" placeholder="e.g. Motorcycle, Car, SUV"></div>
    <div class="form-row"><label>Position</label>
      <select id="f-position">
        <option value="Student">Student</option>
        <option value="Faculty">Faculty</option>
        <option value="Staff">Staff</option>
        <option value="Visitor">Visitor</option>
      </select>
    </div>
    <div class="modal-actions">
      <button class="red" onclick="closeModal()">Cancel</button>
      <button class="green" onclick="saveTag()">Save</button>
    </div>
  </div>
</div>

<div class="modal-bg" id="assign-modal-bg" style="display: none;">
  <div class="modal">
    <h2>Assign <span>RFID Tag</span></h2>
    <input type="hidden" id="assign-student-no">
    <div class="form-row"><label>User</label><input type="text" id="assign-user-name" readonly style="opacity:0.7;cursor:not-allowed;background:#f0f4f8;"></div>
    <div class="form-row"><label>Tag ID (EPC)</label><input type="text" id="assign-tag-id" placeholder="e.g. 0102030405060708090A0004" style="font-family:monospace"></div>
    <div class="modal-actions"><button class="red" onclick="closeAssignModal()">Cancel</button><button class="green" onclick="saveAssignTag()">Assign Tag</button></div>
  </div>
</div>

<div class="modal-bg" id="viol-modal-bg" style="display: none;">
  <div class="modal">
    <h2>Add <span>Violation</span></h2>
    <div class="form-row"><label>Student / Employee Number</label><input type="text" id="viol-student-no" placeholder="e.g. 22-021049"></div>
    <div class="form-row"><label>Violation Description</label><input type="text" id="viol-desc" placeholder="e.g. No parking sticker"></div>
    <div class="form-row"><label>Status</label><select id="viol-status"><option value="Pending">Pending</option><option value="Resolved">Resolved</option></select></div>
    <div class="modal-actions"><button class="red" onclick="closeViolModal()">Cancel</button><button class="green" onclick="saveViolation()">Save</button></div>
  </div>
</div>

<script>
let allScans = [], allTags = [], allUsers = [], allViolations = [], allVisitors = [], lastScanId = 0;

function showTab(tab) {
  const tabs = ['scans', 'tags', 'users', 'violations', 'visitors'];
  document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', tabs[i] === tab));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + tab).classList.add('active');
  if (tab === 'tags') fetchTags();
  if (tab === 'users') fetchUsers();
  if (tab === 'violations') fetchViolations();
  if (tab === 'visitors') fetchVisitors();
}

function posBadge(pos) {
  const m = {Student:'pos-student', Faculty:'pos-faculty', Staff:'pos-staff', Visitor:'pos-visitor'};
  return `<span class="badge-pos ${m[pos]||'pos-default'}">${pos||'—'}</span>`;
}

function showAlert(scan) {
  if (!scan.name && !scan.visitor_id) return;
  document.getElementById('alert-name').textContent = scan.name || scan.visitor_id || 'Visitor';
  document.getElementById('alert-details').textContent = `${scan.position||'Visitor'} | ${scan.department||''}`;
  document.getElementById('alert-tag').textContent = scan.tag_id || scan.visitor_id;
  const el = document.getElementById('scan-alert');
  el.style.display = 'block';
  clearTimeout(window._at);
  window._at = setTimeout(() => el.style.display = 'none', 4000);
}

async function fetchScans() {
  const r = await fetch('/api/scans?limit=200');
  const d = await r.json();
  allScans = d.scans;
  renderScans(allScans);
  if (d.scans.length > 0 && d.scans[0].id > lastScanId) {
    lastScanId = d.scans[0].id;
    showAlert(d.scans[0]);
  }
}

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

function renderScans(rows) {
  document.getElementById('scan-table').innerHTML = rows.map((r, i) => {
    const dt = r.scan_time ? r.scan_time.split(' ') : ['—','—'];
    const isExit = (r.scan_type||'').toLowerCase().includes('exit');
    const badge = isExit ? '<span style="background:rgba(244,162,97,0.15);color:#d4882a;padding:3px 12px;border-radius:30px;font-size:0.75rem;font-weight:700">Exit</span>' : '<span style="background:rgba(0,180,216,0.12);color:#0088a0;padding:3px 12px;border-radius:30px;font-size:0.75rem;font-weight:700">Entry</span>';
    return `<tr>
      <td>${i+1}</td>
      <td class="name">${r.name || r.visitor_id || '<span style="color:#8a9aaa">Unregistered</span>'}</td>
      <td>${r.student_no||'—'}</td>
      <td>${r.department||'—'}</td>
      <td>${r.course||'—'}</td>
      <td>${r.vehicle_type||'—'}</td>
      <td>${posBadge(r.position)}</td>
      <td class="time">${dt[0]||'—'}</td>
      <td class="time">${to12hr(dt[1])}</td>
      <td>${badge}</td>
      <td class="rssi">${r.rssi||'—'}</td>
      <td class="tag">${r.tag_id||r.visitor_id||'—'}</td>
    </tr>`;
  }).join('');
}

function filterScans() {
  const q = document.getElementById('search-scan').value.toLowerCase();
  renderScans(allScans.filter(r => (r.tag_id||'').toLowerCase().includes(q) || (r.name||'').toLowerCase().includes(q) || (r.student_no||'').toLowerCase().includes(q)));
}

async function fetchStats() {
  const r = await fetch('/api/stats');
  const d = await r.json();
  document.getElementById('total-scans').textContent = d.total;
  document.getElementById('unique-tags').textContent = d.unique;
  document.getElementById('today-scans').textContent = d.today;
  document.getElementById('registered-count').textContent = d.registered;
}

async function fetchTags() {
  const r = await fetch('/api/tags');
  const d = await r.json();
  allTags = d.tags;
  renderTags(allTags);
}

function renderTags(rows) {
  document.getElementById('tag-table').innerHTML = rows.map(r => `<tr><td class="tag">${r.tag_id}</td><td class="name">${r.name||'—'}</td><td class="student-no">${r.student_no||'—'}</td><td class="department">${r.department||'—'}</td><td class="course">${r.course||'—'}</td><td class="vehicle">${r.vehicle_type||'—'}<td>${posBadge(r.position)}</td><td class="actions"><button class="orange" style="padding:4px 12px;font-size:0.8rem" onclick='editTag(${JSON.stringify(r)})'>Edit</button><button class="red" style="padding:4px 12px;font-size:0.8rem;margin-left:4px" onclick="deleteTag('${r.tag_id}')">Delete</button></td></tr>`).join('');
}

function filterTags() {
  const q = document.getElementById('search-tag').value.toLowerCase();
  renderTags(allTags.filter(r => (r.tag_id||'').toLowerCase().includes(q) || (r.name||'').toLowerCase().includes(q)));
}

function openRegisterModal() {
  document.getElementById('modal-title').innerHTML = 'Register <span>New Tag</span>';
  ['f-tag-id','f-name','f-student-no','f-department','f-course','f-vehicle'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('f-position').value = 'Student';
  document.getElementById('modal-tag-id-original').value = '';
  document.getElementById('modal-bg').style.display = 'flex';
}

function editTag(r) {
  document.getElementById('modal-title').innerHTML = 'Edit <span>Tag</span>';
  document.getElementById('f-tag-id').value = r.tag_id;
  document.getElementById('f-name').value = r.name||'';
  document.getElementById('f-student-no').value = r.student_no||'';
  document.getElementById('f-department').value = r.department||'';
  document.getElementById('f-course').value = r.course||'';
  document.getElementById('f-vehicle').value = r.vehicle_type||'';
  document.getElementById('f-position').value = r.position||'Student';
  document.getElementById('modal-tag-id-original').value = r.tag_id;
  document.getElementById('modal-bg').style.display = 'flex';
}

function closeModal() { document.getElementById('modal-bg').style.display = 'none'; }

async function saveTag() {
  const p = { tag_id: document.getElementById('f-tag-id').value.trim().toUpperCase(), name: document.getElementById('f-name').value.trim(), student_no: document.getElementById('f-student-no').value.trim(), department: document.getElementById('f-department').value.trim(), course: document.getElementById('f-course').value.trim(), vehicle_type: document.getElementById('f-vehicle').value.trim(), position: document.getElementById('f-position').value, original_tag_id: document.getElementById('modal-tag-id-original').value.trim() };
  if (!p.tag_id) { alert('Tag ID is required!'); return; }
  await fetch('/api/tags/save', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(p) });
  closeModal();
  fetchTags();
  fetchStats();
}

async function deleteTag(tagId) {
  if (!confirm('Delete this tag registration?')) return;
  await fetch('/api/tags/delete', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({tag_id: tagId}) });
  fetchTags();
  fetchStats();
}

function exportCSV() { window.location.href = '/api/export/csv'; }
function clearConfirm() { if (confirm('Delete ALL scan records?')) { fetch('/api/clear', {method:'POST'}).then(() => { fetchScans(); fetchStats(); }); } }

async function fetchAdminParking() {
  try {
    const r = await fetch('/api/parking/slots');
    const d = await r.json();
    for (const [type, slot] of Object.entries(d)) {
      const a = document.getElementById('adm-' + type + '-avail');
      const b = document.getElementById('adm-' + type + '-bar');
      const c = document.getElementById('adm-' + type);
      if (!a) continue;
      const col = slot.status === 'ok' ? (type.startsWith('faculty') ? '#00b4d8' : '#f4a261') : slot.status === 'warning' ? '#f4a261' : '#dc2626';
      a.textContent = slot.available;
      a.style.color = col;
      b.style.width = (slot.available / slot.capacity * 100) + '%';
      b.style.background = col;
      if (c) c.style.borderTopColor = col;
    }
  } catch(e) {}
}

async function resetParking() {
  if (!confirm('Reset all parking counters?')) return;
  try { await fetch('/api/parking/reset', {method:'POST'}); fetchAdminParking(); alert('Parking counters reset!'); } catch(e) { alert('Cannot connect to app server'); }
}

async function fetchUsers() {
  const r = await fetch('/api/admin/users');
  const d = await r.json();
  allUsers = d.users;
  renderUsers(allUsers);
}

function renderUsers(rows) {
  const tb = document.getElementById('users-table');
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:40px;color:#8a9aaa">No users yet</td></tr>'; return; }
  tb.innerHTML = rows.map(r => `<tr>
      <td style="font-family:monospace;font-size:0.85rem">${r.student_no}</td>
      <td style="font-weight:600">${r.full_name||'—'}</td>
      <td>${posBadge(r.position)}</td>
      <td>${r.college||'—'}</td>
      <td>${r.vehicle_type||'—'}</td>
      <td style="font-family:monospace;font-size:0.75rem;color:${r.tag_id ? '#00b4d8' : '#f4a261'}">${r.tag_id ? r.tag_id.substring(0,16)+'...' : 'Not assigned'}</td>
      <td style="font-size:0.8rem;color:#8a9aaa">${r.created_at ? r.created_at.split(' ')[0] : '—'}</td>
      <td><button class="orange" style="padding:4px 10px;font-size:0.8rem" onclick="openAssignModal('${r.student_no}','${(r.full_name||'').replace(/'/g,"\\'")}','${r.tag_id||''}')">${r.tag_id ? 'Re-assign' : 'Assign Tag'}</button>${r.tag_id ? `<button class="red" style="padding:4px 10px;font-size:0.8rem;margin-left:4px" onclick="removeTag('${r.student_no}')">Remove</button>` : ''}<button class="red" style="padding:4px 10px;font-size:0.8rem;margin-left:4px;background:#991b1b" onclick="deleteUser('${r.student_no}','${(r.full_name||'').replace(/'/g,"\\'")}')">Delete</button></td>
    </tr>`).join('');
}

function filterUsers() {
  const q = document.getElementById('search-user').value.toLowerCase();
  renderUsers(allUsers.filter(r => (r.student_no||'').toLowerCase().includes(q) || (r.full_name||'').toLowerCase().includes(q)));
}

function openAssignModal(sno, name, tag) {
  document.getElementById('assign-student-no').value = sno;
  document.getElementById('assign-user-name').value = name + ' (' + sno + ')';
  document.getElementById('assign-tag-id').value = tag || '';
  document.getElementById('assign-modal-bg').style.display = 'flex';
}
function closeAssignModal() { document.getElementById('assign-modal-bg').style.display = 'none'; }
async function saveAssignTag() {
  const sno = document.getElementById('assign-student-no').value;
  const tid = document.getElementById('assign-tag-id').value.trim().toUpperCase();
  if (!tid) { alert('Enter Tag ID'); return; }
  const r = await fetch('/api/admin/assign_tag', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({student_no: sno, tag_id: tid}) });
  const d = await r.json();
  if (d.status === 'ok') { closeAssignModal(); fetchUsers(); alert('Tag assigned!'); }
  else alert('Error: ' + d.message);
}
async function removeTag(sno) { if (!confirm('Remove RFID tag from this user?')) return; await fetch('/api/admin/assign_tag', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({student_no: sno, tag_id: ''}) }); fetchUsers(); }
async function deleteUser(sno, name) { if (!confirm('DELETE user ' + name + '?')) return; await fetch('/api/admin/users/delete', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({student_no: sno}) }); fetchUsers(); alert('Deleted.'); }

async function fetchViolations() {
  const r = await fetch('/api/admin/violations');
  const d = await r.json();
  allViolations = d.violations;
  renderViolations(allViolations);
}
function renderViolations(rows) {
  const tb = document.getElementById('violations-table');
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:#8a9aaa">No violations recorded</td></tr>'; return; }
  tb.innerHTML = rows.map((v,i) => `<tr id="vrow-${v.id}">
      <td>${i+1}</td>
      <td style="font-family:monospace;font-size:0.85rem">${v.student_no}</td>
      <td style="font-weight:600">${v.full_name||'—'}</td>
      <td id="vtext-${v.id}">${v.description||v.violation||'—'}</td>
      <td style="color:#8a9aaa;font-size:0.82rem">${v.date ? v.date + ' (PHT)' : '—'}</td>
      <td><select id="vstatus-${v.id}" onchange="updateViolationStatus(${v.id},this.value)" style="background:${v.status==='Resolved'?'#00b4d8':'#f4a261'};color:#0a1628;border:none;border-radius:30px;padding:3px 10px;font-size:0.78rem;font-weight:600;cursor:pointer"><option value="Pending" ${v.status==='Pending' ?'selected':''}>Pending</option><option value="Resolved" ${v.status==='Resolved'?'selected':''}>Resolved</option></select></td>
      <td><button class="orange" style="padding:3px 10px;font-size:0.78rem" onclick="editViolationText(${v.id},'${(v.description||v.violation||'').replace(/'/g,"\\'")}')">Edit</button><button class="red" style="padding:3px 10px;font-size:0.78rem;margin-left:4px" onclick="deleteViolation(${v.id})">Delete</button></td>
    </tr>`).join('');
}
async function updateViolationStatus(id, status) { await fetch('/api/admin/violations/update', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id, status}) }); fetchViolations(); }
function editViolationText(id, current) { const newText = prompt('Edit violation description:', current); if (!newText || !newText.trim()) return; fetch('/api/admin/violations/update', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id, description: newText.trim()}) }).then(() => fetchViolations()); }
function filterViolations() { const q = document.getElementById('search-viol').value.toLowerCase(); renderViolations(allViolations.filter(v => (v.student_no||'').toLowerCase().includes(q) || (v.full_name||'').toLowerCase().includes(q) || (v.description||v.violation||'').toLowerCase().includes(q))); }
function openAddViolation() { document.getElementById('viol-student-no').value = ''; document.getElementById('viol-desc').value = ''; document.getElementById('viol-status').value = 'Pending'; document.getElementById('viol-modal-bg').style.display = 'flex'; }
function closeViolModal() { document.getElementById('viol-modal-bg').style.display = 'none'; }
async function saveViolation() { const sno = document.getElementById('viol-student-no').value.trim(); const v = document.getElementById('viol-desc').value.trim(); const s = document.getElementById('viol-status').value; if (!sno || !v) { alert('Fill in all fields'); return; } await fetch('/api/admin/violations/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({student_no: sno, description: v, status: s}) }); closeViolModal(); fetchViolations(); }
async function deleteViolation(id) { if (!confirm('Delete violation?')) return; await fetch('/api/admin/violations/delete', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id}) }); fetchViolations(); }

// ============ VISITOR FUNCTIONS ============
async function fetchVisitors() {
  const r = await fetch('/api/visitors');
  const d = await r.json();
  allVisitors = d.visitors;
  renderVisitors(allVisitors);
  document.getElementById('total-visitors').textContent = d.total || 0;
  document.getElementById('today-visits').textContent = d.today_visits || 0;
}

function renderVisitors(rows) {
  const tb = document.getElementById('visitors-table');
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:40px;color:#8a9aaa">No visitors found</td></tr>'; return; }
  tb.innerHTML = rows.map(v => `<tr>
      <td>${v.qr_code ? `<img src="data:image/png;base64,${v.qr_code}" class="visitor-qr-img" onclick="downloadVisitorQR('${v.visitor_id}','${v.qr_code}')" title="Click to download">` : '<span style="color:#8a9aaa;font-size:0.75rem">No QR</span>'}</td>
      <td><strong>${v.visitor_id}</strong></td>
      <td>${v.name || 'Visitor'}</td>
      <td><span class="visitor-status ${v.is_active == 1 ? 'status-active' : 'status-inactive'}">${v.is_active == 1 ? 'Active' : 'Inactive'}</span></td>
      <td class="time">${v.created_at ? v.created_at.split(' ')[0] : '—'}</td>
      <td>
        ${v.qr_code ? `<button class="green" style="padding:4px 10px;font-size:0.78rem;margin-bottom:4px;display:block" onclick="downloadVisitorQR('${v.visitor_id}','${v.qr_code}')">📥 Download</button>` : ''}
        <button class="green" style="padding:4px 10px;font-size:0.78rem" onclick="toggleVisitorStatus('${v.visitor_id}', ${v.is_active})">${v.is_active == 1 ? 'Deactivate' : 'Activate'}</button>
      </td>
    </tr>`).join('');
}

function downloadVisitorQR(visitorId, qrBase64) {
  const a = document.createElement('a');
  a.href = 'data:image/png;base64,' + qrBase64;
  a.download = visitorId + '_qrcode.png';
  a.click();
}

async function printAllVisitorQR() {
  const r = await fetch('/api/visitors');
  const d = await r.json();
  const visitors = d.visitors || [];
  const printWindow = window.open('', '_blank');
  printWindow.document.write(`<html><head><title>MMSU CCIS Parking - Visitor QR Codes</title>
    <style>
      body { font-family: Arial, sans-serif; padding: 20px; }
      .qr-container { display: flex; flex-wrap: wrap; justify-content: center; gap: 30px; }
      .qr-card { text-align: center; border: 2px solid #00b4d8; border-radius: 12px; padding: 18px; width: 200px; page-break-inside: avoid; }
      .qr-card img { width: 160px; height: 160px; }
      .qr-card h4 { margin: 10px 0 5px; font-size: 1rem; }
      .qr-card p { margin: 3px 0; color: #666; font-size: 12px; }
      @media print { .qr-card { page-break-inside: avoid; } }
    </style></head><body>
    <h2 style="text-align:center">MMSU CCIS Parking — Visitor QR Codes</h2>
    <p style="text-align:center; color:#666; margin-bottom:24px">Print and laminate for visitors</p>
    <div class="qr-container">`);
  visitors.forEach(v => {
    if (v.qr_code) {
      printWindow.document.write(`<div class="qr-card">
        <img src="data:image/png;base64,${v.qr_code}" alt="${v.visitor_id}">
        <h4>${v.visitor_id}</h4>
        <p>${v.name || 'Visitor'}</p>
        <p style="font-size:10px;color:#00b4d8">Scan at gate for entry/exit</p>
      </div>`);
    }
  });
  printWindow.document.write('</div></body></html>');
  printWindow.document.close();
  printWindow.print();
}

function updatePHClock() {
  const now = new Date();
  const ph = new Date(now.toLocaleString('en-US', {timeZone:'Asia/Manila'}));
  const pad = n => String(n).padStart(2,'0');
  const h = ph.getHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  const hr12 = h % 12 || 12;
  const timeStr = `${hr12}:${pad(ph.getMinutes())}:${pad(ph.getSeconds())} ${ampm} PHT`;
  const el1 = document.getElementById('ph-clock');
  const el2 = document.getElementById('ph-clock-bar');
  if (el1) el1.textContent = timeStr;
  if (el2) el2.textContent = timeStr;
}
updatePHClock();
setInterval(updatePHClock, 1000);

async function refresh() {
  try { await fetchStats(); } catch(e) {}
  try { await fetchScans(); } catch(e) {}
  try { await fetchAdminParking(); } catch(e) {}
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""

# ============================================================
#  QR SCANNER HTML (KEPT SIMPLE FOR VISITORS)
# ============================================================
QR_SCANNER_HTML = """<!DOCTYPE html>
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
  .topbar-logo{width:42px;height:42px;border-radius:50%;object-fit:cover;border:2px solid #f4a261}
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
  .cam-overlay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
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
  .slot-bar{background:rgba(255,255,255,0.03);border:1px solid rgba(0,180,216,0.1);border-radius:14px;padding:14px 18px;display:flex;justify-content:space-between;align-items:center}
  .slot-bar .sl{font-size:0.8rem;color:#8a9aaa}
  .slot-bar .sv{font-size:1rem;font-weight:700;color:#00b4d8}
  .slot-bar .sv.full{color:#f4a261}
  .scan-ts{text-align:center;font-size:0.72rem;color:#6a7a8a;margin-top:12px}
  .countdown{position:absolute;bottom:16px;right:20px;font-size:0.72rem;color:#6a7a8a}
  .recent-ticker{position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.4);padding:10px 24px;display:flex;align-items:center;gap:12px;font-size:0.75rem;color:#8a9aaa;border-top:1px solid rgba(244,162,97,0.15)}
  .ticker-label{color:#00b4d8;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;flex-shrink:0}
  .ticker-item{color:#b8c8d8}
  .ticker-entry{color:#00b4d8}
  .ticker-exit{color:#f4a261}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-left">
    <img src="/static/logo.jpg" class="topbar-logo" alt="MMSU">
    <div class="topbar-title">
      MMSU CCIS Parking Gate
      <span>Scan QR Code or present RFID tag</span>
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
    </div>
    <div class="cam-instruction">
      <strong>Place QR Code inside the frame</strong>
      Or present your RFID tag to the reader
    </div>
    <div class="cam-status">
      <div class="dot pulse" id="status-dot"></div>
      <span id="status-text">Initializing camera...</span>
    </div>
  </div>

  <div class="result-side idle" id="result-side">
    <div class="idle-state" id="idle-state">
      <div class="idle-icon">🏢</div>
      <div class="idle-title">Ready to Scan</div>
      <div class="idle-sub">Show your QR code or tap your RFID tag</div>
    </div>

    <div class="scan-result" id="scan-result" style="position:relative">
      <div class="welcome-msg">
        <span class="welcome-emoji" id="res-emoji">✅</span>
        <div class="welcome-text green" id="res-welcome">Welcome to CCIS!</div>
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
          <div class="detail-item"><div class="dl">College/Dept</div><div class="dv" id="res-college">—</div></div>
          <div class="detail-item"><div class="dl">Vehicle</div><div class="dv" id="res-vehicle">—</div></div>
          <div class="detail-item"><div class="dl">Purpose</div><div class="dv" id="res-dept">—</div></div>
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
      <span id="ticker-content" class="ticker-item">Waiting for scans...</span>
    </div>
  </div>
</div>

<script>
  (function() {
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    const statusText = document.getElementById('status-text');
    const statusDot = document.getElementById('status-dot');

    let stream = null;
    let scanning = false;
    let lastQR = '';
    let lastQRTime = 0;
    let resetTimer = null;
    let countdownInterval = null;
    let lastRFIDScanId = 0;

    function updateClock() {
      const now = new Date();
      const ph = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Manila' }));
      const pad = n => String(n).padStart(2, '0');
      const h = ph.getHours();
      const ampm = h >= 12 ? 'PM' : 'AM';
      const hr12 = h % 12 || 12;
      document.getElementById('clock').textContent = `${hr12}:${pad(ph.getMinutes())}:${pad(ph.getSeconds())} ${ampm} PHT`;
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
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'environment' }
        });
        video.srcObject = stream;
        video.addEventListener('loadedmetadata', () => {
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          statusDot.className = 'dot pulse';
          statusText.textContent = 'Camera ready';
          startScanning();
        });
      } catch (err) {
        statusDot.className = 'dot err';
        statusText.textContent = 'Camera error: ' + err.message;
      }
    }

    function startScanning() {
      if (scanning) return;
      scanning = true;
      scanLoop();
    }

    function scanLoop() {
      if (!scanning) return;
      if (video.readyState === video.HAVE_ENOUGH_DATA) {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        let code = jsQR(imageData.data, imageData.width, imageData.height, { inversionAttempts: 'attemptBoth' });
        if (code) {
          handleQRCode(code.data);
        }
      }
      requestAnimationFrame(scanLoop);
    }

    function handleQRCode(qrData) {
      const now = Date.now();
      if (qrData === lastQR && now - lastQRTime < 3000) return;
      lastQR = qrData;
      lastQRTime = now;
      statusText.textContent = 'QR detected! Processing...';

      fetch('/api/qr/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ qr_data: qrData })
      })
      .then(res => res.json())
      .then(data => {
        showResult(data);
      })
      .catch(err => {
        statusText.textContent = 'Server error. Try again.';
        statusDot.className = 'dot err';
        setTimeout(() => { statusDot.className = 'dot pulse'; statusText.textContent = 'Camera ready'; }, 2000);
      });
    }

    function showResult(data) {
      clearTimeout(resetTimer);
      clearInterval(countdownInterval);
      document.getElementById('idle-state').style.display = 'none';
      document.getElementById('scan-result').style.display = 'block';
      const side = document.getElementById('result-side');

      if (data.status === 'not_found') {
        side.className = 'result-side denied';
        document.getElementById('res-emoji').textContent = '❌';
        document.getElementById('res-welcome').textContent = 'Access Denied';
        document.getElementById('res-welcome').className = 'welcome-text red';
        document.getElementById('res-sub').textContent = 'QR Code not registered';
        document.getElementById('res-name').textContent = 'Unknown';
        document.getElementById('res-id').textContent = '—';
        document.getElementById('res-avatar').textContent = '?';
        document.getElementById('res-slot-val').textContent = '—';
        speak('Access denied. This QR code is not registered.');
        startCountdown(5);
        return;
      }

      const u = data.user;
      const isExit = data.scan_type === 'exit';
      const firstName = (u.full_name || u.name || u.visitor_id || '').split(' ')[0] || 'Visitor';
      const initials = (u.full_name || u.name || 'V').split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();

      document.getElementById('res-avatar').textContent = initials;
      document.getElementById('res-name').textContent = u.full_name || u.name || u.visitor_id || 'Visitor';
      document.getElementById('res-id').textContent = u.student_no || u.visitor_id || '—';
      document.getElementById('res-position').textContent = u.position || 'Visitor';
      document.getElementById('res-college').textContent = u.department || u.college || '—';
      document.getElementById('res-vehicle').textContent = u.vehicle_type || 'Car';
      document.getElementById('res-dept').textContent = u.purpose || '—';
      document.getElementById('res-time').textContent = (isExit ? 'Exit' : 'Entry') + ' logged at ' + data.scan_time + ' (PHT)';

      if (isExit) {
        side.className = 'result-side exit-ok';
        document.getElementById('res-emoji').textContent = '👋';
        document.getElementById('res-welcome').textContent = `Thank you, ${firstName}!`;
        document.getElementById('res-welcome').className = 'welcome-text blue';
        document.getElementById('res-sub').textContent = 'Drive safe! See you next time.';
        document.getElementById('res-slot-label').textContent = 'Slot Released';
        document.getElementById('res-slot-val').textContent = data.slot ? data.slot.label : '—';
        speak(`Thank you, ${firstName}! Drive safe.`);
      } else {
        if (data.slot && data.slot.status === 'full') {
          side.className = 'result-side full';
          document.getElementById('res-emoji').textContent = '⚠️';
          document.getElementById('res-welcome').textContent = 'Parking Full!';
          document.getElementById('res-welcome').className = 'welcome-text orange';
          document.getElementById('res-sub').textContent = 'No available slots for your vehicle type';
          document.getElementById('res-slot-label').textContent = data.slot.label;
          document.getElementById('res-slot-val').textContent = 'FULL';
          speak(`Welcome ${firstName}. However, the parking area is currently full.`);
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
      }
      startCountdown(8);
    }

    function startCountdown(secs) {
      let t = secs;
      document.getElementById('countdown').textContent = 'Resetting in ' + t + 's...';
      countdownInterval = setInterval(() => {
        t--;
        document.getElementById('countdown').textContent = t > 0 ? 'Resetting in ' + t + 's...' : '';
        if (t <= 0) clearInterval(countdownInterval);
      }, 1000);
      resetTimer = setTimeout(() => {
        document.getElementById('idle-state').style.display = 'block';
        document.getElementById('scan-result').style.display = 'none';
        document.getElementById('result-side').className = 'result-side idle';
        statusText.textContent = 'Camera ready';
      }, secs * 1000);
    }

    async function pollRFID() {
      try {
        const res = await fetch('/api/latest-scan');
        const data = await res.json();
        if (data.scan && data.scan.id !== lastRFIDScanId) {
          lastRFIDScanId = data.scan.id;
          showResult({
            status: 'ok',
            scan_type: data.scan.scan_type,
            scan_time: data.scan.scan_time,
            user: {
              full_name: data.scan.name || data.scan.tag_id,
              student_no: data.scan.student_no || data.scan.tag_id,
              position: data.scan.position || 'Visitor',
              department: data.scan.department || '—',
              vehicle_type: data.scan.vehicle_type || 'Car',
              purpose: data.scan.purpose || '—'
            },
            slot: data.scan.slot || null
          });
        }
      } catch (e) {}
    }

    startCamera();
    setInterval(pollRFID, 2000);
  })();
</script>
</body>
</html>"""

# ============================================================
#  ROUTES
# ============================================================
@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/scans")
def api_scans():
    limit = request.args.get("limit", 200, type=int)
    conn  = get_db()
    rows  = conn.execute("""
        SELECT s.id, s.tag_id, s.scan_time, s.rssi, s.antenna, s.scan_type,
               COALESCE(t.name, u.full_name, v.name, s.tag_id) AS name,
               COALESCE(t.student_no, u.student_no, v.visitor_id) AS student_no,
               COALESCE(t.department, u.department, v.name) AS department,
               COALESCE(t.course, u.college) AS course,
               COALESCE(t.vehicle_type, u.vehicle_type, 'Car') AS vehicle_type,
               COALESCE(t.position, u.position, 'Visitor') AS position,
               v.visitor_id
        FROM rfid_scans s
        LEFT JOIN tag_registry t ON s.tag_id = t.tag_id
        LEFT JOIN users u ON s.tag_id = u.student_no OR s.tag_id = u.tag_id
        LEFT JOIN visitors v ON s.tag_id = v.visitor_id
        ORDER BY s.id DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return jsonify({"scans": [dict(r) for r in rows]})

@app.route("/api/stats")
def api_stats():
    today = datetime.now(PH_TZ).strftime("%Y-%m-%d")
    conn  = get_db()
    total      = conn.execute("SELECT COUNT(*) FROM rfid_scans").fetchone()[0]
    unique     = conn.execute("SELECT COUNT(DISTINCT tag_id) FROM rfid_scans").fetchone()[0]
    today_c    = conn.execute("SELECT COUNT(*) FROM rfid_scans WHERE scan_time LIKE ?", (f"{today}%",)).fetchone()[0]
    registered = conn.execute("SELECT COUNT(*) FROM tag_registry").fetchone()[0]
    conn.close()
    return jsonify({"total": total, "unique": unique, "today": today_c, "registered": registered})

@app.route("/api/tags")
def api_tags():
    conn = get_db()
    rows = conn.execute("SELECT * FROM tag_registry ORDER BY name").fetchall()
    conn.close()
    return jsonify({"tags": [dict(r) for r in rows]})

@app.route("/api/tags/save", methods=["POST"])
def api_tags_save():
    d    = request.json
    conn = sqlite3.connect(DB_FILE, timeout=30)
    original = d.get("original_tag_id", "").strip()
    if original and original != d["tag_id"]:
        conn.execute("DELETE FROM tag_registry WHERE tag_id=?", (original,))
    conn.execute("""
        INSERT INTO tag_registry (tag_id, name, student_no, department, course, vehicle_type, position)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(tag_id) DO UPDATE SET
            name=excluded.name, student_no=excluded.student_no,
            department=excluded.department, course=excluded.course,
            vehicle_type=excluded.vehicle_type, position=excluded.position
    """, (d["tag_id"], d.get("name"), d.get("student_no"), d.get("department"),
          d.get("course"), d.get("vehicle_type"), d.get("position")))
    conn.commit()
    conn.close()
    return jsonify({"status": "saved"})

@app.route("/api/tags/delete", methods=["POST"])
def api_tags_delete():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("DELETE FROM tag_registry WHERE tag_id=?", (request.json["tag_id"],))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

@app.route("/api/export/csv")
def api_export_csv():
    conn = get_db()
    rows = conn.execute("""
        SELECT s.id, s.tag_id, s.scan_time, s.rssi, s.scan_type,
               COALESCE(t.name, u.full_name, v.name, s.tag_id) AS name,
               COALESCE(t.student_no, u.student_no, v.visitor_id) AS student_no,
               COALESCE(t.department, u.department, v.name) AS department,
               COALESCE(t.course, u.college) AS course,
               COALESCE(t.vehicle_type, u.vehicle_type, 'Car') AS vehicle_type,
               COALESCE(t.position, u.position, 'Visitor') AS position
        FROM rfid_scans s
        LEFT JOIN tag_registry t ON s.tag_id = t.tag_id
        LEFT JOIN users u ON s.tag_id = u.student_no OR s.tag_id = u.tag_id
        LEFT JOIN visitors v ON s.tag_id = v.visitor_id
        ORDER BY s.scan_time DESC
    """).fetchall()
    conn.close()

    def to_ph_time(raw):
        if not raw: return "—", "—"
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            dt_ph = PH_TZ.localize(dt)
            return dt_ph.strftime("%Y-%m-%d"), dt_ph.strftime("%I:%M:%S %p")
        except:
            return raw, "—"

    output = io.StringIO()
    writer = csv.writer(output)
    export_time = datetime.now(PH_TZ).strftime("%Y-%m-%d %H:%M:%S")
    writer.writerow([f"MMSU CCIS Parking System — Scan Log Export"])
    writer.writerow([f"Exported: {export_time} (Philippine Time, UTC+8)"])
    writer.writerow([])
    writer.writerow(["#", "Tag ID", "Date (PH)", "Time (PH)", "Name",
                     "Student/Visitor No.", "Department/Purpose", "Course",
                     "Vehicle Type", "Position", "Scan Type"])
    for i, r in enumerate(rows, 1):
        date_ph, time_ph = to_ph_time(r["scan_time"])
        writer.writerow([
            i, r["tag_id"], date_ph, time_ph,
            r["name"] or "Unregistered",
            r["student_no"] or "—",
            r["department"] or "—",
            r["course"] or "—",
            r["vehicle_type"] or "—",
            r["position"] or "—",
            r["scan_type"] or "rfid",
        ])
    output.seek(0)
    filename = f"scan_log_{datetime.now(PH_TZ).strftime('%Y%m%d_%H%M%S')}_PHT.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )

@app.route("/api/clear", methods=["POST"])
def api_clear():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("DELETE FROM rfid_scans")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='rfid_scans'")
    conn.commit()
    conn.close()
    return jsonify({"status": "cleared"})

@app.route("/api/parking/slots")
def api_parking_slots():
    conn = get_db()
    rows = conn.execute("SELECT slot_type, capacity, occupied FROM parking_slots").fetchall()
    conn.close()
    result = {}
    for r in rows:
        available = r["capacity"] - r["occupied"]
        pct = available / r["capacity"] if r["capacity"] else 1
        status = "full" if available <= 0 else "warning" if pct < 0.2 else "ok"
        result[r["slot_type"]] = {
            "capacity": r["capacity"],
            "occupied": r["occupied"],
            "available": max(available, 0),
            "status": status
        }
    return jsonify(result)

@app.route("/api/parking/exit", methods=["POST"])
def api_parking_exit():
    d          = request.json
    student_no = d.get("student_no", "")
    conn       = get_db()
    user       = conn.execute("SELECT * FROM users WHERE student_no=?", (student_no,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"status": "error", "message": "User not found"})
    position     = (user["position"] or "Student").lower()
    vehicle_type = (user["vehicle_type"] or "").lower()
    is_moto      = vehicle_type in ["motorcycle", "motor", "bike"]
    slot_type    = ("faculty" if position in ["faculty","staff","admin"] else "student") + ("_moto" if is_moto else "_car")
    conn.execute("UPDATE parking_slots SET occupied = MAX(occupied-1, 0) WHERE slot_type=?", (slot_type,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "slot_type": slot_type})

@app.route("/api/parking/reset", methods=["POST"])
def api_parking_reset():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("UPDATE parking_slots SET occupied=0")
    conn.commit()
    conn.close()
    return jsonify({"status": "reset"})

@app.route("/api/parking/update", methods=["POST"])
def api_parking_update():
    student_no = request.json.get("student_no", "")
    conn = get_db()
    user = conn.execute("SELECT vehicle_type, position FROM users WHERE student_no=?", (student_no,)).fetchone()
    conn.close()
    if not user:
        return jsonify({"status": "unknown"})
    vtype    = (user["vehicle_type"] or "").lower()
    position = (user["position"] or "").lower()
    vkey     = "car" if any(x in vtype for x in ["car","suv","truck","van"]) else "moto"
    slot_type = ("faculty" if any(x in position for x in ["faculty","staff","pwd"]) else "student") + f"_{vkey}"
    conn2 = sqlite3.connect(DB_FILE, timeout=30)
    conn2.row_factory = sqlite3.Row
    slot = conn2.execute("SELECT capacity, occupied FROM parking_slots WHERE slot_type=?", (slot_type,)).fetchone()
    if slot and slot["occupied"] < slot["capacity"]:
        conn2.execute("UPDATE parking_slots SET occupied=occupied+1 WHERE slot_type=?", (slot_type,))
        conn2.commit()
        status = "ok"
    else:
        status = "full"
    conn2.close()
    return jsonify({"status": status, "slot_type": slot_type})

@app.route("/api/admin/users")
def api_admin_users():
    conn = get_db()
    rows = conn.execute("""
        SELECT id, student_no, full_name, position, college, vehicle_type, tag_id, created_at
        FROM users WHERE is_admin=0 ORDER BY full_name
    """).fetchall()
    conn.close()
    return jsonify({"users": [dict(r) for r in rows]})

@app.route("/api/admin/violations")
def api_admin_get_violations():
    conn = get_db()
    rows = conn.execute("""
        SELECT v.*, u.full_name FROM violations v
        LEFT JOIN users u ON v.student_no = u.student_no
        ORDER BY v.date DESC
    """).fetchall()
    conn.close()
    return jsonify({"violations": [dict(r) for r in rows]})

@app.route("/api/admin/violations/add", methods=["POST"])
def api_admin_add_violation():
    d    = request.json
    date = datetime.now(PH_TZ).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("""
        INSERT INTO violations (student_no, description, date, status)
        VALUES (?,?,?,?)
    """, (d.get("student_no"), d.get("description"), date, d.get("status", "Pending")))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/admin/violations/delete", methods=["POST"])
def api_admin_delete_violation():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("DELETE FROM violations WHERE id=?", (request.json.get("id"),))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/admin/violations/update", methods=["POST"])
def api_admin_update_violation():
    d    = request.json
    vid  = d.get("id")
    conn = sqlite3.connect(DB_FILE, timeout=30)
    if "status" in d:
        conn.execute("UPDATE violations SET status=? WHERE id=?", (d["status"], vid))
    if "description" in d:
        conn.execute("UPDATE violations SET description=? WHERE id=?", (d["description"], vid))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/admin/users/delete", methods=["POST"])
def api_admin_delete_user():
    student_no = request.json.get("student_no", "")
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("DELETE FROM users WHERE student_no=?", (student_no,))
    conn.execute("DELETE FROM tag_registry WHERE student_no=?", (student_no,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/admin/assign_tag", methods=["POST"])
def api_admin_assign_tag():
    d          = request.json
    student_no = d.get("student_no", "").strip()
    tag_id     = d.get("tag_id", "").strip().upper()
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE users SET tag_id=? WHERE student_no=?",
                     (tag_id if tag_id else None, student_no))
        if tag_id:
            row = conn.execute("SELECT * FROM users WHERE student_no=?", (student_no,)).fetchone()
            if row:
                conn.execute("""
                    INSERT INTO tag_registry (tag_id, name, student_no, department, course, vehicle_type, position)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(tag_id) DO UPDATE SET
                        name=excluded.name, student_no=excluded.student_no,
                        department=excluded.department,
                        vehicle_type=excluded.vehicle_type,
                        position=excluded.position
                """, (tag_id, row["full_name"], row["student_no"],
                      row["department"], "", row["vehicle_type"], row["position"]))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ============ VISITOR ENDPOINTS ============
@app.route("/api/visitors")
def api_get_visitors():
    conn = get_db()
    rows = conn.execute("SELECT * FROM visitors ORDER BY visitor_id").fetchall()
    total = conn.execute("SELECT COUNT(*) FROM visitors").fetchone()[0]
    today = datetime.now(PH_TZ).strftime("%Y-%m-%d")
    today_visits = conn.execute("SELECT COUNT(*) FROM visitor_scans WHERE scan_time LIKE ?", (f"{today}%",)).fetchone()[0]
    conn.close()
    return jsonify({"visitors": [dict(r) for r in rows], "total": total, "today_visits": today_visits})

@app.route("/api/visitors/toggle", methods=["POST"])
def api_toggle_visitor():
    d = request.json
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("UPDATE visitors SET is_active=? WHERE visitor_id=?", (d.get("is_active"), d.get("visitor_id")))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

# ============ RFID NOTIFICATION ENDPOINT ============
@app.route("/api/rfid/notify", methods=["POST"])
def api_rfid_notify():
    """Receive RFID scan notifications from logger script"""
    global last_rfid_scan
    data = request.json
    tag_id = data.get("tag_id", "")
    name = data.get("name", "Unknown")
    scan_time = data.get("scan_time", ph_now())
    scan_type = data.get("scan_type", "entry")

    last_rfid_scan = {
        "id": int(time.time() * 1000),
        "tag_id": tag_id,
        "name": name,
        "scan_time": scan_time,
        "scan_type": scan_type,
        "position": "Student" if name != "Unknown" else "Unregistered",
        "department": "—",
        "vehicle_type": "—"
    }

    return jsonify({"status": "ok", "scan": last_rfid_scan})

# ============ LATEST SCAN ENDPOINT (SINGLE VERSION) ============
@app.route("/api/latest-scan")
def api_latest_scan():
    global last_rfid_scan

    conn = get_db()
    row = conn.execute("""
        SELECT s.id, s.tag_id, s.scan_time, s.scan_type, s.rssi,
               COALESCE(t.name, u.full_name, v.name, s.tag_id) AS name,
               COALESCE(t.student_no, u.student_no, v.visitor_id) AS student_no,
               COALESCE(t.department, u.department, v.name) AS department,
               COALESCE(t.vehicle_type, u.vehicle_type, 'Car') AS vehicle_type,
               COALESCE(t.position, u.position, 'Visitor') AS position
        FROM rfid_scans s
        LEFT JOIN tag_registry t ON s.tag_id = t.tag_id
        LEFT JOIN users u ON s.tag_id = u.student_no OR s.tag_id = u.tag_id
        LEFT JOIN visitors v ON s.tag_id = v.visitor_id
        ORDER BY s.id DESC LIMIT 1
    """).fetchone()
    conn.close()

    if not row:
        if last_rfid_scan:
            return jsonify({"scan": last_rfid_scan})
        return jsonify({"scan": None})

    return jsonify({"scan": dict(row)})

@app.route("/qr-scanner")
def qr_scanner():
    return QR_SCANNER_HTML

@app.route("/api/qr/scan", methods=["POST"])
def api_qr_scan():
    d          = request.json
    qr_data = d.get("qr_data", "").strip()
    conn       = get_db()

    # Check if it's a visitor QR (VISITOR1, VISITOR2, etc.)
    visitor = conn.execute("SELECT * FROM visitors WHERE visitor_id=? AND is_active=1", (qr_data,)).fetchone()

    if visitor:
        # Visitor scan
        scan_time = ph_now()

        # Check last scan type for this visitor
        last_scan = conn.execute(
            "SELECT scan_type FROM rfid_scans WHERE tag_id=? ORDER BY id DESC LIMIT 1",
            (visitor["visitor_id"],)
        ).fetchone()

        last_type = (last_scan["scan_type"] or "") if last_scan else ""
        is_inside = last_type in ("entry", "qr_entry", "rfid_entry")
        scan_type = "qr_exit" if is_inside else "qr_entry"
        is_exit = scan_type == "qr_exit"

        conn.execute("""
            INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna, scan_type)
            VALUES (?, ?, ?, ?, ?)
        """, (visitor["visitor_id"], scan_time, "QR", "QR", scan_type))

        conn.execute("""
            INSERT INTO visitor_scans (visitor_id, scan_time, scan_type)
            VALUES (?, ?, ?)
        """, (visitor["visitor_id"], scan_time, "exit" if is_exit else "entry"))

        # Update parking slots for visitors (use student slots)
        slot_type = "student_car"
        slot_labels = {"student_car": "Student Cars", "student_moto": "Student Motorcycles"}

        slot = conn.execute("SELECT * FROM parking_slots WHERE slot_type=?", (slot_type,)).fetchone()
        slot_info = None

        if slot:
            if is_exit:
                conn.execute("UPDATE parking_slots SET occupied=MAX(occupied-1, 0) WHERE slot_type=?", (slot_type,))
                available = slot["capacity"] - max(slot["occupied"] - 1, 0)
                slot_info = {"label": slot_labels.get(slot_type, slot_type), "available": max(0, available), "capacity": slot["capacity"], "status": "ok"}
            else:
                available = slot["capacity"] - slot["occupied"]
                if available > 0:
                    conn.execute("UPDATE parking_slots SET occupied=MIN(occupied+1, capacity) WHERE slot_type=?", (slot_type,))
                    available -= 1
                status = "full" if available <= 0 else "warning" if available < slot["capacity"] * 0.2 else "ok"
                slot_info = {"label": slot_labels.get(slot_type, slot_type), "available": max(0, available), "capacity": slot["capacity"], "status": status}

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
                "department": "Visitor",
                "vehicle_type": "Car",
                "purpose": "Visitor Access"
            },
            "slot": slot_info
        })

    # Check regular user
    user = conn.execute("SELECT * FROM users WHERE student_no=?", (qr_data,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"status": "not_found"})

    last_scan = conn.execute(
        "SELECT scan_type FROM rfid_scans WHERE (tag_id=? OR tag_id=?) ORDER BY id DESC LIMIT 1",
        (user["student_no"], user["tag_id"] or "")
    ).fetchone()

    last_type = (last_scan["scan_type"] or "") if last_scan else ""
    is_inside = last_type in ("entry", "qr_entry", "rfid_entry")
    scan_type = "qr_exit" if is_inside else "qr_entry"
    is_exit   = scan_type == "qr_exit"

    scan_time = ph_now()

    conn.execute("""
        INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna, scan_type)
        VALUES (?, ?, ?, ?, ?)
    """, (user["student_no"], scan_time, "QR", "QR", scan_type))

    conn.execute("""
        INSERT INTO qr_scans (student_no, scan_time, method)
        VALUES (?, ?, 'qr')
    """, (qr_data, scan_time))

    position     = (user["position"] or "Student").lower()
    vehicle_type = (user["vehicle_type"] or "").lower()
    is_moto      = vehicle_type in ["motorcycle", "motor", "bike"]
    is_staff     = position in ["faculty", "staff"]
    slot_type    = ("faculty" if is_staff else "student") + ("_moto" if is_moto else "_car")
    slot_labels  = {
        "faculty_car":  "Faculty/PWD Cars",
        "faculty_moto": "Faculty Motorcycles",
        "student_car":  "Student Cars",
        "student_moto": "Student Motorcycles"
    }

    slot      = conn.execute("SELECT * FROM parking_slots WHERE slot_type=?", (slot_type,)).fetchone()
    slot_info = None

    if slot:
        if is_exit:
            conn.execute("UPDATE parking_slots SET occupied=MAX(occupied-1, 0) WHERE slot_type=?", (slot_type,))
            available = slot["capacity"] - max(slot["occupied"] - 1, 0)
            slot_info = {
                "label":     slot_labels.get(slot_type, slot_type),
                "available": max(0, available),
                "capacity":  slot["capacity"],
                "status":    "ok"
            }
        else:
            available = slot["capacity"] - slot["occupied"]
            if available > 0:
                conn.execute("UPDATE parking_slots SET occupied=MIN(occupied+1, capacity) WHERE slot_type=?", (slot_type,))
                available -= 1
            pct    = ((slot["capacity"] - available) / slot["capacity"] * 100)
            status = "full" if available <= 0 else "warning" if pct >= 80 else "ok"
            slot_info = {
                "label":     slot_labels.get(slot_type, slot_type),
                "available": max(0, available),
                "capacity":  slot["capacity"],
                "status":    status
            }

    conn.commit()
    conn.close()
    return jsonify({
        "status":    "ok",
        "scan_time": scan_time,
        "scan_type": "exit" if is_exit else "entry",
        "user": {
            "student_no":   user["student_no"],
            "full_name":    user["full_name"],
            "position":     user["position"],
            "college":      user["college"],
            "department":   user["department"],
            "vehicle_type": user["vehicle_type"],
        },
        "slot": slot_info
    })

# ============================================================
#  MAIN
# ============================================================
if __name__ == "__main__":
    init_db()
    print("=" * 50)
    print("  MMSU CCIS Parking Admin Dashboard")
    print("  http://localhost:5001")
    print("  Fixed Visitor QR Codes: VISITOR1, VISITOR2, VISITOR3, VISITOR4, VISITOR5")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5001, debug=True)
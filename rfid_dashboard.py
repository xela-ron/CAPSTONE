"""
RFID Web Dashboard - QB0A M-Series
Student/Employee Vehicle Tracking System
Visit http://localhost:5000
"""

from flask import Flask, jsonify, render_template_string, request, send_file
import sqlite3
import io
import csv
from datetime import datetime

app = Flask(__name__)
DB_FILE = "rfid_logs.db"

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>RFID Vehicle Tracking Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }

    header {
      background: #1e3a5f; padding: 16px 32px;
      display: flex; align-items: center; justify-content: space-between;
      border-bottom: 3px solid #3b82f6;
    }
    header h1 { font-size: 1.3rem; color: #93c5fd; }
    .badge {
      background: #16a34a; color: white; border-radius: 999px;
      padding: 4px 14px; font-size: 0.8rem; font-weight: bold;
      animation: pulse 2s infinite;
    }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }

    .tabs {
      display: flex; gap: 0; padding: 20px 32px 0;
      border-bottom: 2px solid #334155;
    }
    .tab {
      padding: 10px 24px; cursor: pointer; font-weight: 600;
      font-size: 0.9rem; color: #94a3b8; border-bottom: 3px solid transparent;
      margin-bottom: -2px; transition: all 0.2s;
    }
    .tab.active { color: #3b82f6; border-bottom-color: #3b82f6; }
    .tab:hover { color: #e2e8f0; }

    .page { display: none; padding: 24px 32px; }
    .page.active { display: block; }

    .stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
    .stat-card {
      background: #1e293b; border: 1px solid #334155; border-radius: 12px;
      padding: 18px 24px; flex: 1; min-width: 140px; text-align: center;
    }
    .stat-card .value { font-size: 1.8rem; font-weight: bold; color: #3b82f6; }
    .stat-card .label { font-size: 0.82rem; color: #94a3b8; margin-top: 4px; }

    .controls { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; }
    input[type=text], select {
      background: #1e293b; border: 1px solid #334155; color: #e2e8f0;
      padding: 8px 14px; border-radius: 8px; font-size: 0.9rem;
    }
    input[type=text] { width: 220px; }

    button {
      background: #3b82f6; color: white; border: none;
      padding: 8px 18px; border-radius: 8px; cursor: pointer;
      font-size: 0.9rem; font-weight: 600; transition: background 0.2s;
    }
    button:hover { background: #2563eb; }
    button.green { background: #16a34a; }
    button.green:hover { background: #15803d; }
    button.red { background: #dc2626; }
    button.red:hover { background: #b91c1c; }
    button.orange { background: #d97706; }
    button.orange:hover { background: #b45309; }

    table {
      width: 100%; border-collapse: collapse; background: #1e293b;
      border-radius: 12px; overflow: hidden; border: 1px solid #334155;
    }
    thead th {
      background: #1e3a5f; padding: 11px 14px; text-align: left;
      font-size: 0.8rem; color: #93c5fd; text-transform: uppercase; letter-spacing: 0.05em;
    }
    tbody tr { border-bottom: 1px solid #334155; transition: background 0.15s; }
    tbody tr:hover { background: #263548; }
    td { padding: 10px 14px; font-size: 0.88rem; }
    td.tag { font-family: monospace; color: #34d399; font-weight: bold; font-size: 0.78rem; }
    td.time { color: #94a3b8; font-size: 0.8rem; }
    td.name { font-weight: 600; color: #e2e8f0; }
    td.rssi { color: #fbbf24; font-size: 0.8rem; }
    .badge-pos {
      display: inline-block; padding: 2px 10px; border-radius: 999px;
      font-size: 0.75rem; font-weight: 600;
    }
    .pos-student { background: #1e40af; color: #93c5fd; }
    .pos-faculty { background: #065f46; color: #6ee7b7; }
    .pos-staff   { background: #78350f; color: #fcd34d; }
    .pos-visitor { background: #4c1d95; color: #c4b5fd; }
    .pos-default { background: #1e293b; color: #94a3b8; }

    .new-row { animation: highlight 2s ease; }
    @keyframes highlight { 0%{background:#1d4635} 100%{background:transparent} }

    /* Modal */
    .modal-bg {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.7); z-index: 100;
      align-items: center; justify-content: center;
    }
    .modal-bg.open { display: flex; }
    .modal {
      background: #1e293b; border: 1px solid #334155; border-radius: 16px;
      padding: 28px; width: 480px; max-width: 95vw;
    }
    .modal h2 { color: #93c5fd; margin-bottom: 20px; font-size: 1.1rem; }
    .form-row { margin-bottom: 14px; }
    .form-row label { display: block; font-size: 0.82rem; color: #94a3b8; margin-bottom: 5px; }
    .form-row input, .form-row select {
      width: 100%; padding: 9px 12px; background: #0f172a;
      border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-size: 0.9rem;
    }
    .form-row input:focus, .form-row select:focus {
      outline: none; border-color: #3b82f6;
    }
    .modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px; }

    /* Alert popup */
    #scan-alert {
      display: none; position: fixed; top: 20px; right: 20px; z-index: 200;
      background: #1e293b; border: 2px solid #3b82f6; border-radius: 14px;
      padding: 18px 24px; min-width: 300px; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      animation: slidein 0.3s ease;
    }
    @keyframes slidein { from{transform:translateX(120%)} to{transform:translateX(0)} }
    #scan-alert .alert-title { font-size: 0.8rem; color: #94a3b8; margin-bottom: 6px; }
    #scan-alert .alert-name { font-size: 1.2rem; font-weight: 700; color: #34d399; }
    #scan-alert .alert-details { font-size: 0.85rem; color: #cbd5e1; margin-top: 4px; }
    #scan-alert .alert-tag { font-size: 0.72rem; color: #64748b; font-family: monospace; margin-top: 6px; }

    #status-bar { text-align: center; padding: 12px; font-size: 0.8rem; color: #475569; }
  </style>
</head>
<body>

<!-- Scan Alert Popup -->
<div id="scan-alert">
  <div class="alert-title">TAG DETECTED</div>
  <div class="alert-name" id="alert-name">—</div>
  <div class="alert-details" id="alert-details">—</div>
  <div class="alert-tag" id="alert-tag">—</div>
</div>

<header>
  <h1>[RFID] Vehicle Tracking Dashboard</h1>
  <span class="badge">* LIVE</span>
</header>

<div class="tabs">
  <div class="tab active" onclick="showTab('scans')">Live Scans</div>
  <div class="tab" onclick="showTab('tags')">Registered Tags</div>
  <div class="tab" onclick="showTab('users')">Users</div>
</div>

<!-- LIVE SCANS PAGE -->
<div class="page active" id="page-scans">
  <div class="stats">
    <div class="stat-card"><div class="value" id="total-scans">-</div><div class="label">Total Scans</div></div>
    <div class="stat-card"><div class="value" id="unique-tags">-</div><div class="label">Unique Tags</div></div>
    <div class="stat-card"><div class="value" id="today-scans">-</div><div class="label">Today's Scans</div></div>
    <div class="stat-card"><div class="value" id="registered-count">-</div><div class="label">Registered Tags</div></div>
  </div>
  <div class="controls">
    <input type="text" id="search-scan" placeholder="Search name or tag..." oninput="filterScans()">
    <button class="green" onclick="exportCSV()">Export CSV</button>
    <button onclick="fetchScans()">Refresh</button>
    <button class="red" onclick="clearConfirm()">Clear All</button>
  </div>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Name</th><th>Student No.</th><th>Department</th>
        <th>Course</th><th>Vehicle Type</th><th>Position</th>
        <th>Date</th><th>Time</th><th>RSSI</th><th>Tag ID</th>
      </tr>
    </thead>
    <tbody id="scan-table"></tbody>
  </table>
  <div id="status-bar">Auto-refreshes every 3 seconds</div>
</div>

<!-- REGISTERED TAGS PAGE -->
<div class="page" id="page-tags">
  <div class="controls">
    <input type="text" id="search-tag" placeholder="Search registered tags..." oninput="filterTags()">
    <button class="green" onclick="openRegisterModal()">+ Register New Tag</button>
  </div>
  <table>
    <thead>
      <tr>
        <th>Tag ID (EPC)</th><th>Name</th><th>Student No.</th>
        <th>Department</th><th>Course</th><th>Vehicle Type</th><th>Position</th><th>Actions</th>
      </tr>
    </thead>
    <tbody id="tag-table"></tbody>
  </table>
</div>


<!-- USERS PAGE -->
<div class="page" id="page-users">
  <div class="controls">
    <input type="text" id="search-user" placeholder="Search users by name or ID..." oninput="filterUsers()" style="width:280px">
  </div>
  <table>
    <thead>
      <tr>
        <th>Student No.</th><th>Full Name</th><th>Position</th><th>College</th>
        <th>Vehicle Type</th><th>RFID Tag</th><th>Registered</th><th>Actions</th>
      </tr>
    </thead>
    <tbody id="users-table"></tbody>
  </table>
</div>

<!-- Register / Edit Modal -->
<div class="modal-bg" id="modal-bg">
  <div class="modal">
    <h2 id="modal-title">Register New Tag</h2>
    <input type="hidden" id="modal-tag-id-original">
    <div class="form-row">
      <label>Tag ID (EPC) — scan tag first or enter manually</label>
      <input type="text" id="f-tag-id" placeholder="e.g. 0102030405060708090A0B0C">
    </div>
    <div class="form-row">
      <label>Full Name</label>
      <input type="text" id="f-name" placeholder="e.g. Juan Dela Cruz">
    </div>
    <div class="form-row">
      <label>Student / Employee Number</label>
      <input type="text" id="f-student-no" placeholder="e.g. 2021-00123">
    </div>
    <div class="form-row">
      <label>Department</label>
      <input type="text" id="f-department" placeholder="e.g. College of Engineering">
    </div>
    <div class="form-row">
      <label>Course</label>
      <input type="text" id="f-course" placeholder="e.g. BS Computer Engineering">
    </div>
    <div class="form-row">
      <label>Vehicle Type</label>
      <input type="text" id="f-vehicle" placeholder="e.g. Motorcycle, Car, SUV">
    </div>
    <div class="form-row">
      <label>Position</label>
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

<script>
  let allScans = [];
  let allTags  = [];
  let lastScanId = 0;

  // ── Tabs ──────────────────────────────────────────────────────
  function showTab(tab) {
    document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', ['scans','tags'][i]===tab));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-'+tab).classList.add('active');
    if (tab === 'tags') fetchTags();
  }

  // ── Position badge ────────────────────────────────────────────
  function posBadge(pos) {
    const map = {Student:'pos-student',Faculty:'pos-faculty',Staff:'pos-staff',Visitor:'pos-visitor'};
    const cls = map[pos] || 'pos-default';
    return `<span class="badge-pos ${cls}">${pos||'—'}</span>`;
  }

  // ── Scan alert popup ──────────────────────────────────────────
  function showAlert(scan) {
    if (!scan.name) return;
    document.getElementById('alert-name').textContent    = scan.name;
    document.getElementById('alert-details').textContent =
      `${scan.position||''} | ${scan.department||''} | ${scan.vehicle_type||''}`;
    document.getElementById('alert-tag').textContent = scan.tag_id;
    const el = document.getElementById('scan-alert');
    el.style.display = 'block';
    clearTimeout(window._alertTimer);
    window._alertTimer = setTimeout(() => el.style.display='none', 4000);
  }

  // ── Live Scans ────────────────────────────────────────────────
  async function fetchScans() {
    const res  = await fetch('/api/scans?limit=200');
    const data = await res.json();
    allScans = data.scans;
    renderScans(allScans);

    if (data.scans.length > 0 && data.scans[0].id > lastScanId) {
      lastScanId = data.scans[0].id;
      showAlert(data.scans[0]);
      const rows = document.querySelectorAll('#scan-table tr');
      if (rows.length) rows[0].classList.add('new-row');
    }
  }

  function renderScans(rows) {
    document.getElementById('scan-table').innerHTML = rows.map(r => {
      const dt = r.scan_time ? r.scan_time.split(' ') : ['—','—'];
      const date = dt[0] || '—';
      const time = dt[1] || '—';
      return `
      <tr>
        <td>${r.id}</td>
        <td class="name">${r.name||'<span style="color:#64748b">Unregistered</span>'}</td>
        <td>${r.student_no||'—'}</td>
        <td>${r.department||'—'}</td>
        <td>${r.course||'—'}</td>
        <td>${r.vehicle_type||'—'}</td>
        <td>${posBadge(r.position)}</td>
        <td class="time">${date}</td>
        <td class="time">${time}</td>
        <td class="rssi">${r.rssi||'—'}</td>
        <td class="tag">${r.tag_id}</td>
      </tr>`;
    }).join('');
  }

  function filterScans() {
    const q = document.getElementById('search-scan').value.toLowerCase();
    renderScans(allScans.filter(r =>
      (r.tag_id||'').toLowerCase().includes(q) ||
      (r.name||'').toLowerCase().includes(q) ||
      (r.student_no||'').toLowerCase().includes(q)
    ));
  }

  // ── Stats ─────────────────────────────────────────────────────
  async function fetchStats() {
    const res  = await fetch('/api/stats');
    const data = await res.json();
    document.getElementById('total-scans').textContent    = data.total;
    document.getElementById('unique-tags').textContent    = data.unique;
    document.getElementById('today-scans').textContent    = data.today;
    document.getElementById('registered-count').textContent = data.registered;
  }

  // ── Registered Tags ───────────────────────────────────────────
  async function fetchTags() {
    const res  = await fetch('/api/tags');
    const data = await res.json();
    allTags = data.tags;
    renderTags(allTags);
  }

  function renderTags(rows) {
    document.getElementById('tag-table').innerHTML = rows.map(r => `
      <tr>
        <td class="tag">${r.tag_id}</td>
        <td class="name">${r.name||'—'}</td>
        <td>${r.student_no||'—'}</td>
        <td>${r.department||'—'}</td>
        <td>${r.course||'—'}</td>
        <td>${r.vehicle_type||'—'}</td>
        <td>${posBadge(r.position)}</td>
        <td>
          <button class="orange" style="padding:4px 12px;font-size:0.8rem" onclick='editTag(${JSON.stringify(r)})'>Edit</button>
          <button class="red" style="padding:4px 12px;font-size:0.8rem;margin-left:4px" onclick="deleteTag('${r.tag_id}')">Delete</button>
        </td>
      </tr>`).join('');
  }

  function filterTags() {
    const q = document.getElementById('search-tag').value.toLowerCase();
    renderTags(allTags.filter(r =>
      (r.tag_id||'').toLowerCase().includes(q) ||
      (r.name||'').toLowerCase().includes(q)
    ));
  }

  // ── Modal ─────────────────────────────────────────────────────
  function setTagIdEditable(editable) {
    const el = document.getElementById('f-tag-id');
    el.readOnly = !editable;
    el.style.opacity = editable ? '1' : '0.5';
    el.style.cursor  = editable ? 'text' : 'not-allowed';
  }

  function openRegisterModal(tagId='') {
    document.getElementById('modal-title').textContent = 'Register New Tag';
    document.getElementById('f-tag-id').value      = tagId;
    document.getElementById('f-name').value        = '';
    document.getElementById('f-student-no').value  = '';
    document.getElementById('f-department').value  = '';
    document.getElementById('f-course').value      = '';
    document.getElementById('f-vehicle').value     = '';
    document.getElementById('f-position').value    = 'Student';
    document.getElementById('modal-tag-id-original').value = '';
    setTagIdEditable(true);
    document.getElementById('modal-bg').classList.add('open');
  }

  function editTag(r) {
    document.getElementById('modal-title').textContent = 'Edit Tag';
    document.getElementById('f-tag-id').value      = r.tag_id;
    document.getElementById('f-name').value        = r.name||'';
    document.getElementById('f-student-no').value  = r.student_no||'';
    document.getElementById('f-department').value  = r.department||'';
    document.getElementById('f-course').value      = r.course||'';
    document.getElementById('f-vehicle').value     = r.vehicle_type||'';
    document.getElementById('f-position').value    = r.position||'Student';
    document.getElementById('modal-tag-id-original').value = r.tag_id;
    setTagIdEditable(false);
    document.getElementById('modal-bg').classList.add('open');
  }

  function closeModal() {
    document.getElementById('modal-bg').classList.remove('open');
    setTagIdEditable(true);
  }

  async function saveTag() {
    const payload = {
      tag_id:      document.getElementById('f-tag-id').value.trim().toUpperCase(),
      name:        document.getElementById('f-name').value.trim(),
      student_no:  document.getElementById('f-student-no').value.trim(),
      department:  document.getElementById('f-department').value.trim(),
      course:      document.getElementById('f-course').value.trim(),
      vehicle_type:document.getElementById('f-vehicle').value.trim(),
      position:    document.getElementById('f-position').value,
      original_tag_id: document.getElementById('modal-tag-id-original').value.trim()
    };
    if (!payload.tag_id) { alert('Tag ID is required!'); return; }
    await fetch('/api/tags/save', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    closeModal();
    fetchTags();
    fetchStats();
  }

  async function deleteTag(tagId) {
    if (!confirm('Delete this tag registration?')) return;
    await fetch('/api/tags/delete', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({tag_id: tagId})
    });
    fetchTags();
    fetchStats();
  }

  // ── Export / Clear ────────────────────────────────────────────
  function exportCSV() { window.location.href = '/api/export/csv'; }

  function clearConfirm() {
    if (confirm('Delete ALL scan records? Tag registrations will be kept.')) {
      fetch('/api/clear', {method:'POST'}).then(() => { fetchScans(); fetchStats(); });
    }
  }

  // ── Auto refresh ──────────────────────────────────────────────
  async function refresh() { await fetchStats(); await fetchScans(); }
  refresh();
  setInterval(refresh, 3000);

  // ── USERS TAB ─────────────────────────────────────────────────────────────
  let allUsers = [];

  async function fetchUsers() {
    const res  = await fetch('/api/admin/users');
    const data = await res.json();
    allUsers   = data.users;
    renderUsers(allUsers);
  }

  function renderUsers(rows) {
    const tbody = document.getElementById('users-table');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:40px;color:#64748b">No registered users yet</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td style="font-family:monospace;font-size:0.85rem">${r.student_no}</td>
        <td style="font-weight:600;color:#e2e8f0">${r.full_name||'—'}</td>
        <td>${posBadge(r.position)}</td>
        <td style="font-size:0.85rem">${r.college||'—'}</td>
        <td style="font-size:0.85rem">${r.vehicle_type||'—'}</td>
        <td style="font-family:monospace;font-size:0.75rem;color:${r.tag_id ? '#34d399' : '#f59e0b'}">
          ${r.tag_id ? r.tag_id.substring(0,16)+'...' : 'Not assigned'}
        </td>
        <td style="font-size:0.8rem;color:#94a3b8">${r.created_at ? r.created_at.split(' ')[0] : '—'}</td>
        <td>
          <button class="orange" style="padding:4px 12px;font-size:0.8rem"
            onclick="openAssignModal('${r.student_no}','${r.full_name||''}','${r.tag_id||''}')">
            ${r.tag_id ? 'Re-assign' : 'Assign Tag'}
          </button>
          ${r.tag_id ? `<button class="red" style="padding:4px 12px;font-size:0.8rem;margin-left:4px"
            onclick="removeTag('${r.student_no}')">Remove</button>` : ''}
        </td>
      </tr>`).join('');
  }

  function filterUsers() {
    const q = document.getElementById('search-user').value.toLowerCase();
    renderUsers(allUsers.filter(r =>
      (r.student_no||'').toLowerCase().includes(q) ||
      (r.full_name||'').toLowerCase().includes(q)
    ));
  }

  function openAssignModal(studentNo, name, currentTag) {
    document.getElementById('assign-student-no').value = studentNo;
    document.getElementById('assign-user-name').value  = name + ' (' + studentNo + ')';
    document.getElementById('assign-tag-id').value     = currentTag || '';
    document.getElementById('assign-modal-bg').classList.add('open');
  }

  function closeAssignModal() {
    document.getElementById('assign-modal-bg').classList.remove('open');
  }

  async function saveAssignTag() {
    const studentNo = document.getElementById('assign-student-no').value;
    const tagId     = document.getElementById('assign-tag-id').value.trim().toUpperCase();
    if (!tagId) { alert('Please enter a Tag ID'); return; }
    const res = await fetch('/api/admin/assign_tag', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({student_no: studentNo, tag_id: tagId})
    });
    const data = await res.json();
    if (data.status === 'ok') {
      closeAssignModal();
      fetchUsers();
      alert('Tag assigned successfully!');
    } else {
      alert('Error: ' + data.message);
    }
  }

  async function removeTag(studentNo) {
    if (!confirm('Remove RFID tag from this user?')) return;
    await fetch('/api/admin/assign_tag', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({student_no: studentNo, tag_id: ''})
    });
    fetchUsers();
  }

  // Override showTab to load users when tab clicked
  const _origShowTab = showTab;
  function showTab(tab) {
    document.querySelectorAll('.tab').forEach((t,i) => 
      t.classList.toggle('active', ['scans','tags','users'][i]===tab));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-'+tab).classList.add('active');
    if (tab === 'tags') fetchTags();
    if (tab === 'users') fetchUsers();
  }
</script>

<!-- Assign Tag Modal -->
<div class="modal-bg" id="assign-modal-bg">
  <div class="modal">
    <h2 id="assign-modal-title">Assign RFID Tag</h2>
    <input type="hidden" id="assign-student-no">
    <div class="form-row">
      <label>User</label>
      <input type="text" id="assign-user-name" readonly style="opacity:0.7;cursor:not-allowed">
    </div>
    <div class="form-row">
      <label>Tag ID (EPC) - Scan tag or enter manually</label>
      <input type="text" id="assign-tag-id" placeholder="e.g. 0102030405060708090A0004" style="font-family:monospace">
    </div>
    <div style="font-size:0.8rem;color:#94a3b8;margin-top:-8px;margin-bottom:12px">
      Tip: Run rfid_logger.py, scan the tag, and copy the Tag ID shown
    </div>
    <div class="modal-actions">
      <button class="red" onclick="closeAssignModal()">Cancel</button>
      <button class="green" onclick="saveAssignTag()">Assign Tag</button>
    </div>
  </div>
</div>
</body>
</html>
"""


def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rfid_scans (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_id       TEXT NOT NULL,
            scan_time    TEXT NOT NULL,
            rssi         TEXT,
            antenna      TEXT
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
    # Add rssi/antenna columns if missing
    for col in ["rssi", "antenna"]:
        try:
            conn.execute(f"ALTER TABLE rfid_scans ADD COLUMN {col} TEXT")
        except Exception:
            pass
    conn.commit()
    conn.close()


@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/scans")
def api_scans():
    limit = request.args.get("limit", 200, type=int)
    conn = get_db()
    rows = conn.execute("""
        SELECT s.id, s.tag_id, s.scan_time, s.rssi, s.antenna,
               t.name, t.student_no, t.department, t.course, t.vehicle_type, t.position
        FROM rfid_scans s
        LEFT JOIN tag_registry t ON s.tag_id = t.tag_id
        ORDER BY s.id DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return jsonify({"scans": [dict(r) for r in rows]})


@app.route("/api/stats")
def api_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    total      = conn.execute("SELECT COUNT(*) FROM rfid_scans").fetchone()[0]
    unique     = conn.execute("SELECT COUNT(DISTINCT tag_id) FROM rfid_scans").fetchone()[0]
    today_c    = conn.execute("SELECT COUNT(*) FROM rfid_scans WHERE scan_time LIKE ?", (f"{today}%",)).fetchone()[0]
    registered = conn.execute("SELECT COUNT(*) FROM tag_registry").fetchone()[0]
    last       = conn.execute("""
        SELECT COALESCE(t.name, s.tag_id) as label
        FROM rfid_scans s LEFT JOIN tag_registry t ON s.tag_id = t.tag_id
        ORDER BY s.id DESC LIMIT 1
    """).fetchone()
    conn.close()
    return jsonify({"total": total, "unique": unique, "today": today_c,
                    "registered": registered, "last_tag": last[0] if last else None})


@app.route("/api/tags")
def api_tags():
    conn = get_db()
    rows = conn.execute("SELECT * FROM tag_registry ORDER BY name").fetchall()
    conn.close()
    return jsonify({"tags": [dict(r) for r in rows]})


@app.route("/api/tags/save", methods=["POST"])
def api_tags_save():
    d = request.json
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
        SELECT s.id, s.tag_id, s.scan_time, s.rssi,
               t.name, t.student_no, t.department, t.course, t.vehicle_type, t.position
        FROM rfid_scans s
        LEFT JOIN tag_registry t ON s.tag_id = t.tag_id
        ORDER BY s.scan_time DESC
    """).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Tag ID", "Date", "Time", "Name", "Student No",
                     "Department", "Course", "Vehicle Type", "Position"])
    for r in rows:
        dt = r["scan_time"].split(" ") if r["scan_time"] else ["—", "—"]
        writer.writerow([r["id"], r["tag_id"], dt[0], dt[1] if len(dt)>1 else "—",
                         r["name"], r["student_no"], r["department"],
                         r["course"], r["vehicle_type"], r["position"]])
    output.seek(0)
    filename = f"rfid_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(io.BytesIO(output.getvalue().encode("utf-8")),
                     mimetype="text/csv", as_attachment=True, download_name=filename)


@app.route("/api/clear", methods=["POST"])
def api_clear():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("DELETE FROM rfid_scans")
    conn.commit()
    conn.close()
    return jsonify({"status": "cleared"})



@app.route("/api/admin/users")
def api_admin_users():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, student_no, full_name, position, college, vehicle_type, tag_id, created_at FROM users WHERE is_admin=0 ORDER BY full_name"
    ).fetchall()
    conn.close()
    return jsonify({"users": [dict(r) for r in rows]})


@app.route("/api/admin/assign_tag", methods=["POST"])
def api_admin_assign_tag():
    d = request.json
    student_no = d.get("student_no", "").strip()
    tag_id = d.get("tag_id", "").strip().upper()
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "UPDATE users SET tag_id=? WHERE student_no=?",
            (tag_id if tag_id else None, student_no)
        )
        if tag_id:
            row = conn.execute(
                "SELECT * FROM users WHERE student_no=?", (student_no,)
            ).fetchone()
            if row:
                conn.execute("""
                    INSERT INTO tag_registry (tag_id, name, student_no, department, course, vehicle_type, position)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(tag_id) DO UPDATE SET
                        name=excluded.name, student_no=excluded.student_no,
                        department=excluded.department,
                        vehicle_type=excluded.vehicle_type,
                        position=excluded.position
                """, (tag_id, row['full_name'], row['student_no'],
                      row['department'], '', row['vehicle_type'], row['position']))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == "__main__":
    init_db()
    print("Starting RFID Dashboard at http://localhost:5000")
    app.run(host="0.0.0.0", port=5001, debug=False)


"""
UHF RFID Exit Logger - EXIT GATE (RFID ONLY)
Logs vehicle EXIT scans to the same DB as the entry logger.
Run this on the EXIT gate terminal.
COM3, 57600 baud
Sends to /api/qr/scan endpoint - kiosk displays and speaks
"""

import serial
import sqlite3
import time
import urllib.request
import json
from datetime import datetime
import pytz

_PH_TZ = pytz.timezone("Asia/Manila")

PORT = "COM3"
BAUDRATE = 57600           # ✅ FIXED: was 5700 (missing a zero)
DB_FILE = "rfid_logs.db"

CMD_SINGLE_INVENTORY = bytes([0x7C, 0xFF, 0xFF, 0x20, 0x00, 0x00, 0x66])

# Cooldown
recent_scans = {}
COOLDOWN_SECS = 6

# Prevent sending the same tag repeatedly
last_sent_tag = ""
last_sent_time = 0
SEND_COOLDOWN = 5


def is_cooldown(key):
    now = time.time()
    if key in recent_scans and now - recent_scans[key] < COOLDOWN_SECS:
        return True
    recent_scans[key] = now
    return False


def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
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
    for col in ["rssi", "antenna", "scan_type"]:
        try:
            conn.execute(f"ALTER TABLE rfid_scans ADD COLUMN {col} TEXT")
        except Exception:
            pass
    conn.commit()
    conn.close()
    print(f"[DB] Database ready: {DB_FILE}")


def decrement_parking(student_no):
    try:
        payload = json.dumps({"student_no": student_no}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:5000/api/parking/exit",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
        print(f"[PARKING] Slot freed for {student_no}")
    except Exception as e:
        print(f"[PARKING] Error: {e}")


def send_to_kiosk_api(tag_id, status="ok", message=""):
    """Send RFID exit scan to kiosk — matches entry logger signature"""
    global last_sent_tag, last_sent_time

    now = time.time()
    if tag_id == last_sent_tag and now - last_sent_time < SEND_COOLDOWN:
        print(f"[API  ] Cooldown - skipping duplicate send for tag {tag_id[:8]}...")
        return

    last_sent_tag = tag_id
    last_sent_time = now

    try:
        # ✅ FIXED: now sends status and message just like the entry logger
        payload = json.dumps({
            "qr_data": tag_id,
            "mode": "exit",
            "source": "rfid",
            "status": status,
            "message": message
        }).encode()

        req = urllib.request.Request(
            "http://127.0.0.1:5000/api/qr/scan",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
        print(f"[API  ] RFID EXIT sent to kiosk (status: {status})")
    except Exception as e:
        print(f"[API  ] Error: {e}")


def save_exit_scan(tag_id, rssi="", antenna=""):
    if is_cooldown(tag_id):
        print(f"[EXIT] Cooldown active for {tag_id[:8]}...")
        return

    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row

    user = conn.execute(
        "SELECT student_no, full_name FROM users WHERE tag_id=?", (tag_id,)
    ).fetchone()

    # UNREGISTERED TAG
    if not user:
        print(f"[EXIT] ACCESS DENIED - Unregistered tag: {tag_id}")
        conn.close()
        # ✅ FIXED: pass status="not_found" so the kiosk shows Access Denied + alarm
        send_to_kiosk_api(tag_id, status="not_found", message="Access Denied")
        return

    student_no = user["student_no"]
    full_name  = user["full_name"]

    # Check if user is inside
    inside = conn.execute(
        "SELECT * FROM currently_inside WHERE student_no=?",
        (student_no,)
    ).fetchone()

    if not inside:
        print(f"[EXIT] BLOCKED — {full_name} is not inside")
        conn.close()
        # ✅ FIXED: pass status="not_inside" so the kiosk shows the right message
        send_to_kiosk_api(tag_id, status="not_inside", message="Not Inside")
        return

    scan_time = datetime.now(_PH_TZ).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna, scan_type) VALUES (?,?,?,?,'rfid_exit')",
        (tag_id, scan_time, rssi, antenna)
    )
    conn.execute("DELETE FROM currently_inside WHERE student_no=?", (student_no,))
    conn.commit()
    conn.close()

    print(f"[EXIT] {scan_time} | {tag_id} | {full_name}")
    decrement_parking(student_no)
    # ✅ FIXED: pass status="ok" and a message for the kiosk welcome display
    send_to_kiosk_api(tag_id, status="ok", message="Goodbye")


def parse_response(data: bytes):
    tags = []
    i = 0
    while i < len(data) - 23:
        if data[i] == 0xCC and data[i+1] == 0xFF and data[i+2] == 0xFF:
            try:
                if len(data) - i >= 22:
                    antenna  = data[i + 8]
                    epc      = data[i+9 : i+21].hex().upper()
                    rssi_raw = data[i+21]
                    rssi     = f"-{rssi_raw}dBm"
                    if len(epc) == 24 and epc != "0"*24 and epc != "F"*24:
                        tags.append((epc, rssi, str(antenna)))
                        i += 24
                        continue
            except Exception:
                pass
        i += 1
    return tags


def run_continuous(ser):
    print("[INFO] Continuous exit scan running... Press Ctrl+C to stop\n")
    try:
        while True:
            ser.reset_input_buffer()
            ser.write(CMD_SINGLE_INVENTORY)
            buffer = b""
            t_end = time.time() + 1.5
            while time.time() < t_end:
                if ser.in_waiting > 0:
                    buffer += ser.read(ser.in_waiting)
                time.sleep(0.01)
            if buffer and len(buffer) > 10:
                tags = parse_response(buffer)
                if tags:
                    for tag_id, rssi, ant in tags:
                        save_exit_scan(tag_id, rssi, ant)
                else:
                    print("[....] Scanning for exit...")
            else:
                print("[....] Scanning for exit...")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[DONE] Exit scanner stopped.")


def run_single(ser):
    print("\n[READY] Press Enter to scan exit tag\n")
    try:
        while True:
            input(">> Press Enter to scan exit...")
            for attempt in range(5):
                ser.reset_input_buffer()
                ser.write(CMD_SINGLE_INVENTORY)
                time.sleep(1.2)
                buffer = b""
                deadline = time.time() + 0.5
                while time.time() < deadline:
                    if ser.in_waiting > 0:
                        buffer += ser.read(ser.in_waiting)
                    time.sleep(0.01)
                if buffer and len(buffer) > 8:
                    tags = parse_response(buffer)
                    if tags:
                        for tag_id, rssi, ant in tags:
                            save_exit_scan(tag_id, rssi, ant)
                        break
                print(f"[....] Retrying... ({attempt+1}/5)")
    except KeyboardInterrupt:
        print("\n[INFO] Stopped.")


def main():
    init_db()
    print("=" * 55)
    print("  MMSU CCIS Parking — RFID EXIT Scanner")
    print("  Sends to /api/qr/scan endpoint - Kiosk displays")
    print("=" * 55 + "\n")

    print("Choose mode:")
    print("  1. Single scan (press Enter each time)")
    print("  2. Continuous scan (auto)")
    choice = input("Enter 1 or 2: ").strip()

    print(f"[SERIAL] Connecting to {PORT} at {BAUDRATE} baud...")
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1, dsrdtr=False, rtscts=False)
        print(f"[SERIAL] Connected!\n")
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    if choice == "1":
        run_single(ser)
    else:
        run_continuous(ser)

    ser.close()
    print("\n[INFO] Exit scanner stopped.")


if __name__ == "__main__":
    main()
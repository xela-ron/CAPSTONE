"""
RFID LOGGER - ENTRY GATE ONLY
UHF RFID Logger for QB0A M-Series Reader (915MHz)
COM3, 57600 baud
ENTRY ONLY - Will show "Already Inside" if scanned twice
"""

import serial
import sqlite3
import time
import urllib.request
import json
from datetime import datetime
import pytz
import winsound
import threading

_PH_TZ = pytz.timezone("Asia/Manila")

PORT = "COM3"
BAUDRATE = 57600
DB_FILE = "rfid_logs.db"

CMD_SINGLE_INVENTORY = bytes([0x7C, 0xFF, 0xFF, 0x20, 0x00, 0x00, 0x66])

# Cooldown tracker
recent_scans = {}
COOLDOWN_SECS = 6

# Prevent sending the same tag repeatedly
last_sent_tag = ""
last_sent_time = 0
SEND_COOLDOWN = 5


def play_alarm(duration_seconds=5):
    """Play warning alarm"""
    def alarm_thread():
        end_time = time.time() + duration_seconds
        print("\n" + "=" * 50)
        print("⚠️  WARNING ALARM - ACCESS DENIED! ⚠️")
        print("=" * 50)
        try:
            for _ in range(duration_seconds * 2):
                if time.time() >= end_time:
                    break
                winsound.Beep(1000, 300)
                time.sleep(0.2)
        except:
            for i in range(duration_seconds):
                if time.time() >= end_time:
                    break
                print("\a", end="", flush=True)
                time.sleep(1)
        print("\n" + "=" * 50)
        print("✓ Alarm ended")
        print("=" * 50)
    alarm_thread_obj = threading.Thread(target=alarm_thread, daemon=True)
    alarm_thread_obj.start()


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


def update_parking(student_no):
    try:
        payload = json.dumps({"student_no": student_no}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:5000/api/parking/update",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
        print(f"[PARKING] Updated for {student_no}")
    except Exception as e:
        print(f"[PARKING] Error: {e}")


def send_to_kiosk_api(tag_id, is_exit=False, status="ok", message=""):
    """Send RFID scan to kiosk using same endpoint as QR code"""
    global last_sent_tag, last_sent_time

    now = time.time()
    if tag_id == last_sent_tag and now - last_sent_time < SEND_COOLDOWN:
        print(f"[API  ] Cooldown - skipping duplicate send for tag {tag_id[:8]}...")
        return

    last_sent_tag = tag_id
    last_sent_time = now

    try:
        mode = "exit" if is_exit else "entry"

        payload = json.dumps({
            "qr_data": tag_id,
            "mode": mode,
            "source": "rfid",
            "status": status,  # Add status to payload
            "message": message
        }).encode()

        req = urllib.request.Request(
            "http://127.0.0.1:5000/api/qr/scan",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
        print(f"[API  ] RFID {mode} sent to kiosk (status: {status})")
    except Exception as e:
        print(f"[API  ] Error: {e}")


def print_welcome_message(full_name):
    print("\n" + "=" * 60)
    print(f"🎉 WELCOME, {full_name.upper()}! 🎉")
    print("=" * 60)
    print("✅ Entry granted. Have a safe stay!")
    print("=" * 60 + "\n")


def print_already_inside_message(full_name):
    print("\n" + "=" * 60)
    print(f"⚠️  ATTENTION, {full_name.upper()}! ⚠️")
    print("=" * 60)
    print("❌ YOU ARE ALREADY INSIDE!")
    print("📌 Please use the EXIT gate to leave.")
    print("=" * 60 + "\n")


def print_access_denied_message(tag_id):
    print("\n" + "=" * 60)
    print("🔴 ACCESS DENIED! 🔴")
    print("=" * 60)
    print(f"📡 Unregistered Tag ID: {tag_id[:16]}...")
    print("🚫 This RFID tag is not registered in the system.")
    print("=" * 60 + "\n")
    play_alarm(5)


def save_rfid_scan(tag_id, rssi="", antenna=""):
    if is_cooldown(tag_id):
        print(f"[RFID] Cooldown active for {tag_id[:8]}...")
        return

    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row

    user = conn.execute(
        "SELECT student_no, full_name, position, vehicle_type FROM users WHERE tag_id=?", (tag_id,)
    ).fetchone()

    # UNREGISTERED TAG
    if not user:
        print(f"[RFID] ACCESS DENIED - Unregistered tag: {tag_id}")
        print_access_denied_message(tag_id)
        # Send with status "not_found" for kiosk
        send_to_kiosk_api(tag_id, False, "not_found", "Access Denied")
        conn.close()
        return

    student_no = user["student_no"]
    full_name = user["full_name"]
    position = user["position"] or "Student"
    vehicle_type = user["vehicle_type"] or ""

    # Check if user is already inside
    inside = conn.execute(
        "SELECT * FROM currently_inside WHERE student_no=?",
        (student_no,)
    ).fetchone()

    is_inside = inside is not None
    scan_time = datetime.now(_PH_TZ).strftime("%Y-%m-%d %H:%M:%S")

    # ========== ALREADY INSIDE - BLOCK ENTRY ==========
    if is_inside:
        print(f"[RFID] BLOCKED - {full_name} is already inside!")
        print_already_inside_message(full_name)
        # Send with status "already_inside" for kiosk
        send_to_kiosk_api(tag_id, False, "already_inside", "Already Inside")
        conn.close()
        return

    # ========== ENTRY LOGIC (only when NOT inside) ==========
    print(f"[RFID] ENTRY — {full_name} is entering")
    print_welcome_message(full_name)

    conn.execute(
        "INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna, scan_type) VALUES (?,?,?,?,'rfid_entry')",
        (tag_id, scan_time, rssi, antenna)
    )

    is_moto = vehicle_type.lower() in ["motorcycle", "motor", "bike"]
    is_staff = position.lower() in ["faculty", "staff"]
    slot_type = ("faculty" if is_staff else "student") + ("_moto" if is_moto else "_car")

    conn.execute(
        "INSERT OR REPLACE INTO currently_inside (student_no, entry_time, slot_type) VALUES (?, ?, ?)",
        (student_no, scan_time, slot_type)
    )
    conn.commit()
    conn.close()

    print(f"[RFID] ENTRY LOGGED — {full_name} at {scan_time}")
    update_parking(student_no)
    # Send with status "ok" for normal entry
    send_to_kiosk_api(tag_id, False, "ok", "Welcome")


def parse_response(data: bytes):
    tags = []
    i = 0
    while i < len(data) - 23:
        if data[i] == 0xCC and data[i + 1] == 0xFF and data[i + 2] == 0xFF:
            try:
                if len(data) - i >= 22:
                    antenna = data[i + 8]
                    epc = data[i + 9: i + 21].hex().upper()
                    rssi_raw = data[i + 21]
                    rssi = f"-{rssi_raw}dBm"
                    if len(epc) == 24 and epc != "0" * 24 and epc != "F" * 24:
                        tags.append((epc, rssi, str(antenna)))
                        i += 24
                        continue
            except Exception:
                pass
        i += 1
    return tags


def run_continuous(ser):
    print("[INFO] Continuous ENTRY scan running... Press Ctrl+C to stop")
    print("[INFO] Hold tag in front of ENTRY antenna\n")
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
                        save_rfid_scan(tag_id, rssi, ant)
                else:
                    print("[....] Scanning for entry...")
            else:
                print("[....] Scanning for entry... (hold tag near antenna)")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[DONE] Entry scanner stopped.")


def run_single(ser):
    print("\n[READY] Press Enter to scan ENTRY tag, Ctrl+C to quit\n")
    print("NOTE: If already inside, you will see 'ALREADY INSIDE' message\n")
    try:
        while True:
            input(">> Press Enter to scan entry...")
            found = False
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
                            save_rfid_scan(tag_id, rssi, ant)
                        found = True
                        break
                    else:
                        print(f"[WARN] Retrying... ({attempt + 1}/5)")
                else:
                    print(f"[....] No tag, retrying... ({attempt + 1}/5)")
            if not found:
                print("[INFO] Tag not found after 5 attempts")
    except KeyboardInterrupt:
        print("\n[INFO] Stopped.")


def main():
    init_db()
    print("=" * 60)
    print("  MMSU CCIS Parking — RFID ENTRY Scanner ONLY")
    print("  - First scan: ENTRY granted")
    print("  - Second scan: ALREADY INSIDE (blocked)")
    print("  - Use EXIT logger for exiting")
    print("=" * 60 + "\n")

    print("Choose mode:")
    print("  1. Single scan (press Enter each time)")
    print("  2. Continuous scan (auto)")
    choice = input("Enter 1 or 2: ").strip()

    print(f"[SERIAL] Connecting to {PORT}...")
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
    print("\n[INFO] Entry scanner stopped.")


if __name__ == "__main__":
    main()
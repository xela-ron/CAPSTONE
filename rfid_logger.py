"""
UHF RFID Logger + QR Code Scanner - QB0A M-Series Reader (915MHz)
Runs both RFID and Logitech Brio QR scanner simultaneously in one script.
COM3, 57600 baud
"""

import serial
import sqlite3
import time
import threading
import urllib.request
import json
from datetime import datetime

PORT     = "COM3"
BAUDRATE = 57600
DB_FILE  = "rfid_logs.db"

CMD_SINGLE_INVENTORY = bytes([0x7C, 0xFF, 0xFF, 0x20, 0x00, 0x00, 0x66])

# Cooldown tracker — prevents double scan within 6 seconds
recent_scans = {}
COOLDOWN_SECS = 6


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


def update_parking(student_no, label="RFID"):
    try:
        payload = json.dumps({"student_no": student_no}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:5000/api/parking/update",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp   = urllib.request.urlopen(req, timeout=2)
        result = json.loads(resp.read())
        if result.get("status") == "full":
            print(f"[{label}] PARKING FULL — slot: {result.get('slot_type')}")
        else:
            print(f"[{label}] Parking updated — slot: {result.get('slot_type')}")
    except Exception as e:
        print(f"[{label}] Could not update parking: {e}")


def save_rfid_scan(tag_id, rssi="", antenna=""):
    if is_cooldown(tag_id):
        return
    conn = sqlite3.connect(DB_FILE, timeout=30)
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna, scan_type) VALUES (?,?,?,?,'rfid')",
        (tag_id, scan_time, rssi, antenna)
    )
    user = conn.execute(
        "SELECT student_no, full_name FROM users WHERE tag_id=?", (tag_id,)
    ).fetchone()
    conn.commit()
    conn.close()
    name = user[1] if user else "Unregistered"
    print(f"[RFID] {scan_time} | {tag_id} | {name} | RSSI: {rssi}")
    if user:
        update_parking(user[0], label="RFID")


def save_qr_scan(student_no, full_name=""):
    if is_cooldown(student_no):
        print(f"[QR  ] Cooldown — skipping duplicate for {student_no}")
        return
    conn = sqlite3.connect(DB_FILE, timeout=30)
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna, scan_type) VALUES (?,?,?,?,'qr')",
        (student_no, scan_time, "QR", "QR")
    )
    conn.commit()
    conn.close()
    print(f"[QR  ] {scan_time} | {student_no} | {full_name}")
    update_parking(student_no, label="QR ")


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
                        i += 22
                        continue
            except Exception:
                pass
        i += 1
    return tags


def rfid_thread():
    print(f"[RFID] Connecting to {PORT} @ {BAUDRATE} baud...")
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
        print(f"[RFID] Connected! Scanning...\n")
    except Exception as e:
        print(f"[RFID] ERROR: {e} — RFID disabled, QR only mode\n")
        return

    while True:
        try:
            ser.reset_input_buffer()
            ser.write(CMD_SINGLE_INVENTORY)
            buffer = b""
            t_end  = time.time() + 1.5
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
                    print("[RFID] Scanning...")
            else:
                print("[RFID] Scanning...")
            time.sleep(0.2)
        except Exception as e:
            print(f"[RFID] Error: {e}")
            time.sleep(1)


def qr_thread():
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("[QR  ] Missing: pip install opencv-python numpy")
        return

    print("[QR  ] Starting QR scanner...")

    cam_index = 0
    for i in range(5):
        t = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if t.isOpened():
            print(f"[QR  ] Camera {i} found")
            cam_index = i
            t.release()

    cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)

    if not cap.isOpened():
        print("[QR  ] ERROR: Cannot open camera")
        return

    qd = cv2.QRCodeDetector()

    print("[QR  ] Warming up (2 sec)...")
    for _ in range(60):
        cap.grab()
    print("[QR  ] Camera ready!\n")

    last_data    = ""
    last_time    = 0
    banner_txt   = ""
    banner_color = (0, 255, 0)
    banner_until = 0
    frame_count  = 0

    while True:
        cap.grab()
        ret, frame = cap.retrieve()
        if not ret:
            time.sleep(0.05)
            continue

        frame = cv2.flip(frame, 1)
        frame_count += 1
        data = ""

        # Only process every 3rd frame to reduce lag
        if frame_count % 3 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Try 1: raw frame
            data, _, _ = qd.detectAndDecode(frame)

            # Try 2: upscaled — helps blurry/small QR
            if not data:
                big  = cv2.resize(frame, (1280, 960), interpolation=cv2.INTER_CUBIC)
                data, _, _ = qd.detectAndDecode(big)

            # Try 3: darkened — fixes bright phone screen
            if not data:
                dark = cv2.convertScaleAbs(frame, alpha=0.45, beta=0)
                data, _, _ = qd.detectAndDecode(dark)

            # Try 4: darkened + upscaled
            if not data:
                dark_big = cv2.resize(dark, (1280, 960), interpolation=cv2.INTER_CUBIC)
                data, _, _ = qd.detectAndDecode(dark_big)

            # Try 5: CLAHE grayscale
            if not data:
                clahe    = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
                enhanced = clahe.apply(gray)
                data, _, _ = qd.detectAndDecode(
                    cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR))

            # Try 6: threshold
            if not data:
                _, thresh = cv2.threshold(gray, 0, 255,
                                          cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                data, _, _ = qd.detectAndDecode(
                    cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR))

        now = time.time()

        if data and (data != last_data or now - last_time > COOLDOWN_SECS):
            last_data = data
            last_time = now
            print(f"[QR  ] Decoded: {data}")

            student_no = data.strip()
            conn = sqlite3.connect(DB_FILE, timeout=30)
            user = conn.execute(
                "SELECT full_name FROM users WHERE student_no=?", (student_no,)
            ).fetchone()
            conn.close()

            if user:
                save_qr_scan(student_no, user[0])
                banner_txt   = f"GRANTED: {user[0]}"
                banner_color = (0, 220, 0)
                print(f"[QR  ] Granted: {user[0]}")
            else:
                banner_txt   = "UNKNOWN — NOT REGISTERED"
                banner_color = (0, 0, 220)
                print(f"[QR  ] Unknown: {student_no}")
            banner_until = now + 4

        # Display
        if now < banner_until:
            cv2.rectangle(frame, (0,0), (frame.shape[1], 60), (0,0,0), -1)
            cv2.putText(frame, banner_txt, (10,42),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, banner_color, 2)
        else:
            cv2.rectangle(frame, (0,0), (frame.shape[1], 40), (0,0,0), -1)
            cv2.putText(frame, "MMSU CCIS  |  Show QR to camera",
                        (10,28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200,200,200), 1)

        h, w = frame.shape[:2]
        cx, cy, hs = w//2, h//2, 120
        cv2.rectangle(frame, (cx-hs, cy-hs), (cx+hs, cy+hs), (0,255,0), 2)

        cv2.imshow("MMSU CCIS QR Scanner  [Q = quit]", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("[QR  ] Camera closed.")
def main():
    init_db()
    print("=" * 55)
    print("  MMSU CCIS Parking — Gate Scanner v2")
    print("  RFID + QR running simultaneously")
    print("=" * 55 + "\n")

    # RFID runs in background thread
    t = threading.Thread(target=rfid_thread, daemon=True)
    t.start()
    time.sleep(1)

    # QR runs in main thread (OpenCV requirement)
    qr_thread()

    print("\n[INFO] Scanner stopped.")


if __name__ == "__main__":
    main()
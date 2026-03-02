"""
UHF RFID Logger - QB0A M-Series Reader (915MHz)
Fixed EPC parser — matches seller software output exactly.
COM3, 57600 baud
"""

import serial
import sqlite3
import time
from datetime import datetime

PORT     = "COM3"
BAUDRATE = 57600
DB_FILE  = "rfid_logs.db"

# Confirmed trigger command from demo software RCP CMD log
CMD_SINGLE_INVENTORY = bytes([0x7C, 0xFF, 0xFF, 0x20, 0x00, 0x00, 0x66])


def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rfid_scans (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_id    TEXT NOT NULL,
            scan_time TEXT NOT NULL,
            rssi      TEXT,
            antenna   TEXT
        )
    """)
    for col in ["rssi", "antenna"]:
        try:
            conn.execute(f"ALTER TABLE rfid_scans ADD COLUMN {col} TEXT")
        except Exception:
            pass
    conn.commit()
    conn.close()
    print(f"[DB] Database ready: {DB_FILE}")


def save_scan(tag_id, rssi="", antenna=""):
    conn = sqlite3.connect(DB_FILE)
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO rfid_scans (tag_id, scan_time, rssi, antenna) VALUES (?, ?, ?, ?)",
        (tag_id, scan_time, rssi, antenna)
    )
    conn.commit()
    conn.close()
    print(f"[SCAN] {scan_time} | Tag: {tag_id} | RSSI: {rssi}")


def parse_response(data: bytes):
    """
    Parse QB0A RCP RSP response packets.

    Confirmed packet structure from RAW + seller software comparison:
    CC FF FF 20 02 10 00 30 00 [ant] [PC1] [PC2] [EPC 12 bytes] [RSSI] ...
    Byte  0-2  : CC FF FF       = header
    Byte  3    : 20             = address
    Byte  4    : 02             = flag
    Byte  5    : 10             = cmd code (inventory response)
    Byte  6-7  : 00 30          = data length
    Byte  8    : 00             = antenna
    Byte  9-10 : PC bytes (e.g. 01 02) — NOT part of EPC, skip these
    Byte 11-22 : EPC (12 bytes = 24 hex chars) — matches seller software
    Byte 23    : RSSI

    Seller software showed: 0102030405060708 09 00A004
    RAW was:  ...00 [01 02] [03 04 05 06 07 08 09 00 A0 04] [C3 40]
                ant  PC1 PC2   EPC starts here (12 bytes)    RSSI checksum
    """
    tags = []
    i = 0
    while i < len(data) - 23:
        if data[i] == 0xCC and data[i+1] == 0xFF and data[i+2] == 0xFF:
            try:
                if len(data) - i >= 22:
                    antenna  = data[i + 8]
                    # Skip 2 PC bytes (i+9, i+10), EPC starts at i+11
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


def run_continuous(ser):
    """Keep triggering continuously for fast reliable scanning."""
    print("[INFO] Continuous scan running... Press Ctrl+C to stop")
    print("[INFO] Hold tag 0.5-2m in front of antenna\n")
    seen_tags = set()
    try:
        while True:
            ser.reset_input_buffer()
            ser.write(CMD_SINGLE_INVENTORY)

            # Collect response for up to 1.5 seconds
            buffer = b""
            t_end = time.time() + 1.5
            while time.time() < t_end:
                if ser.in_waiting > 0:
                    buffer += ser.read(ser.in_waiting)
                time.sleep(0.01)

            if buffer and len(buffer) > 8:
                # Only print RAW if it has actual tag data
                if len(buffer) > 10:
                    print(f"[RAW] {buffer.hex().upper()}")
                tags = parse_response(buffer)
                if tags:
                    for tag_id, rssi, ant in tags:
                        save_scan(tag_id, rssi, ant)
                        seen_tags.add(tag_id)
            else:
                print("[....] Scanning... (hold tag near antenna)")

            # Short pause between triggers
            time.sleep(0.2)

    except KeyboardInterrupt:
        print(f"\n[DONE] Stopped. Unique tags this session: {len(seen_tags)}")
        for t in seen_tags:
            print(f"  -> {t}")


def run_single(ser):
    """Press Enter each time — sends trigger 3 times to ensure detection."""
    print("\n[READY] Press Enter to scan, Ctrl+C to quit\n")
    try:
        while True:
            input(">> Press Enter to scan...")
            found = False
            # Try up to 5 times to detect the tag
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
                    print(f"[RAW] {buffer.hex().upper()}")
                    tags = parse_response(buffer)
                    if tags:
                        for tag_id, rssi, ant in tags:
                            save_scan(tag_id, rssi, ant)
                        found = True
                        break
                    else:
                        print(f"[WARN] Response too short, retrying... ({attempt+1}/5)")
                else:
                    print(f"[....] No tag detected, retrying... ({attempt+1}/5)")

            if not found:
                print("[INFO] Tag not found after 5 attempts — make sure tag is directly in front of antenna")
    except KeyboardInterrupt:
        print("\n[INFO] Stopped.")


def main():
    init_db()
    print(f"[SERIAL] Connecting to {PORT} at {BAUDRATE} baud...")
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
        print(f"[SERIAL] Connected!\n")
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    print("Choose scan mode:")
    print("  1. Single scan (press Enter each time)")
    print("  2. Continuous scan (auto triggers every second)")
    choice = input("Enter 1 or 2: ").strip()

    if choice == "1":
        run_single(ser)
    else:
        run_continuous(ser)

    ser.close()


if __name__ == "__main__":
    main()
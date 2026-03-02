"""
RFID Tag ID Diagnostic Tool
Scans a tag and shows ALL possible EPC parse positions
so you can match against the seller software output.
"""

import serial
import time

PORT     = "COM3"
BAUDRATE = 57600
CMD      = bytes([0x7C, 0xFF, 0xFF, 0x20, 0x00, 0x00, 0x66])

def diagnose(raw: bytes):
    print("\n" + "="*60)
    print(f"RAW HEX  : {raw.hex().upper()}")
    print(f"RAW LEN  : {len(raw)} bytes")
    print("="*60)
    print("\nAll possible 12-byte EPC positions:")
    print(f"{'Offset':<8} {'EPC (24 hex chars)':<26} {'Readable?'}")
    print("-"*55)
    for i in range(len(raw) - 11):
        chunk = raw[i:i+12]
        epc   = chunk.hex().upper()
        valid = "YES <---" if (epc != "0"*24 and epc != "F"*24
                               and not all(b == raw[i] for b in chunk)) else ""
        print(f"  [{i:02d}]   {epc}   {valid}")
    print("\nCompare the YES rows against your seller software EPC.")
    print("Tell me which offset matches and I'll fix the code!")

def main():
    print(f"Connecting {PORT} @ {BAUDRATE}...")
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=2)
    except Exception as e:
        print(f"ERROR: {e}")
        return

    print("Ready! Press Enter to scan a tag (hold tag near antenna)\n")
    try:
        while True:
            input(">> Press Enter to scan...")
            ser.reset_input_buffer()
            ser.write(CMD)
            time.sleep(0.7)
            buf = b""
            while ser.in_waiting:
                buf += ser.read(ser.in_waiting)
                time.sleep(0.05)
            if buf:
                diagnose(buf)
            else:
                print("No response — make sure tag is in range")
    except KeyboardInterrupt:
        print("\nDone.")
    ser.close()

if __name__ == "__main__":
    main()
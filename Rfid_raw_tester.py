"""
QB0A Raw Command Tester
Tests the exact commands seen in the demo software log.
Run this with the demo software CLOSED.
"""

import serial
import time

PORT     = "COM3"
BAUDRATE = 57600

# Exact packets captured from the demo software RCP log
# From screenshot: "CC FF FF 20 00 02 00 03 11" = Single Inventory
# From screenshot: "CC FF FF 20 02 10 00 30 00 01 02 03 04 05 06 07 08 09 00 A0 04 C9 3A" = Loop

CMDS = [
    ("Single Inventory (from demo log)",
     bytes.fromhex("CCFFFF200002000311")),

    ("Loop Inventory (from demo log)",
     bytes.fromhex("CCFFFF2002100030000102030405060708090 0A004C93A".replace(" ",""))),

    ("Single Inventory v2",
     bytes.fromhex("CCFFFF20000200030F")),

    ("Get Version / Ping",
     bytes.fromhex("CCFFFF200002000301")),

    ("Single Inventory alternate",
     bytes.fromhex("CCFFFF200003000101FF")),
]

def test_cmd(ser, name, cmd):
    print(f"\n{'='*50}")
    print(f"CMD : {name}")
    print(f"HEX : {cmd.hex().upper()}")
    ser.reset_input_buffer()
    ser.write(cmd)
    time.sleep(1.5)  # wait longer for reader to respond
    response = b""
    # Read all available bytes
    while ser.in_waiting > 0:
        response += ser.read(ser.in_waiting)
        time.sleep(0.1)
    if response:
        print(f"✅ RESPONSE HEX : {response.hex().upper()}")
        print(f"   RESPONSE LEN : {len(response)} bytes")
        print(f"   RESPONSE RAW : {response}")
        return True
    else:
        print(f"❌ No response")
        return False

def main():
    print(f"Connecting to {PORT} at {BAUDRATE}...")
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=2)
        print(f"✅ Port opened!\n")
    except Exception as e:
        print(f"❌ ERROR: {e}")
        print("Make sure the demo software is CLOSED before running this!")
        return

    print("👉 Hold your UHF tag 0.5 to 2 meters from the reader antenna")
    print("   Testing commands now...\n")

    for name, cmd in CMDS:
        success = test_cmd(ser, name, cmd)
        if success:
            print(f"\n🎉 WORKING! Command: {name}")
            print(f"   Send this hex to trigger the reader: {cmd.hex().upper()}")
            break
        time.sleep(0.5)

    print("\n" + "="*50)
    print("If nothing worked, try this:")
    print("1. Open demo software → do a Single Inventory scan")
    print("2. Look at the RCP Packet(HEX) log at the bottom")
    print("3. Copy the exact hex from 'RCP CMD' row and share it here")
    ser.close()

if __name__ == "__main__":
    main()
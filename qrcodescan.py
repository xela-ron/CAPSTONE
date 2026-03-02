"""
QR Code Scanner - Logitech Brio Webcam
Uses OpenCV + pyzbar to detect and decode QR codes in real-time.
Logs results to SQLite DB (same rfid_logs.db used by RFID logger).

Install dependencies:
    pip install opencv-python pyzbar
    (Windows also needs: https://sourceforge.net/projects/zbar/ )

TIPS FOR BEST SCANNING:
  - Hold QR code 20-30cm (8-12 inches) from the camera
  - Avoid glare/reflection - tilt phone slightly
  - Make sure QR code is well lit
"""

import cv2
import sqlite3
import time
from pyzbar.pyzbar import decode
from datetime import datetime

DB_FILE     = "rfid_logs.db"
CAMERA_ID   = 0
WINDOW_NAME = "QR Code Scanner - Press Q to quit"

# Fixed display window size (change if too big/small for your screen)
DISPLAY_WIDTH  = 800
DISPLAY_HEIGHT = 600


def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS qr_logs (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            data      TEXT
        )
    """)
    conn.commit()
    return conn


def log_qr(conn, data):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO qr_logs (timestamp, data) VALUES (?, ?)", (ts, data))
    conn.commit()
    print(f"[{ts}] QR SCANNED: {data}")


def preprocess(frame):
    """Improve frame quality for better QR detection."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Auto brightness/contrast stretch
    min_val, max_val = gray.min(), gray.max()
    if max_val > min_val:
        gray = cv2.convertScaleAbs(gray, alpha=255.0 / (max_val - min_val),
                                   beta=-min_val * 255.0 / (max_val - min_val))

    # Sharpen
    kernel = cv2.getGaussianKernel(0, 1.5)
    blurred = cv2.sepFilter2D(gray, -1, kernel, kernel)
    sharpened = cv2.addWeighted(gray, 1.8, blurred, -0.8, 0)

    # Denoise
    denoised = cv2.fastNlMeansDenoising(sharpened, h=10)

    return denoised


def main():
    conn = init_db()

    print(f"Opening camera {CAMERA_ID}, please wait...")
    cap = cv2.VideoCapture(CAMERA_ID, cv2.CAP_DSHOW)

    if not cap.isOpened():
        print(f"ERROR: Cannot open camera (ID={CAMERA_ID})")
        print("Try changing CAMERA_ID to 1 or 2 at the top of the script.")
        return

    # Resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    # Exposure & brightness
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
    cap.set(cv2.CAP_PROP_BRIGHTNESS, 160)
    cap.set(cv2.CAP_PROP_CONTRAST, 160)
    cap.set(cv2.CAP_PROP_GAIN, 0)

    # Autofocus
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
    cap.set(cv2.CAP_PROP_FOCUS, 30)   # 30 = medium-near range, better than 0 for Brio

    # Fix aspect ratio window
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, DISPLAY_WIDTH, DISPLAY_HEIGHT)

    print("Warming up camera (3 seconds)...")
    time.sleep(3)

    last_scan = {}
    COOLDOWN  = 3.0

    print("Camera ready! Hold QR code 20-30cm from camera. Press Q to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("ERROR: Failed to read frame.")
            break

        # Preprocess for better detection
        processed = preprocess(frame)

        # Try decode on both original and processed
        qr_codes = decode(frame) or decode(processed)

        for qr in qr_codes:
            data = qr.data.decode("utf-8")
            now  = time.time()

            if data not in last_scan or (now - last_scan[data]) > COOLDOWN:
                last_scan[data] = now
                log_qr(conn, data)

            # Draw bounding box on display frame
            pts = qr.polygon
            if len(pts) == 4:
                for i in range(4):
                    p1 = (pts[i].x,           pts[i].y)
                    p2 = (pts[(i + 1) % 4].x, pts[(i + 1) % 4].y)
                    cv2.line(frame, p1, p2, (0, 255, 0), 3)

            # Label with background
            x, y = qr.rect.left, qr.rect.top - 12
            label = data[:50]
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (x, max(y - th - 4, 0)), (x + tw + 4, max(y + 6, th + 6)), (0, 200, 0), -1)
            cv2.putText(frame, label, (x + 2, max(y, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # Overlay instructions
        avg_brightness = frame.mean()
        status_color = (0, 255, 0) if 80 < avg_brightness < 200 else (0, 100, 255)
        cv2.putText(frame, f"Brightness: {avg_brightness:.0f}  |  Hold QR 20-30cm away  |  Q = quit",
                    (10, frame.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_color, 1)

        # Center guide box
        h, w = frame.shape[:2]
        bx1, by1 = w // 4, h // 4
        bx2, by2 = 3 * w // 4, 3 * h // 4
        cv2.rectangle(frame, (bx1, by1), (bx2, by2), (0, 200, 255), 1)
        cv2.putText(frame, "Point QR here", (bx1 + 5, by1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)

        cv2.imshow(WINDOW_NAME, frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    conn.close()
    print("Scanner stopped.")


if __name__ == "__main__":
    main()
"""Quick test - take a screenshot of your QR code and run this"""
import cv2
import numpy as np

try:
    from pyzbar import pyzbar
    HAS_PYZBAR = True
except:
    HAS_PYZBAR = False

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)

print("Press SPACE to capture and test QR decode")
print("Press Q to quit\n")

while True:
    ret, frame = cap.read()
    if not ret:
        continue
    frame = cv2.flip(frame, 1)

    cv2.putText(frame, "Press SPACE to scan QR", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
    cv2.imshow("QR Test", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord(' '):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        print("\n--- TESTING DECODE ---")

        # Test cv2
        qd = cv2.QRCodeDetector()
        d, _, _ = qd.detectAndDecode(frame)
        print(f"cv2 QRCodeDetector: '{d}'")

        # Test pyzbar
        if HAS_PYZBAR:
            from pyzbar import pyzbar, ZBarSymbol
            codes = pyzbar.decode(gray, symbols=[ZBarSymbol.QRCODE])
            print(f"pyzbar result: {[c.data for c in codes]}")

            # Try all rotations
            for angle in [0, 90, 180, 270]:
                M = cv2.getRotationMatrix2D((320,240), angle, 1)
                rot = cv2.warpAffine(gray, M, (640,480))
                codes = pyzbar.decode(rot, symbols=[ZBarSymbol.QRCODE])
                if codes:
                    print(f"pyzbar at {angle}deg: {codes[0].data}")
                    break

        # Save captured frame for inspection
        cv2.imwrite("qr_capture.png", frame)
        print("Saved qr_capture.png")
        print("--- DONE ---\n")

cap.release()
cv2.destroyAllWindows()

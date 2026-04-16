import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522
from adafruit_fingerprint import Adafruit_Fingerprint
from RPLCD.i2c import CharLCD
import serial
import time
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime

# ==========================================================
# 1. HARDWARE PIN MAPPING & SETUP
# ==========================================================
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

BUZZER_PIN = 5   
LED_GREEN = 23   
LED_RED = 24     

GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.setup(LED_GREEN, GPIO.OUT)
GPIO.setup(LED_RED, GPIO.OUT)

rfid = SimpleMFRC522()
lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1, cols=16, rows=2, dotsize=8)
uart = serial.Serial("/dev/serial0", baudrate=57600, timeout=1) 
finger = Adafruit_Fingerprint(uart)

# ==========================================================
# 2. FIREBASE CLOUD CONFIGURATION
# ==========================================================
cred = credentials.Certificate("service-account-key.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
})

current_mode = "Attendance"

def on_control_change(event):
    global current_mode
    if event.data and isinstance(event.data, dict):
        if 'mode' in event.data:
            current_mode = event.data['mode']
            lcd.clear()
            lcd.write_string("Mode Changed:")
            lcd.crlf()
            lcd.write_string(current_mode)
            time.sleep(1)

db.reference('/control').listen(on_control_change)

# ==========================================================
# 3. HELPER FUNCTIONS
# ==========================================================
def display_lcd(line1, line2=""):
    lcd.clear()
    lcd.write_string(line1[:16])
    if line2:
        lcd.crlf()
        lcd.write_string(line2[:16])

def feedback(status):
    if status == "success":
        GPIO.output(LED_GREEN, GPIO.HIGH)
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(0.2)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        GPIO.output(LED_GREEN, GPIO.LOW)
    elif status == "error":
        GPIO.output(LED_RED, GPIO.HIGH)
        for _ in range(3): 
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(0.1)
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(0.1)
        GPIO.output(LED_RED, GPIO.LOW)

# ==========================================================
# 4. MAIN SYSTEM LOOP
# ==========================================================
display_lcd("System Ready", "Waiting...")
time.sleep(2)

try:
    while True:
        if current_mode == "Attendance":
            display_lcd("Scan RFID Card", "To Check-In/Out")
            card_id = rfid.read_id_no_block()

            if card_id:
                uid_str = str(card_id).strip()
                display_lcd("Card Detected", "Validating...")

                all_cards = db.reference('/cards').get() or {}
                match = next((v for v in all_cards.values() if str(v.get('card_id')) == uid_str), None)

                if match:
                    name = match.get('name', 'Unknown')
                    cloud_fp_id = str(match.get('fingerprint_id', ''))
                    display_lcd(f"Hi {name[:10]}", "Place Finger...")

                    start_t = time.time()
                    fp_success = False

                    while time.time() - start_t < 5: 
                        if finger.get_image() == 0x00: 
                            if finger.image_2_tz(1) == 0x00 and finger.finger_search() == 0x00:
                                if str(finger.finger_id) == cloud_fp_id:
                                    fp_success = True
                                    break
                                else:
                                    display_lcd("FP Mismatch!", "Access Denied")
                                    feedback("error")
                                    time.sleep(2)
                                    break
                            else:
                                display_lcd("Not Found!", "Access Denied")
                                feedback("error")
                                time.sleep(2)
                                break
                        time.sleep(0.1)

                    if fp_success:
                        display_lcd("Access Granted", "Logged to Cloud")
                        feedback("success")
                        
                        date_str = datetime.now().strftime("%Y-%m-%d")
                        db.reference(f'/attendance/{date_str}').push().set({
                            'student_id': match['student_id'],
                            'name': name,
                            'status': "present",
                            'timestamp': int(time.time()),
                            'verification_method': "RFID + FP 2FA"
                        })
                        time.sleep(2)
                    elif not fp_success and (time.time() - start_t >= 5):
                        display_lcd("FP Timeout", "Try Again")
                        feedback("error")
                        time.sleep(2)
                else:
                    display_lcd("Unknown Card!", "Access Denied")
                    feedback("error")
                    time.sleep(2)
            else:
                time.sleep(0.2) 

        elif current_mode == "Enrollment":
            display_lcd("Enrollment Mode", "Scan New Card")
            card_id = rfid.read_id_no_block()

            if card_id:
                uid_str = str(card_id).strip()
                display_lcd("Card Scanned!", f"UID:{uid_str[-8:]}")
                feedback("success")
                time.sleep(1)

                if finger.read_templates() == 0x00:
                    used_slots = finger.templates
                    empty_slot = -1
                    for i in range(1, 128):
                        if i not in used_slots:
                            empty_slot = i
                            break

                    if empty_slot != -1:
                        display_lcd("Place Finger", f"Slot: {empty_slot}")
                        while finger.get_image() != 0x00: 
                            time.sleep(0.1)
                        finger.image_2_tz(1)
                        feedback("success")

                        display_lcd("Remove Finger", "")
                        while finger.get_image() != 0x02: 
                            time.sleep(0.1)

                        display_lcd("Place Again", "")
                        while finger.get_image() != 0x00: 
                            time.sleep(0.1)
                        finger.image_2_tz(2)

                        if finger.create_model() == 0x00 and finger.store_model(empty_slot) == 0x00:
                            feedback("success")
                            display_lcd("Success!", "Check Web App")
                            
                            # 🚀 NEW: 把数据推送到云端的“暂存区 (pending_registration)”
                            db.reference('/pending_registration').set({
                                'rfid': uid_str,
                                'fp_id': empty_slot,
                                'timestamp': int(time.time())
                            })
                            print(f"👉 Hardware synced. Open Web App and click 'Fetch Scanned Card'.")
                            time.sleep(4)
                        else:
                            display_lcd("FP Error", "Try Again")
                            feedback("error")
                            time.sleep(2)
                    else:
                        display_lcd("Sensor Full!", "Cannot Enroll")
                        feedback("error")
                        time.sleep(2)
            else:
                time.sleep(0.2)

except KeyboardInterrupt:
    display_lcd("System Offline", "Goodbye!")
    GPIO.cleanup()

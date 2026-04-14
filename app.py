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
# 1. HARDWARE PIN MAPPING (Based on your Configuration Table)
# ==========================================================
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Grove Buzzer (D5 on Grove Base Hat -> BCM 5)
BUZZER_PIN = 5  
# LEDs (PIN 16 -> BCM 23, PIN 18 -> BCM 24)
LED_GREEN = 23
LED_RED = 24

GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.setup(LED_GREEN, GPIO.OUT)
GPIO.setup(LED_RED, GPIO.OUT)

# Initialize Hardware Modules
rfid = SimpleMFRC522()
lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1, cols=16, rows=2, dotsize=8)
uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1) # AS608 Fingerprint
finger = Adafruit_Fingerprint(uart)

# ==========================================================
# 2. FIREBASE CLOUD CONFIGURATION
# ==========================================================
cred = credentials.Certificate("service-account-key.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://bmit2123-iot-71ac4-default-rtdb.asia-southeast1.firebasedatabase.app'
})

control_ref = db.reference('/control')
cards_ref = db.reference('/cards')

system_state = {"mode": "Attendance", "is_locked": False}

# ==========================================================
# 3. HARDWARE FEEDBACK FUNCTIONS (LCD, LED, Buzzer)
# ==========================================================
def display_lcd(line1, line2=""):
    lcd.clear()
    lcd.write_string(line1)
    if line2:
        lcd.crlf()
        lcd.write_string(line2)

def feedback(status):
    if status == "success":
        GPIO.output(LED_GREEN, GPIO.HIGH)
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(0.2)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        time.sleep(0.8)
        GPIO.output(LED_GREEN, GPIO.LOW)
    elif status == "error":
        GPIO.output(LED_RED, GPIO.HIGH)
        for _ in range(3): # 3 quick beeps for error
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(0.1)
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(0.1)
        GPIO.output(LED_RED, GPIO.LOW)

def log_attendance(student_id, name):
    date_str = datetime.now().strftime("%Y-%m-%d")
    db.reference(f'/attendance/{date_str}').push().set({
        'student_id': student_id,
        'name': name,
        'status': "present",
        'timestamp': int(time.time()),
        'verification_method': "RFID_Fingerprint_2FA"
    })
    print(f"✅ Logged: {name}")

# ==========================================================
# 4. CLOUD LISTENER (Responds to your Streamlit App)
# ==========================================================
def on_control_change(event):
    global system_state
    if event.data:
        if event.path == "/trigger_buzzer" and event.data is True:
            display_lcd("Remote Alert!", "Buzzer Triggered")
            feedback("error") # Use error beep pattern for alert
        if isinstance(event.data, dict):
            system_state["mode"] = event.data.get("mode", system_state["mode"])
            system_state["is_locked"] = event.data.get("is_locked", system_state["is_locked"])
            display_lcd(f"Mode: {system_state['mode']}")

control_ref.listen(on_control_change)

# ==========================================================
# 5. MAIN 2FA LOOP (RFID -> Fingerprint)
# ==========================================================
try:
    display_lcd("IoT System", "Starting...")
    time.sleep(2)
    
    while True:
        if system_state["is_locked"]:
            display_lcd("SYSTEM LOCKED", "See Admin")
            time.sleep(2)
            continue

        if system_state["mode"] == "Attendance":
            display_lcd("Scan RFID Card", "To Check-In/Out")
            card_id, _ = rfid.read()
            card_id = str(card_id).strip()
            display_lcd("Card Detected", "Validating...")
            
            # 1. Validate RFID
            all_cards = cards_ref.get() or {}
            match = next((v for v in all_cards.values() if v.get('card_id') == card_id), None)
            
            if match:
                display_lcd(f"Hi {match['name'][:10]}", "Place Finger...")
                time.sleep(1)
                
                # 2. Trigger Fingerprint Verification
                if finger.get_image() == 0x00 and finger.image_2_tz(1) == 0x00 and finger.finger_search() == 0x00:
                    if str(finger.finger_id) == str(match.get('fingerprint_id')):
                        display_lcd("Access Granted", "Logged to Cloud")
                        feedback("success")
                        log_attendance(match['student_id'], match['name'])
                    else:
                        display_lcd("FP Mismatch!", "Access Denied")
                        feedback("error")
                else:
                    display_lcd("FP Error", "Try Again")
                    feedback("error")
            else:
                display_lcd("Unknown Card!", "Access Denied")
                feedback("error")
            
            time.sleep(2) # Cooldown before next scan

        elif system_state["mode"] == "Enrollment":
            display_lcd("Enrollment Mode", "Scan New Card")
            card_id, _ = rfid.read()
            display_lcd("Card UID:", str(card_id))
            feedback("success")
            print(f"✨ Copy this UID to Web App: {card_id}")
            time.sleep(3)

except KeyboardInterrupt:
    display_lcd("System Offline", "")
    GPIO.cleanup()

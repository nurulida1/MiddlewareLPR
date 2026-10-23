
import serial
import time

PORT = "COM60"
BAUDRATE = 9600

command = b"001DIS=HII INTELLIGENCE2200\r\n"

print("Sending:", repr(command))
print("HEX:", command.hex(" ").upper())

with serial.Serial(PORT, BAUDRATE, timeout=1) as led:
    time.sleep(0.2)
    written = led.write(command)
    led.flush()
    print(f"Bytes written: {written}/{len(command)}")

print("Test complete.")

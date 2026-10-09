
import serial
import time

PORT = "COM3"       # Change to your actual FTDI COM port
BAUD_RATE = 9600

TEST_MESSAGE = b"TEST123\r\n"

try:
    with serial.Serial(
        port=PORT,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=1,
        write_timeout=2,
    ) as ser:

        print(f"Connected to {PORT}")
        print(f"Baud rate: {BAUD_RATE}")
        print("Preparing test transmission...")

        time.sleep(0.2)

        bytes_sent = ser.write(TEST_MESSAGE)
        ser.flush()

        print(f"Write completed: {bytes_sent} bytes")
        print(f"Sent bytes: {TEST_MESSAGE!r}")
        print("No receiving device is connected.")
        print("Transmission at the remote end is NOT verified.")

except serial.SerialException as exc:
    print(f"Serial port error: {exc}")

except Exception as exc:
    print(f"Unexpected error: {exc}")
"""
CUSTronics LED Simulation Test
------------------------------
Standalone simulator based on the current led.py command format.

- Does NOT open COM61.
- Does NOT send data to the physical LED.
- Displays two 8-character rows in the terminal.
- Logs ASCII and HEX for display and clear commands.
- Shows the message for DISPLAY_SECONDS, then simulates blanking.
"""

import logging
import time

# Match current led.py settings
ROW_WIDTH = 8
FRAME_WIDTH = 16
BAUDRATE = 9600
DEFAULT_WELCOME_MESSAGE = "WELCOME"
GREEN_SUFFIX = "1100"
YELLOW_SUFFIX = "2200"
CLEAR_SUFFIX = "0000"

DISPLAY_SECONDS = 10
CLEAR_DISPLAY_SECONDS = 1

# Test plate can be changed here
TEST_PLATE = "CDP 2709"
TEST_WELCOME = "WELCOME"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("led_simulation")


def shorten_plate(plate):
    plate = str(plate).strip().upper()

    if plate.startswith("PUTRAJAYA"):
        number = plate[len("PUTRAJAYA"):].strip()
        shortened = "PUT" + number
        if len(shortened) <= ROW_WIDTH:
            logger.info("Shortened plate: %s -> %s", plate, shortened)
            return shortened

    if len(plate) <= ROW_WIDTH:
        return plate

    shortened = plate[:ROW_WIDTH]
    logger.warning(
        "Plate exceeds %d characters: %s -> %s",
        ROW_WIDTH,
        plate,
        shortened,
    )
    return shortened


def build_display_message(welcome, plate):
    welcome = str(welcome).strip().upper()[:ROW_WIDTH]
    plate = shorten_plate(plate)

    if not welcome.isascii() or not plate.isascii():
        raise ValueError("Display messages must contain ASCII characters.")

    first_part = welcome.ljust(ROW_WIDTH)
    second_part = plate.ljust(ROW_WIDTH)
    combined = first_part + second_part

    logger.info("FIRST 8 CHARACTERS: %r", first_part)
    logger.info("NEXT 8 CHARACTERS:  %r", second_part)
    logger.info("COMBINED MESSAGE:   %r", combined)
    return combined


def build_command(message, colour_suffix):
    if not message.isascii():
        raise ValueError("Message must contain ASCII characters.")

    if colour_suffix not in (GREEN_SUFFIX, YELLOW_SUFFIX, CLEAR_SUFFIX):
        raise ValueError(f"Unsupported suffix: {colour_suffix}")

    message = message[:FRAME_WIDTH].ljust(FRAME_WIDTH)
    command = f"001DIS={message}{colour_suffix}\r\n"
    return command.encode("ascii")


def log_command(label, command_bytes):
    logger.info("=" * 60)
    logger.info("%s ASCII: %r", label, command_bytes.decode("ascii"))
    logger.info(
        "%s HEX: %s",
        label,
        command_bytes.hex(" ").upper(),
    )
    logger.info("%s BYTE COUNT: %d", label, len(command_bytes))


def render_screen(row1, row2, status):
    # Terminal-only visualization. It does not control the physical LED.
    print("\n" + "=" * 34)
    print("       CUSTronics LED SIMULATOR")
    print("=" * 34)
    print(f"Status: {status}")
    print("+------------------+")
    print(f"|{row1[:ROW_WIDTH].ljust(ROW_WIDTH)}|")
    print(f"|{row2[:ROW_WIDTH].ljust(ROW_WIDTH)}|")
    print("+------------------+")
    print("Line 1 / Line 2 are simulated only.")
    print("=" * 34 + "\n")


def simulate_display(plate, welcome=DEFAULT_WELCOME_MESSAGE):
    combined = build_display_message(welcome, plate)
    display_command = build_command(combined, GREEN_SUFFIX)
    log_command("DISPLAY COMMAND", display_command)

    row1 = combined[:ROW_WIDTH]
    row2 = combined[ROW_WIDTH:FRAME_WIDTH]
    render_screen(row1, row2, f"DISPLAYING for {DISPLAY_SECONDS} seconds")

    logger.info(
        "[SIMULATION] Would display plate=%s on virtual LED.",
        plate,
    )
    time.sleep(DISPLAY_SECONDS)

    # Mirror the current led.py clear command: 16 spaces + 0000 + CR/LF.
    clear_command = build_command("", CLEAR_SUFFIX)
    log_command("CLEAR COMMAND", clear_command)
    logger.info("[SIMULATION] Clear command requested; no bytes sent to COM61.")

    render_screen("", "", "BLANK")
    time.sleep(CLEAR_DISPLAY_SECONDS)


def main():
    print("CUSTronics LED Simulation Test")
    print("Safety: this file never opens COM61 and never sends serial data.")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            plate = input(
                f"Enter plate to simulate (Enter = {TEST_PLATE}, q = quit): "
            ).strip()

            if plate.lower() == "q":
                break
            if not plate:
                plate = TEST_PLATE

            simulate_display(plate, TEST_WELCOME)

    except KeyboardInterrupt:
        print("\nSimulation stopped.")

    logger.info("LED simulation test finished.")


if __name__ == "__main__":
    main()

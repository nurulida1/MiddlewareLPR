"""
CUSTronics 2-row x 8-character LED controller.

Hardware:
- Dimensions: 690 x 370 x 80 mm
- Character height: 110 mm
- Display: 2 rows x 8 characters
- Colours: RED and GREEN
- Communication: RS485
- Power supply: AC 240V

IMPORTANT:
Physical LED output remains blocked until the vendor confirms
the RS485 protocol, row addressing, colour commands and framing.

DISPLAY OPTIONS:
- FIXED_MESSAGES: existing behaviour; IN uses WELCOME and OUT uses
  THANK YOU on Row 2, while long Row 1 messages scroll.
- WRAP_OVERFLOW: no hardcoded greeting and no scrolling on either row.
  Row 1 shows up to 8 characters in RED; Row 2 shows the next 8 in RED.
  Text after 16 characters is truncated. A message that fits on Row 1
  leaves Row 2 blank.
- Physical RS485 protocol must still be confirmed with CUSTronics.
"""

import logging
import queue
import tkinter as tk
from threading import Thread

import serial
from serial import SerialException

from config import (
    LED_SIMULATION_MODE,
    SERIAL_PORT,
    BAUD_RATE,
    DATA_BITS,
    PARITY,
    STOP_BITS,
    SERIAL_TIMEOUT,
)


# ============================================================
# HARDWARE / DISPLAY SETTINGS
# ============================================================

WINDOW_TITLE = "CUSTronics 2 x 8 LED Simulator"

PANEL_WIDTH_MM = 690
PANEL_HEIGHT_MM = 370
PANEL_DEPTH_MM = 80
CHARACTER_HEIGHT_MM = 110

ROWS = 2
COLUMNS = 8
MAX_DISPLAY_CHARACTERS = COLUMNS

BACKGROUND = "#050505"
PANEL_BACKGROUND = "#101010"

LED_RED = "#FF2020"
LED_RED_GLOW = "#8B0000"

LED_GREEN = "#39FF65"
LED_GREEN_GLOW = "#126B2A"

LED_OFF = "#292929"
TEXT_GREY = "#777777"

WINDOW_WIDTH = 900
WINDOW_HEIGHT = 420

DOT_RADIUS = 4
DOT_SPACING = 13

# Move the scrolling message one character every 250 ms.
SCROLL_INTERVAL_MS = 250

# Select one display behaviour:
# "FIXED_MESSAGES" = existing IN WELCOME / OUT THANK YOU behaviour
# "WRAP_OVERFLOW"  = no greeting or scrolling; both rows are RED
DISPLAY_MODE = "FIXED_MESSAGES"
VALID_DISPLAY_MODES = {"FIXED_MESSAGES", "WRAP_OVERFLOW"}


# ============================================================
# 5 x 7 DOT-MATRIX FONT
# ============================================================

FONT_5X7 = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],

    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],

    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


# ============================================================
# LED CONTROLLER
# ============================================================

class LEDController:
    """Virtual 2x8 display and guarded RS485 connection manager."""

    VALID_COLOURS = {"RED", "GREEN", "YELLOW"}

    COLOUR_CODES = {
        "YELLOW": "2200",
        "GREEN": "1100",
        "RED": "0000",
    }

    def __init__(self, port=None):
        self.logger = logging.getLogger(__name__)
        self.port = str(port or SERIAL_PORT).strip().upper()

        self.serial_connection = None

        self.gui_queue = queue.Queue()
        self.gui_thread = None
        self.gui_ready = False
        self.gui_running = False
        self._stopping = False

        self.root = None
        self.canvas = None
        self.status_label = None

        self.rows = ["", ""]
        self.colours = ["RED", "RED"] if DISPLAY_MODE == "WRAP_OVERFLOW" else ["RED", "GREEN"]

        # Scrolling state for row indexes 0 and 1.
        self._scroll_states = {
            0: None,
            1: None,
        }

    # --------------------------------------------------------
    # SERIAL CONNECTION
    # --------------------------------------------------------

    
    def connect(self):
        """
        Connect the CUSTronics LED controller.

        Simulation mode:
            Starts the virtual LED display without opening a COM port.

        Physical mode:
            Opens the configured RS485 serial port.
            The vendor's command protocol must be verified before
            sending commands to the physical LED panel.
        """

        # Already connected or running.
        if LED_SIMULATION_MODE:
            if self.gui_thread and self.gui_thread.is_alive():
                return True

            self.logger.info(
                "[LED SIMULATION] Starting virtual display | port=%s",
                self.port,
            )

            self._stopping = False
            self.gui_running = True

            self.gui_thread = Thread(
                target=self._run_virtual_display,
                name=f"LED-Simulator-{self.port}",
                daemon=True,
            )
            self.gui_thread.start()

            return True

        # Physical RS485 mode.
        if self.serial_connection and self.serial_connection.is_open:
            return True

        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=BAUD_RATE,
                bytesize=DATA_BITS,
                parity=PARITY,
                stopbits=STOP_BITS,
                timeout=SERIAL_TIMEOUT,
            )

            self.logger.info(
                "[LED HARDWARE] RS485 serial port opened | "
                "port=%s | baudrate=%s | data_bits=%s | "
                "parity=%s | stop_bits=%s",
                self.port,
                BAUD_RATE,
                DATA_BITS,
                PARITY,
                STOP_BITS,
            )

            return True

        except (SerialException, OSError):
            self.serial_connection = None

            self.logger.exception(
                "[LED HARDWARE] Failed to open RS485 port | port=%s",
                self.port,
            )

            return False
    # --------------------------------------------------------
    # VIRTUAL DISPLAY WINDOW
    # --------------------------------------------------------

    def _run_virtual_display(self):
        try:
            self.root = tk.Tk()
            self.root.title(f"{WINDOW_TITLE} - {self.port}")
            self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
            self.root.configure(bg=BACKGROUND)

            self.root.protocol(
                "WM_DELETE_WINDOW",
                self._on_window_close,
            )

            header = tk.Label(
                self.root,
                text=(
                    "CUSTronics LED | "
                    "690 x 370 x 80 mm | 2 ROW x 8 CHAR"
                    f" | {self.port}"
                ),
                font=("Consolas", 14, "bold"),
                bg=BACKGROUND,
                fg=TEXT_GREY,
            )
            header.pack(pady=(12, 8))

            self.canvas = tk.Canvas(
                self.root,
                bg=PANEL_BACKGROUND,
                highlightthickness=2,
                highlightbackground="#444444",
            )
            self.canvas.pack(
                fill="both",
                expand=True,
                padx=20,
                pady=10,
            )
            self.canvas.bind(
                "<Configure>",
                self._on_canvas_resize,
            )

            self.status_label = tk.Label(
                self.root,
                text=(
                    "SIMULATION MODE | RS485 OUTPUT DISABLED | "
                    "RED / GREEN | LEFT SCROLLING"
                ),
                font=("Consolas", 9),
                bg=BACKGROUND,
                fg="#55DD77",
            )
            self.status_label.pack(pady=(0, 12))

            self.gui_ready = True

            self.root.after(50, self._process_gui_queue)
            self.root.after(
                SCROLL_INTERVAL_MS,
                self._animate_scroll,
            )

            self._draw_display()
            self.root.mainloop()

        except Exception:
            self.logger.exception(
                "Virtual LED display could not start on %s.",
                self.port,
            )

        finally:
            self.gui_ready = False
            self.gui_running = False
            self.root = None
            self.canvas = None
            self.status_label = None

    # --------------------------------------------------------
    # DRAW DOT MATRIX
    # --------------------------------------------------------

    def _draw_row(self, text, row_index, colour):
        if not self.canvas:
            return

        # Each row is rendered as exactly 8 character positions.
        text = str(text)[:COLUMNS].ljust(COLUMNS)

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()

        if width <= 1 or height <= 1:
            return

        row_height = height / ROWS

        spacing_x = min(
            DOT_SPACING,
            max(3, (width - 40) / (COLUMNS * 6)),
        )

        spacing_y = min(
            DOT_SPACING,
            max(3, (row_height - 20) / 7),
        )

        spacing = min(spacing_x, spacing_y)

        radius = max(
            1,
            min(DOT_RADIUS, int(spacing * 0.34)),
        )

        char_width = 5 * spacing
        char_gap = spacing

        total_width = (
            COLUMNS * char_width
            + (COLUMNS - 1) * char_gap
        )

        start_x = max(10, (width - total_width) / 2)

        start_y = (
            row_index * row_height
            + (row_height - 7 * spacing) / 2
        )

        if colour == "RED":
            bright = LED_RED
            glow = LED_RED_GLOW
        else:
            bright = LED_GREEN
            glow = LED_GREEN_GLOW

        for char_index, char in enumerate(text):
            pattern = FONT_5X7.get(char, FONT_5X7[" "])

            char_x = start_x + char_index * (
                char_width + char_gap
            )

            for y_index, pattern_row in enumerate(pattern):
                for x_index, pixel in enumerate(pattern_row):
                    x = char_x + x_index * spacing
                    y = start_y + y_index * spacing

                    if pixel == "1":
                        self.canvas.create_oval(
                            x - radius - 2,
                            y - radius - 2,
                            x + radius + 2,
                            y + radius + 2,
                            fill=glow,
                            outline="",
                        )
                        self.canvas.create_oval(
                            x - radius,
                            y - radius,
                            x + radius,
                            y + radius,
                            fill=bright,
                            outline=bright,
                        )
                    else:
                        self.canvas.create_oval(
                            x - 1,
                            y - 1,
                            x + 1,
                            y + 1,
                            fill=LED_OFF,
                            outline=LED_OFF,
                        )

    def _draw_display(self):
        if not self.canvas:
            return

        try:
            if not self.canvas.winfo_exists():
                return
        except tk.TclError:
            return

        self.canvas.delete("all")

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()

        if width > 1 and height > 1:
            self.canvas.create_line(
                0,
                height / 2,
                width,
                height / 2,
                fill="#333333",
            )

        self._draw_row(self.rows[0], 0, self.colours[0])
        self._draw_row(self.rows[1], 1, self.colours[1])

    def _on_canvas_resize(self, _event=None):
        self._draw_display()


    def _format_display_text(self, message):
        """Center short messages and keep long messages ready for scrolling."""
        message = str(message).upper()

        if len(message) <= COLUMNS:
            return message.center(COLUMNS)

        return message[:COLUMNS]

    # --------------------------------------------------------
    # GUI QUEUE
    # --------------------------------------------------------

    def _process_gui_queue(self):
        if not self.root or not self.gui_running:
            return

        try:
            while True:
                action, value = self.gui_queue.get_nowait()

                if action in ("row", "scroll"):
                    if not isinstance(value, (tuple, list)) or len(value) != 3:
                        self.logger.error(
                            "Invalid GUI queue value for %r: %r",
                            action,
                            value,
                        )
                        continue

                    row_index, message, colour = value

                    if row_index not in (0, 1):
                        self.logger.error(
                            "Invalid row index for %r: %r",
                            action,
                            row_index,
                        )
                        continue

                    message = str(message)
                    colour = str(colour).strip().upper()

                    if colour not in self.VALID_COLOURS:
                        self.logger.error(
                            "Invalid colour for %r: %r",
                            action,
                            colour,
                        )
                        continue

                    if action == "row":
                        self._scroll_states[row_index] = None
                        self.rows[row_index] = self._format_display_text(message)
                        self.colours[row_index] = colour

                    else:
                        self._scroll_states[row_index] = {
                            "message": message,
                            "position": 0,
                            "colour": colour,
                            "pause_remaining": 0,
                        }

                        self.rows[row_index] = message[:COLUMNS].ljust(COLUMNS)
                        self.colours[row_index] = colour

                    self._draw_display()

                elif action == "clear":
                    if value not in (0, 1):
                        self.logger.error(
                            "Invalid row index for clear: %r",
                            value,
                        )
                        continue

                    self._scroll_states[value] = None
                    self.rows[value] = ""
                    self._draw_display()

                else:
                    self.logger.error(
                        "Unknown GUI queue action: %r",
                        action,
                    )

        except queue.Empty:
            pass
        except tk.TclError:
            return
        except Exception:
            self.logger.exception(
                "Error processing GUI queue."
            )

        if self.root and self.gui_running:
            try:
                self.root.after(50, self._process_gui_queue)
            except tk.TclError:
                pass

    # --------------------------------------------------------
    # SCROLLING ANIMATION
    # --------------------------------------------------------

    def _animate_scroll(self):
        """
        Scroll long messages left and pause for one frame before restarting.
        """

        if not self.root or not self.gui_running:
            return

        changed = False

        for row_index, state in self._scroll_states.items():
            if state is None:
                continue

            message = state["message"]
            position = state["position"]

            self.colours[row_index] = state["colour"]

            # Once the whole message and trailing spaces have scrolled away,
            # show one blank frame, then restart.
            if position > len(message):
                self.rows[row_index] = " " * COLUMNS
                state["position"] = 0
                changed = True
                continue

            # Add spaces so every character can scroll off the panel.
            scrolling_text = message + (" " * COLUMNS)

            # Take the next 8-character viewing window.
            visible_text = scrolling_text[
                position:position + COLUMNS
            ]

            self.rows[row_index] = visible_text.ljust(COLUMNS)

            state["position"] = position + 1
            changed = True

        if changed:
            self._draw_display()

        if self.root and self.gui_running:
            try:
                self.root.after(
                    SCROLL_INTERVAL_MS,
                    self._animate_scroll,
                )
            except tk.TclError:
                pass

    # --------------------------------------------------------
    # INPUT VALIDATION
    # --------------------------------------------------------

    def _validate_message(self, text, row, colour):
        if row not in (1, 2):
            self.logger.error("Row must be 1 or 2.")
            return None

        colour = str(colour).strip().upper()

        if colour not in self.VALID_COLOURS:
            self.logger.error("Colour must be RED or GREEN.")
            return None

        if text is None:
            self.logger.warning("Empty display message ignored.")
            return None

        message = str(text).strip().strip()

        if not message:
            self.logger.warning("Empty display message ignored.")
            return None

        if not message.isascii():
            self.logger.error(
                "Only ASCII text is supported: %r", message
            )
            return None

        unsupported = [
            char for char in message
            if char not in FONT_5X7
        ]

        if unsupported:
            self.logger.error(
                "Unsupported character(s) in message %r: %s",
                message,
                ", ".join(sorted(set(unsupported))),
            )
            return None

        if len(message) > MAX_DISPLAY_CHARACTERS:
            self.logger.info(
                "Message requires scrolling | length=%d | text=%s",
                len(message),
                message,
            )

        return message, colour

    
    def _send_rs485_command(self, text, colour="RED"):
        """Send a padded CUSTronics LED command over RS485."""

        # 1. Normalize the text.
        text = str(text).strip().upper()

        if not text or not text.isascii():
            self.logger.error(
                "[RS485 TX] Invalid LED text: %r",
                text,
            )
            return False

        if "\r" in text or "\n" in text:
            self.logger.error(
                "[RS485 TX] Text must not contain CR/LF: %r",
                text,
            )
            return False

        # 2. Limit the text to the LED's 16-character capacity.
        if len(text) > 16:
            self.logger.warning(
                "[RS485 TX] Text exceeds 16 characters; truncating: %r",
                text,
            )
            text = text[:16]

        # 3. Pad the text with spaces until it contains 16 characters.
        # Example: "ABC1234" becomes "ABC1234         ".
        text = text.ljust(16, " ")

        self.logger.info(
            "[LED TEXT] Prepared text=%r | length=%d",
            text,
            len(text),
        )

        # 4. Select the colour code.
        colour_codes = {
            "RED": "0000",
            "GREEN": "1100",
            "YELLOW": "2200",
        }

        colour = str(colour).strip().upper()
        colour_code = colour_codes.get(colour)

        if colour_code is None:
            self.logger.error(
                "[RS485 TX] Unsupported LED colour: %s",
                colour,
            )
            return False

        # 5. Build the command.
        # \r\n becomes actual bytes 0D 0A when encoded as ASCII.
        command = f"001DIS={text}{colour_code}\r\n"
        command_bytes = command.encode("ascii")

        # 6. Log the exact ASCII command and HEX bytes.
        self.logger.info(
            "[RS485 TX] Port=%s | ASCII=%r | HEX=%s",
            self.port,
            command,
            command_bytes.hex(" ").upper(),
        )

        # 7. Check that the serial port is open.
        if (
            self.serial_connection is None
            or not self.serial_connection.is_open
        ):
            self.logger.error(
                "[RS485 TX] Serial port is not open: %s",
                self.port,
            )
            return False

        # 8. Send the command to the LED.
        try:
            bytes_written = self.serial_connection.write(command_bytes)
            self.serial_connection.flush()

            self.logger.info(
                "[RS485 TX] Bytes written=%s/%s",
                bytes_written,
                len(command_bytes),
            )

            if bytes_written != len(command_bytes):
                self.logger.error(
                    "[RS485 TX] Incomplete serial write."
                )
                return False

            self.logger.info(
                "[LED HARDWARE] Command transmitted | port=%s",
                self.port,
            )

            return True

        except (serial.SerialException, OSError):
            self.logger.exception(
                "[RS485 TX] Failed to send command"
            )
            return False

    # --------------------------------------------------------
    # DISPLAY TEXT
    # --------------------------------------------------------

    def display(
        self,
        text,
        row=1,
        colour="RED",
        show_welcome=True,
        row2_message=None,
    ):
        """
        Display text using the selected DISPLAY_MODE.

        FIXED_MESSAGES:
            Existing behaviour: long messages scroll on Row 1.
            Row 2 displays the supplied message, or WELCOME when
            show_welcome=True. The caller can supply THANK YOU for OUT.

        WRAP_OVERFLOW:
            No scrolling and no hardcoded WELCOME / THANK YOU.
            Row 1 shows the first 8 characters in RED; Row 2 shows the
            next 8 characters in RED. Characters after position 16 are
            truncated. Row 2 is blank when there is no overflow.

        Physical RS485 output remains subject to vendor protocol
        confirmation.
        """

        mode = str(DISPLAY_MODE).strip().upper()
        if mode not in VALID_DISPLAY_MODES:
            self.logger.error(
                "Invalid DISPLAY_MODE=%r. Use one of %s.",
                DISPLAY_MODE,
                sorted(VALID_DISPLAY_MODES),
            )
            return False

        validated = self._validate_message(text, row, colour)
        if validated is None:
            return False

        message, colour = validated

        
        if not self._send_rs485_command(message, colour):
            return False

        # Physical mode: the RS485 command has already been sent.
        # Do not require the virtual display to be running.
        if not LED_SIMULATION_MODE:
            self.logger.info(
                "[LED HARDWARE] Physical display command sent | "
                "port=%s | row=%s | text=%r",
                self.port,
                row,
                message,
            )
            return True

        # Virtual mode requires the simulator window to be running.
        if not self.gui_running:
            self.logger.warning(
                "[LED VIRTUAL] Display is not running | port=%s",
                self.port,
            )
            return False


        if mode == "WRAP_OVERFLOW":
            # Fixed display only: never enqueue a scrolling action in this mode.
            # The two physical rows each show at most 8 characters, both RED.
            first_row = message[:COLUMNS]
            second_row = message[COLUMNS:COLUMNS * 2]

            self.gui_queue.put(("row", (0, first_row, "RED")))

            if second_row:
                self.gui_queue.put(("row", (1, second_row, "RED")))
            else:
                self.gui_queue.put(("clear", 1))

            if len(message) > COLUMNS * 2:
                self.logger.warning(
                    "[LED SIMULATION] Mode=WRAP_OVERFLOW | Port=%s | "
                    "Text exceeds 16 characters; truncating remainder=%r",
                    self.port,
                    message[COLUMNS * 2:],
                )

            self.logger.info(
                "[LED SIMULATION] Mode=WRAP_OVERFLOW | Port=%s | "
                "Row 1 RED=%r | Row 2 RED=%r | scrolling=OFF | ASCII_HEX=%s",
                self.port,
                first_row,
                second_row,
                message.encode("ascii").hex(" ").upper(),
            )
            return True

        if row != 1:
            row_index = row - 1
            if len(message) > COLUMNS:
                self.gui_queue.put(("scroll", (row_index, message, colour)))
            else:
                self.gui_queue.put(("row", (row_index, message, colour)))
            return True

        # FIXED_MESSAGES: preserve the current scrolling behaviour.
        if len(message) > COLUMNS:
            self.gui_queue.put(("scroll", (0, message, colour)))
        else:
            self.gui_queue.put(("row", (0, message, colour)))

        self.logger.info(
            "[LED SIMULATION] Mode=FIXED_MESSAGES | Port=%s | "
            "Row 1 | Colour=%s | Text=%r | Length=%d | ASCII_HEX=%s",
            self.port,
            colour,
            message,
            len(message),
            message.encode("ascii").hex(" ").upper(),
        )

        if row2_message is None:
            row2_message = "WELCOME" if show_welcome else None

        if row2_message:
            row2_validated = self._validate_message(
                row2_message,
                row=2,
                colour="GREEN",
            )
            if row2_validated is None:
                return False

            second_message, second_colour = row2_validated
            if len(second_message) > COLUMNS:
                self.gui_queue.put(("scroll", (1, second_message, second_colour)))
            else:
                self.gui_queue.put(("row", (1, second_message, second_colour)))

            self.logger.info(
                "[LED SIMULATION] Mode=FIXED_MESSAGES | Port=%s | "
                "Row 2 | Colour=%s | Text=%r | Length=%d | ASCII_HEX=%s",
                self.port,
                second_colour,
                second_message,
                len(second_message),
                second_message.encode("ascii").hex(" ").upper(),
            )
        else:
            self.gui_queue.put(("clear", 1))
            self.logger.info(
                "[LED SIMULATION] Port=%s | Row 2 cleared; "
                "no message configured.",
                self.port,
            )

        return True

    # --------------------------------------------------------
    # CLEAR ROW
    # --------------------------------------------------------

    def clear(self, row=1):
        """
        Clear the virtual display.

        clear(row=1): clear both rows.
        clear(row=2): clear only row 2.

        No physical RS485 commands are sent.
        """

        if row not in (1, 2):
            self.logger.error("Row must be 1 or 2.")
            return False

        if not self.gui_running:
            self.logger.warning(
                "Cannot clear: virtual display %s is not running.",
                self.port,
            )
            return False

        if row == 1:
            self.gui_queue.put(("clear", 0))
            self.gui_queue.put(("clear", 1))

            self.logger.info(
                "[LED SIMULATION] Port=%s | "
                "Plate cleared; both rows blank.",
                self.port,
            )
        else:
            self.gui_queue.put(("clear", 1))
            self.logger.info(
                "[LED SIMULATION] Port=%s | Row 2 cleared.",
                self.port,
            )
        return True

    # --------------------------------------------------------
    # SERIAL DISCONNECT
    # --------------------------------------------------------

    def disconnect(self):
        if self.serial_connection is None:
            return

        try:
            if self.serial_connection.is_open:
                self.serial_connection.close()
                self.logger.info("Serial port %s closed.", self.port)

        except (SerialException, OSError):
            self.logger.exception(
                "Error closing serial port %s.", self.port
            )

        finally:
            self.serial_connection = None

    # --------------------------------------------------------
    # CLOSE WINDOW
    # --------------------------------------------------------

    def _on_window_close(self):
        self.gui_running = False
        self.gui_ready = False

        root = self.root
        self.root = None
        self.canvas = None
        self.status_label = None

        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass

    # --------------------------------------------------------
    # STOP CONTROLLER
    # --------------------------------------------------------

    def stop(self):
        """Request simulator shutdown and close the serial port."""

        self._stopping = True

        root = self.root

        if root is not None and self.gui_running:
            # Tkinter should process window operations on its GUI thread.
            try:
                root.after(0, self._on_window_close)
            except tk.TclError:
                self.gui_running = False
                self.gui_ready = False
        else:
            self.gui_running = False
            self.gui_ready = False

        self.disconnect()

        self.logger.info(
            "LED controller stopped | port=%s",
            self.port,
        )
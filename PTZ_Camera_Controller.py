from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import threading
import tkinter as tk
from dataclasses import asdict, dataclass
from enum import Enum, auto
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, Final

try:
    import duvc_ctl as duvc
except ImportError:
    duvc = None

BG: Final = "#0F172A"
HEADER_BG: Final = "#1E293B"
SECTION_BG: Final = "#172033"
BUTTON_BG: Final = "#334155"
BUTTON_HOVER: Final = "#475569"
BUTTON_ACTIVE: Final = "#2563EB"
BUTTON_PRESSED: Final = "#1D4ED8"
BORDER: Final = "#475569"
TEXT: Final = "#F8FAFC"
MUTED: Final = "#94A3B8"
DISABLED: Final = "#64748B"
GREEN: Final = "#22C55E"
YELLOW: Final = "#F59E0B"
RED: Final = "#EF4444"
PRESET_SAVED: Final = "#047857"
PRESET_SAVE_MODE: Final = "#D97706"
TOOLTIP_BG: Final = "#020617"
TOOLTIP_ENABLED: Final = "#3B82F6"
TOOLTIP_DISABLED: Final = "#64748B"

APP_TITLE: Final = "PTZ Remote"
DEFAULT_OPACITY: Final = 1.0
OPACITY_VALUES: Final = (1.00, 0.92, 0.78, 0.64, 0.50, 0.40)
INITIAL_HOLD_DELAY_MS: Final = 120
REPEAT_INTERVAL_MS: Final = 90
POSITION_REFRESH_DELAY_MS: Final = 300
PRESET_COMMAND_DELAY_MS: Final = 300
WORKER_POLL_INTERVAL_MS: Final = 30
RIGHT_MARGIN: Final = 12
BOTTOM_MARGIN: Final = 58
PRESET_NUMBERS: Final = range(1, 5)
PTZ_PROPERTIES: Final = ("pan", "tilt", "zoom")
PREFERRED_CAMERA_SCORES: Final = {
    "c1612": 100,
    "rapoo": 80,
    "ptz": 40,
    "conference": 30,
    "usb video": 10,
}
SPEED_MODES: Final = {"FINE": 1, "NORMAL": 3, "FAST": 6}
ZOOM_SPEED_MODES: Final = {"FINE": 100, "NORMAL": 200, "FAST": 350}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PropertyRange:
    minimum: int
    maximum: int
    step: int
    default: int

    def align(self, requested_value: int) -> int:
        clamped = max(self.minimum, min(self.maximum, int(requested_value)))
        offset = clamped - self.minimum
        quotient, remainder = divmod(offset, self.step)
        if remainder * 2 >= self.step:
            quotient += 1
        aligned = self.minimum + quotient * self.step
        return max(self.minimum, min(self.maximum, aligned))


@dataclass
class PTZPosition:
    pan: int | None = None
    tilt: int | None = None
    zoom: int | None = None

    def get(self, property_name: str) -> int | None:
        return getattr(self, property_name)

    def set(self, property_name: str, value: int | None) -> None:
        setattr(self, property_name, value)

    def supported_values(self, supported: set[str]) -> dict[str, int]:
        return {
            name: value
            for name in PTZ_PROPERTIES
            if name in supported
            and (value := self.get(name)) is not None
        }


@dataclass(frozen=True)
class HoldAction:
    property_name: str
    direction: int
    owner: str


@dataclass(frozen=True)
class CameraSnapshot:
    camera_name: str
    ranges: dict[str, PropertyRange]
    position: PTZPosition


@dataclass(frozen=True)
class WorkerResult:
    request_id: int
    operation: str
    value: Any = None
    error: Exception | None = None


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED_NO_PTZ = auto()
    READY = auto()
    ERROR = auto()


class PresetStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.data: dict[str, dict[str, dict[str, int]]] = {}

    def load(self) -> None:
        try:
            with self.file_path.open("r", encoding="utf-8") as handle:
                raw_data = json.load(handle)
        except FileNotFoundError:
            self.data = {}
            return
        except (json.JSONDecodeError, OSError):
            logger.exception("Unable to load preset file: %s", self.file_path)
            self.data = {}
            return
        self.data = self._validate(raw_data)

    def get(self, camera_key: str, preset_number: int) -> PTZPosition | None:
        values = self.data.get(camera_key, {}).get(str(preset_number))
        return PTZPosition(**values) if values else None

    def save(
        self,
        camera_key: str,
        preset_number: int,
        position: PTZPosition,
    ) -> None:
        if preset_number not in PRESET_NUMBERS:
            raise ValueError(f"Invalid preset number: {preset_number}")
        values = {
            name: value
            for name, value in asdict(position).items()
            if name in PTZ_PROPERTIES
            and isinstance(value, int)
            and not isinstance(value, bool)
        }
        if not values:
            raise ValueError("Preset contains no PTZ values")
        self.data.setdefault(camera_key, {})[str(preset_number)] = values
        self._write_atomic()

    def saved_numbers(self, camera_key: str) -> set[int]:
        saved: set[int] = set()
        for key in self.data.get(camera_key, {}):
            try:
                number = int(key)
            except ValueError:
                continue
            if number in PRESET_NUMBERS:
                saved.add(number)
        return saved

    def _write_atomic(self) -> None:
        temporary_path = self.file_path.with_suffix(".tmp")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.file_path)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Unable to remove temporary preset file")

    @staticmethod
    def _validate(raw_data: Any) -> dict[str, dict[str, dict[str, int]]]:
        if not isinstance(raw_data, dict):
            return {}
        validated: dict[str, dict[str, dict[str, int]]] = {}
        for camera_key, camera_presets in raw_data.items():
            if not isinstance(camera_key, str) or not isinstance(camera_presets, dict):
                continue
            clean_presets: dict[str, dict[str, int]] = {}
            for preset_key, values in camera_presets.items():
                key = str(preset_key)
                if key not in {"1", "2", "3", "4"} or not isinstance(values, dict):
                    continue
                clean_values = {
                    name: value
                    for name, value in values.items()
                    if name in PTZ_PROPERTIES
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                }
                if clean_values:
                    clean_presets[key] = clean_values
            normalized_key = camera_key.strip()
            if normalized_key and clean_presets:
                validated[normalized_key] = clean_presets
        return validated


class CameraService:
    def __init__(self, duvc_module: Any) -> None:
        self.duvc = duvc_module
        self.controller: Any | None = None
        self.camera_name: str | None = None
        self.ranges: dict[str, PropertyRange] = {}
        self.position = PTZPosition()

    def list_cameras(self) -> list[str]:
        if self.duvc is None:
            raise RuntimeError("duvc-ctl is not installed")
        return [str(name) for name in self.duvc.list_cameras()]

    def connect(self, device_index: int, camera_name: str) -> CameraSnapshot:
        if self.duvc is None:
            raise RuntimeError("duvc-ctl is not installed")
        self.disconnect()
        controller = self.duvc.CameraController(device_index=device_index)
        try:
            supported = controller.get_supported_properties()
            camera_properties = (
                supported.get("camera", []) if isinstance(supported, dict) else []
            )
            normalized = {
                self.normalize_property_name(name) for name in camera_properties
            }
            ranges: dict[str, PropertyRange] = {}
            for property_name in PTZ_PROPERTIES:
                if property_name not in normalized:
                    continue
                try:
                    raw_range = controller.get_property_range(property_name)
                    ranges[property_name] = self.parse_property_range(raw_range)
                except Exception:
                    logger.exception("Unable to read %s range", property_name)
            self.controller = controller
            self.camera_name = camera_name
            self.ranges = ranges
            position = self.read_position()
            return CameraSnapshot(camera_name, dict(ranges), position)
        except Exception:
            try:
                controller.close()
            except Exception:
                logger.exception("Unable to close controller")
            raise

    def disconnect(self) -> None:
        controller = self.controller
        self.controller = None
        self.camera_name = None
        self.ranges = {}
        self.position = PTZPosition()
        if controller is not None:
            try:
                controller.close()
            except Exception:
                logger.exception("Unable to close camera")

    def read_position(self) -> PTZPosition:
        position = PTZPosition()
        if self.controller is not None:
            for property_name in self.ranges:
                try:
                    position.set(
                        property_name,
                        int(getattr(self.controller, property_name)),
                    )
                except Exception:
                    logger.exception("Unable to read %s", property_name)
        self.position = position
        return PTZPosition(position.pan, position.tilt, position.zoom)

    def set_value(self, property_name: str, requested_value: int) -> int:
        self._validate_property(property_name)
        aligned_value = self.ranges[property_name].align(requested_value)
        setattr(self.controller, property_name, aligned_value)
        self.position.set(property_name, aligned_value)
        return aligned_value

    def move(self, property_name: str, direction: int, multiplier: int) -> int:
        self._validate_property(property_name)
        if direction not in (-1, 1):
            raise ValueError("Movement direction must be -1 or 1")
        if multiplier < 1:
            raise ValueError("Movement multiplier must be at least 1")
        current_value = self.position.get(property_name)
        if current_value is None:
            current_value = int(getattr(self.controller, property_name))
            self.position.set(property_name, current_value)
        movement = self.ranges[property_name].step * multiplier
        return self.set_value(
            property_name,
            current_value + direction * movement,
        )

    def home_commands(self) -> list[tuple[str, int]]:
        commands: list[tuple[str, int]] = []
        for property_name in ("pan", "tilt"):
            information = self.ranges.get(property_name)
            if information is None:
                continue
            target = (
                0
                if information.minimum <= 0 <= information.maximum
                else information.default
            )
            commands.append((property_name, information.align(target)))
        return commands

    def _validate_property(self, property_name: str) -> None:
        if self.controller is None:
            raise RuntimeError("Camera disconnected")
        if property_name not in self.ranges:
            raise ValueError(f"Unsupported camera property: {property_name}")

    @staticmethod
    def parse_property_range(raw_range: Any) -> PropertyRange:
        if isinstance(raw_range, dict):
            minimum = raw_range.get("min", raw_range.get("minimum"))
            maximum = raw_range.get("max", raw_range.get("maximum"))
            step = raw_range.get("step")
            default = raw_range.get("default")
        else:
            minimum = getattr(
                raw_range,
                "min",
                getattr(raw_range, "minimum", None),
            )
            maximum = getattr(
                raw_range,
                "max",
                getattr(raw_range, "maximum", None),
            )
            step = getattr(raw_range, "step", None)
            default = getattr(raw_range, "default", None)
        values = {
            "minimum": minimum,
            "maximum": maximum,
            "step": step,
            "default": default,
        }
        missing = [name for name, value in values.items() if value is None]
        if missing:
            raise ValueError(
                f"Invalid property range; missing {', '.join(missing)}: {raw_range!r}"
            )
        minimum_value = int(minimum)
        maximum_value = int(maximum)
        if minimum_value > maximum_value:
            raise ValueError(
                f"Invalid property range: {minimum_value} > {maximum_value}"
            )
        parsed = PropertyRange(
            minimum=minimum_value,
            maximum=maximum_value,
            step=max(1, abs(int(step))),
            default=int(default),
        )
        return PropertyRange(
            minimum=parsed.minimum,
            maximum=parsed.maximum,
            step=parsed.step,
            default=parsed.align(parsed.default),
        )

    @staticmethod
    def normalize_property_name(value: Any) -> str:
        return str(value).strip().lower().rsplit(".", 1)[-1]


class CameraWorker:
    def __init__(self, service: CameraService) -> None:
        self.service = service
        self.requests: queue.Queue[
            tuple[int, str, Callable[[], Any]] | None
        ] = queue.Queue()
        self.results: queue.Queue[WorkerResult] = queue.Queue()
        self.thread = threading.Thread(
            target=self._run,
            name="PTZCameraWorker",
            daemon=True,
        )
        self.thread.start()

    def submit(
        self,
        request_id: int,
        operation: str,
        action: Callable[[], Any],
    ) -> None:
        self.requests.put((request_id, operation, action))

    def stop(self) -> None:
        self.requests.put(None)

    def _run(self) -> None:
        while True:
            request = self.requests.get()
            if request is None:
                try:
                    self.service.disconnect()
                finally:
                    return
            request_id, operation, action = request
            try:
                value = action()
                result = WorkerResult(request_id, operation, value=value)
            except Exception as error:
                logger.exception("Camera operation failed: %s", operation)
                result = WorkerResult(request_id, operation, error=error)
            self.results.put(result)


class ToolTip:
    enabled = False
    instances: list["ToolTip"] = []

    def __init__(self, widget: tk.Widget, text: str, delay: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self.window: tk.Toplevel | None = None
        self.job_id: str | None = None
        self.instances.append(self)
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.widget_destroyed, add="+")

    def schedule(self, _event: tk.Event | None = None) -> None:
        self.cancel_schedule()
        if self.enabled:
            self.job_id = self.widget.after(self.delay, self.show)

    def cancel_schedule(self) -> None:
        if self.job_id is not None:
            try:
                self.widget.after_cancel(self.job_id)
            except tk.TclError:
                pass
        self.job_id = None

    def show(self) -> None:
        self.cancel_schedule()
        if not self.enabled or self.window is not None:
            return
        try:
            if not self.widget.winfo_exists():
                return
            center_x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y_position = self.widget.winfo_rooty() + self.widget.winfo_height() + 7
            self.window = tk.Toplevel(self.widget)
            self.window.overrideredirect(True)
            self.window.attributes("-topmost", True)
            self.window.configure(bg=TOOLTIP_BG)
            label = tk.Label(
                self.window,
                text=self.text,
                bg=TOOLTIP_BG,
                fg=TEXT,
                padx=8,
                pady=5,
                justify="left",
                relief="solid",
                borderwidth=1,
                font=("Segoe UI", 8),
            )
            label.pack()
            self.window.update_idletasks()
            width = self.window.winfo_reqwidth()
            height = self.window.winfo_reqheight()
            screen_width = self.widget.winfo_screenwidth()
            screen_height = self.widget.winfo_screenheight()
            x_position = max(
                5,
                min(center_x - width // 2, screen_width - width - 5),
            )
            if y_position + height > screen_height - 5:
                y_position = self.widget.winfo_rooty() - height - 7
            y_position = max(
                5,
                min(y_position, screen_height - height - 5),
            )
            self.window.geometry(f"+{x_position}+{y_position}")
        except tk.TclError:
            self.window = None

    def hide(self, _event: tk.Event | None = None) -> None:
        self.cancel_schedule()
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
        self.window = None

    def widget_destroyed(self, event: tk.Event | None = None) -> None:
        if event is not None and event.widget != self.widget:
            return
        self.hide()
        try:
            self.instances.remove(self)
        except ValueError:
            pass

    @classmethod
    def set_enabled(cls, enabled: bool) -> None:
        cls.enabled = enabled
        if not enabled:
            for tooltip in cls.instances.copy():
                tooltip.hide()


class CompactPTZRemote:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.camera_service = CameraService(duvc)
        self.camera_worker = CameraWorker(self.camera_service)
        self.camera_names: list[str] = []
        self.camera_name: str | None = None
        self.ranges: dict[str, PropertyRange] = {}
        self.position = PTZPosition()
        self.preset_store = PresetStore(self._preset_file_path())
        self.connection_state = ConnectionState.DISCONNECTED
        self.active_hold: HoldAction | None = None
        self.move_pending = False
        self.save_mode = False
        self.is_minimized = False
        self.is_closing = False
        self.operation_generation = 0
        self.request_counter = 0
        self.callbacks: dict[int, Callable[[WorkerResult], None]] = {}
        self.jobs: dict[str, str] = {}
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.opacity_index = 0
        self.speed_mode = "NORMAL"
        self.tooltips_enabled = False
        self.configure_window()
        self.configure_styles()
        self.create_interface()
        self.preset_store.load()
        self.render_state()
        self.root.protocol("WM_DELETE_WINDOW", self.close_application)
        self.root.bind("<Map>", self.window_mapped, add="+")
        self.root.bind("<Escape>", self.handle_escape, add="+")
        self.root.bind_all("<KeyPress>", self.keyboard_pressed, add="+")
        self.root.bind_all("<KeyRelease>", self.keyboard_released, add="+")
        self.schedule_job("worker", WORKER_POLL_INTERVAL_MS, self.poll_worker)
        self.schedule_job("refresh", 200, self.refresh_cameras)
        self.schedule_job("placement", 500, self.place_bottom_right)

    @staticmethod
    def _preset_file_path() -> Path:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            directory = Path(base) / "PTZRemote"
        else:
            directory = Path.home() / "AppData" / "Local" / "PTZRemote"
        return directory / "ptz_presets.json"

    @property
    def supported_properties(self) -> set[str]:
        return set(self.ranges)

    @property
    def is_connected(self) -> bool:
        return self.camera_name is not None

    def configure_window(self) -> None:
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", DEFAULT_OPACITY)
        self.root.resizable(False, False)

    def configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Compact.TCombobox",
            fieldbackground=BUTTON_BG,
            background=BUTTON_BG,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BUTTON_BG,
            lightcolor=BUTTON_BG,
            darkcolor=BUTTON_BG,
            padding=5,
        )
        style.map(
            "Compact.TCombobox",
            fieldbackground=[("readonly", BUTTON_BG)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", BUTTON_BG)],
            selectforeground=[("readonly", TEXT)],
        )

    def create_interface(self) -> None:
        self.outer_frame = tk.Frame(
            self.root,
            bg=BG,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.outer_frame.pack(fill="both", expand=True)
        self.create_header()
        self.content_frame = tk.Frame(self.outer_frame, bg=BG)
        self.content_frame.pack(fill="both", padx=8, pady=7)
        self.create_camera_row()
        self.create_ptz_section()
        self.create_zoom_section()
        self.create_speed_section()
        self.create_preset_section()
        self.create_position_display()
        self.create_log_display()

    def create_header(self) -> None:
        self.header_frame = tk.Frame(self.outer_frame, bg=HEADER_BG, height=30)
        self.header_frame.pack(fill="x")
        self.header_frame.pack_propagate(False)
        self.status_dot = tk.Label(
            self.header_frame,
            text="●",
            bg=HEADER_BG,
            fg=RED,
            font=("Segoe UI", 9),
        )
        self.status_dot.pack(side="left", padx=(8, 4))
        ToolTip(
            self.status_dot,
            "Connection status\nGreen: PTZ ready\nYellow: connecting\nRed: disconnected",
        )
        self.title_label = tk.Label(
            self.header_frame,
            text="PTZ CONTROL",
            bg=HEADER_BG,
            fg=TEXT,
            font=("Segoe UI", 8, "bold"),
        )
        self.title_label.pack(side="left", padx=(0, 4))
        buttons = (
            ("×", self.close_application, RED, "Close PTZ utility"),
            ("◐", self.change_opacity, MUTED, "Change window transparency"),
            ("_", self.minimize_window, MUTED, "Minimize to taskbar"),
            ("?", self.toggle_tooltips, TOOLTIP_DISABLED, "Toggle help tooltips"),
            ("↻", self.refresh_cameras, MUTED, "Refresh USB cameras"),
        )
        for text, command, colour, tooltip in buttons:
            button = self.create_header_button(text, command, colour)
            button.pack(side="right", padx=(0, 2) if text == "×" else 0)
            if text == "?":
                self.tooltip_toggle_button = button
            ToolTip(button, tooltip)
        for widget in (self.header_frame, self.status_dot, self.title_label):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag_window)
        ToolTip(self.title_label, "Drag to move the utility")

    def create_header_button(
        self,
        text: str,
        command: Callable[[], None],
        foreground: str,
    ) -> tk.Button:
        return tk.Button(
            self.header_frame,
            text=text,
            command=command,
            width=2,
            bg=HEADER_BG,
            fg=foreground,
            activebackground=BUTTON_HOVER,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Symbol", 9, "bold"),
            cursor="hand2",
        )

    def create_camera_row(self) -> None:
        frame = tk.Frame(self.content_frame, bg=BG)
        frame.pack(fill="x", pady=(0, 6))
        self.camera_combo = ttk.Combobox(
            frame,
            state="readonly",
            width=25,
            style="Compact.TCombobox",
            font=("Segoe UI", 8),
        )
        self.camera_combo.pack(side="left", fill="x", expand=True)
        self.camera_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.camera_selection_changed(),
        )
        ToolTip(self.camera_combo, "Select the USB camera to control")
        self.connect_button = tk.Button(
            frame,
            text="●",
            command=self.connect_selected_camera,
            width=3,
            bg=BUTTON_ACTIVE,
            fg=TEXT,
            activebackground=BUTTON_PRESSED,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Symbol", 9, "bold"),
            cursor="hand2",
        )
        self.connect_button.pack(side="left", padx=(5, 0), ipady=3)
        ToolTip(self.connect_button, "Connect or reconnect selected camera")

    def create_ptz_section(self) -> None:
        frame = tk.Frame(self.content_frame, bg=SECTION_BG)
        frame.pack(fill="x", pady=(0, 6))
        pad = tk.Frame(frame, bg=SECTION_BG)
        pad.pack(pady=7)
        self.up_button = self.create_hold_button(
            pad, "▲", 0, 1, "tilt", 1, "Tilt camera up"
        )
        self.left_button = self.create_hold_button(
            pad, "◀", 1, 0, "pan", -1, "Pan camera left"
        )
        self.home_button = tk.Button(
            pad,
            text="⌂",
            command=self.go_home,
            width=4,
            height=1,
            bg=BUTTON_ACTIVE,
            fg="#FACC15",
            disabledforeground=DISABLED,
            activebackground=BUTTON_PRESSED,
            activeforeground="#FACC15",
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Symbol", 12, "bold"),
            cursor="hand2",
            state="disabled",
        )
        self.home_button.grid(row=1, column=1, padx=3, pady=3, ipady=3)
        ToolTip(self.home_button, "Move Pan and Tilt to Home")
        self.right_button = self.create_hold_button(
            pad, "▶", 1, 2, "pan", 1, "Pan camera right"
        )
        self.down_button = self.create_hold_button(
            pad, "▼", 2, 1, "tilt", -1, "Tilt camera down"
        )

    def create_hold_button(
        self,
        parent: tk.Widget,
        text: str,
        row: int,
        column: int,
        property_name: str,
        direction: int,
        tooltip_text: str,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            width=4,
            height=1,
            bg=BUTTON_BG,
            fg=TEXT,
            disabledforeground=DISABLED,
            activebackground=BUTTON_ACTIVE,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Symbol", 11, "bold"),
            cursor="hand2",
            state="disabled",
        )
        button.grid(row=row, column=column, padx=3, pady=3, ipady=3)
        owner = f"mouse:{property_name}:{direction}"
        self.bind_hold_button(button, property_name, direction, owner)
        ToolTip(button, tooltip_text + "\nPress and hold")
        return button

    def create_zoom_section(self) -> None:
        frame = tk.Frame(self.content_frame, bg=SECTION_BG)
        frame.pack(fill="x", pady=(0, 6))
        self.zoom_out_button = self.create_zoom_button(frame, "−", -1, "Zoom out")
        self.zoom_out_button.pack(
            side="left", fill="x", expand=True, padx=(7, 3), pady=6, ipady=3
        )
        label = tk.Label(
            frame,
            text="ZOOM",
            bg=SECTION_BG,
            fg=MUTED,
            width=7,
            font=("Segoe UI", 7, "bold"),
        )
        label.pack(side="left")
        ToolTip(label, "Camera Zoom control")
        self.zoom_in_button = self.create_zoom_button(frame, "+", 1, "Zoom in")
        self.zoom_in_button.pack(
            side="left", fill="x", expand=True, padx=(3, 7), pady=6, ipady=3
        )

    def create_zoom_button(
        self,
        parent: tk.Widget,
        text: str,
        direction: int,
        tooltip_text: str,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            bg=BUTTON_BG,
            fg=TEXT,
            disabledforeground=DISABLED,
            activebackground=BUTTON_ACTIVE,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI", 12, "bold"),
            cursor="hand2",
            state="disabled",
        )
        self.bind_hold_button(
            button,
            "zoom",
            direction,
            f"mouse:zoom:{direction}",
        )
        ToolTip(button, tooltip_text + "\nPress and hold")
        return button

    def create_speed_section(self) -> None:
        frame = tk.Frame(self.content_frame, bg=BG)
        frame.pack(fill="x", pady=(0, 6))
        label = tk.Label(
            frame,
            text="SPEED",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 7, "bold"),
        )
        label.pack(side="left", padx=(1, 5))
        ToolTip(label, "Movement amount per command")
        details = {
            "FINE": ("Fine", "Precise movement"),
            "NORMAL": ("Normal", "General movement"),
            "FAST": ("Fast", "Large position changes"),
        }
        self.speed_buttons: dict[str, tk.Button] = {}
        for code in SPEED_MODES:
            display_text, tooltip_text = details[code]
            button = tk.Button(
                frame,
                text=display_text,
                command=lambda selected=code: self.set_speed(selected),
                bg=BUTTON_BG,
                fg=MUTED,
                activebackground=BUTTON_ACTIVE,
                activeforeground=TEXT,
                relief="flat",
                borderwidth=0,
                font=("Segoe UI", 7, "bold"),
                cursor="hand2",
            )
            button.pack(side="left", fill="x", expand=True, padx=1, ipady=3)
            self.speed_buttons[code] = button
            ToolTip(button, tooltip_text)
        self.update_speed_buttons()

    def create_preset_section(self) -> None:
        frame = tk.Frame(self.content_frame, bg=BG)
        frame.pack(fill="x", pady=(0, 6))
        label = tk.Label(
            frame,
            text="PRESETS",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 7, "bold"),
        )
        label.pack(side="left", padx=(1, 4))
        ToolTip(label, "Saved Pan, Tilt and Zoom positions")
        self.preset_buttons: list[tk.Button] = []
        for number in PRESET_NUMBERS:
            button = tk.Button(
                frame,
                text=str(number),
                command=lambda selected=number: self.preset_clicked(selected),
                width=3,
                bg=BUTTON_BG,
                fg=TEXT,
                disabledforeground=DISABLED,
                activebackground=BUTTON_ACTIVE,
                activeforeground=TEXT,
                relief="flat",
                borderwidth=0,
                font=("Segoe UI", 8, "bold"),
                cursor="hand2",
                state="disabled",
            )
            button.pack(side="left", fill="x", expand=True, padx=1, ipady=3)
            button.bind(
                "<Button-3>",
                lambda _event, selected=number: self.save_preset(selected),
            )
            ToolTip(
                button,
                f"Preset {number}\nLeft-click: recall\nRight-click: save",
            )
            self.preset_buttons.append(button)
        self.save_button = tk.Button(
            frame,
            text="SAVE",
            command=self.toggle_save_mode,
            width=5,
            bg=BUTTON_BG,
            fg=TEXT,
            disabledforeground=DISABLED,
            activebackground=BUTTON_ACTIVE,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI", 7, "bold"),
            cursor="hand2",
            state="disabled",
        )
        self.save_button.pack(side="left", padx=(3, 0), ipady=3)
        ToolTip(self.save_button, "Click SAVE, then select preset 1 to 4")

    def create_position_display(self) -> None:
        self.position_label = tk.Label(
            self.content_frame,
            text="PAN --    TILT --    ZOOM --",
            bg=HEADER_BG,
            fg=TEXT,
            anchor="center",
            padx=5,
            pady=6,
            font=("Consolas", 8, "bold"),
        )
        self.position_label.pack(fill="x", pady=(0, 4))
        ToolTip(self.position_label, "Last known camera PTZ values")

    def create_log_display(self) -> None:
        self.log_label = tk.Label(
            self.content_frame,
            text="Searching for cameras...",
            bg=BG,
            fg=YELLOW,
            anchor="w",
            justify="left",
            width=39,
            height=1,
            font=("Segoe UI", 7),
        )
        self.log_label.pack(fill="x")
        ToolTip(self.log_label, "Latest camera status or PTZ activity")

    def submit_camera_operation(
        self,
        operation: str,
        action: Callable[[], Any],
        callback: Callable[[WorkerResult], None],
    ) -> int:
        self.request_counter += 1
        request_id = self.request_counter
        self.callbacks[request_id] = callback
        self.camera_worker.submit(request_id, operation, action)
        return request_id

    def poll_worker(self) -> None:
        while True:
            try:
                result = self.camera_worker.results.get_nowait()
            except queue.Empty:
                break
            callback = self.callbacks.pop(result.request_id, None)
            if callback is not None and not self.is_closing:
                callback(result)
        if not self.is_closing:
            self.schedule_job("worker", WORKER_POLL_INTERVAL_MS, self.poll_worker)

    def refresh_cameras(self) -> None:
        if self.is_closing:
            return
        self.stop_hold()
        self.invalidate_operations()
        self.clear_camera_state()
        self.camera_names = []
        self.camera_combo.set("")
        self.camera_combo["values"] = ()
        self.connection_state = ConnectionState.CONNECTING
        self.render_state()
        self.write_log("Searching for cameras...", YELLOW)
        generation = self.operation_generation

        def completed(result: WorkerResult) -> None:
            if generation != self.operation_generation:
                return
            if result.error is not None:
                self.connection_state = ConnectionState.ERROR
                self.render_state()
                self.write_log(f"Detection failed: {result.error}", RED)
                return
            self.camera_names = list(result.value)
            self.camera_combo["values"] = self.camera_names
            if not self.camera_names:
                self.connection_state = ConnectionState.ERROR
                self.render_state()
                self.write_log("No USB camera detected", RED)
                return
            self.camera_combo.current(self.find_preferred_camera())
            self.connection_state = ConnectionState.DISCONNECTED
            self.render_state()
            self.write_log(f"Found {len(self.camera_names)} camera(s)", YELLOW)
            self.schedule_job("connect", 120, self.connect_selected_camera)

        self.submit_camera_operation(
            "list_cameras",
            self.camera_service.list_cameras,
            completed,
        )

    def find_preferred_camera(self) -> int:
        best_index = 0
        best_score = -1
        for index, camera_name in enumerate(self.camera_names):
            lower_name = camera_name.lower()
            score = sum(
                weight
                for word, weight in PREFERRED_CAMERA_SCORES.items()
                if word in lower_name
            )
            if score > best_score:
                best_index = index
                best_score = score
        return best_index

    def camera_selection_changed(self) -> None:
        self.stop_hold()
        self.invalidate_operations()
        self.clear_camera_state()
        self.render_state()
        self.write_log("Connecting selected camera...", YELLOW)
        self.schedule_job("connect", 100, self.connect_selected_camera)

    def connect_selected_camera(self) -> None:
        if self.is_closing:
            return
        selected_index = self.camera_combo.current()
        if selected_index < 0 or selected_index >= len(self.camera_names):
            self.write_log("Select a camera first", RED)
            return
        self.stop_hold()
        self.invalidate_operations()
        self.clear_camera_state()
        selected_name = self.camera_names[selected_index]
        self.connection_state = ConnectionState.CONNECTING
        self.render_state()
        self.write_log("Connecting...", YELLOW)
        generation = self.operation_generation

        def action() -> CameraSnapshot:
            return self.camera_service.connect(selected_index, selected_name)

        def completed(result: WorkerResult) -> None:
            if generation != self.operation_generation:
                return
            if result.error is not None:
                self.handle_camera_failure("Connection failed", result.error)
                return
            snapshot: CameraSnapshot = result.value
            self.camera_name = snapshot.camera_name
            self.ranges = snapshot.ranges
            self.position = snapshot.position
            if self.ranges:
                self.connection_state = ConnectionState.READY
                supported = "/".join(name.upper() for name in self.ranges)
                self.write_log(f"Ready | {supported}", GREEN)
            else:
                self.connection_state = ConnectionState.CONNECTED_NO_PTZ
                self.write_log("Connected | No standard UVC PTZ", YELLOW)
            self.render_state()

        self.submit_camera_operation("connect", action, completed)

    def disconnect_camera(self, show_log: bool = True) -> None:
        self.stop_hold()
        self.invalidate_operations()
        self.cancel_save_mode(render=False)
        self.clear_camera_state()
        self.connection_state = ConnectionState.DISCONNECTED
        self.render_state()
        self.submit_camera_operation(
            "disconnect",
            self.camera_service.disconnect,
            lambda _result: None,
        )
        if show_log:
            self.write_log("Disconnected", YELLOW)

    def clear_camera_state(self) -> None:
        self.camera_name = None
        self.ranges = {}
        self.position = PTZPosition()
        self.move_pending = False

    def render_state(self) -> None:
        colours = {
            ConnectionState.DISCONNECTED: RED,
            ConnectionState.CONNECTING: YELLOW,
            ConnectionState.CONNECTED_NO_PTZ: YELLOW,
            ConnectionState.READY: GREEN,
            ConnectionState.ERROR: RED,
        }
        self.status_dot.config(fg=colours[self.connection_state])
        connect_colour = BUTTON_ACTIVE
        if self.connection_state == ConnectionState.READY:
            connect_colour = GREEN
        elif self.connection_state in {
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED_NO_PTZ,
        }:
            connect_colour = YELLOW
        self.connect_button.config(bg=connect_colour)
        supported = self.supported_properties
        pan_state = "normal" if "pan" in supported else "disabled"
        tilt_state = "normal" if "tilt" in supported else "disabled"
        zoom_state = "normal" if "zoom" in supported else "disabled"
        self.left_button.config(state=pan_state)
        self.right_button.config(state=pan_state)
        self.up_button.config(state=tilt_state)
        self.down_button.config(state=tilt_state)
        self.zoom_out_button.config(state=zoom_state)
        self.zoom_in_button.config(state=zoom_state)
        self.home_button.config(
            state="normal" if {"pan", "tilt"} & supported else "disabled"
        )
        preset_state = "normal" if self.is_connected and supported else "disabled"
        for button in self.preset_buttons:
            button.config(state=preset_state)
        self.save_button.config(state=preset_state)
        self.update_position_display()
        self.update_preset_colours()

    def bind_hold_button(
        self,
        button: tk.Button,
        property_name: str,
        direction: int,
        owner: str,
    ) -> None:
        button.bind(
            "<ButtonPress-1>",
            lambda _event: self.start_hold(property_name, direction, owner),
        )
        button.bind("<ButtonRelease-1>", lambda _event: self.stop_hold(owner))
        button.bind("<Leave>", lambda _event: self.stop_hold(owner))

    def start_hold(
        self,
        property_name: str,
        direction: int,
        owner: str,
    ) -> None:
        self.stop_hold()
        if property_name not in self.ranges:
            return
        self.active_hold = HoldAction(property_name, direction, owner)
        self.write_log(self.get_active_message(property_name, direction), TEXT)
        self.move_active_hold()

    def move_active_hold(self) -> None:
        if self.active_hold is None or self.move_pending or self.is_closing:
            return
        action = self.active_hold
        multiplier = (
            ZOOM_SPEED_MODES[self.speed_mode]
            if action.property_name == "zoom"
            else SPEED_MODES[self.speed_mode]
        )
        self.move_pending = True
        generation = self.operation_generation

        def operation() -> int:
            return self.camera_service.move(
                action.property_name,
                action.direction,
                multiplier,
            )

        def completed(result: WorkerResult) -> None:
            self.move_pending = False
            if generation != self.operation_generation:
                return
            if result.error is not None:
                self.handle_camera_failure("PTZ failed", result.error)
                return
            self.position.set(action.property_name, int(result.value))
            self.update_position_display()
            if self.active_hold == action:
                self.schedule_job(
                    "repeat",
                    INITIAL_HOLD_DELAY_MS
                    if not self.jobs.get("repeat_started")
                    else REPEAT_INTERVAL_MS,
                    self.repeat_movement,
                )
                self.jobs["repeat_started"] = "active"

        self.submit_camera_operation("move", operation, completed)

    def repeat_movement(self) -> None:
        if self.active_hold is not None and not self.is_closing:
            self.move_active_hold()

    def stop_hold(self, owner: str | None = None) -> None:
        if (
            owner is not None
            and self.active_hold is not None
            and self.active_hold.owner != owner
        ):
            return
        previous = self.active_hold
        self.active_hold = None
        self.cancel_job("repeat")
        self.jobs.pop("repeat_started", None)
        if previous is not None:
            value = self.position.get(previous.property_name)
            if value is not None:
                self.write_log(
                    f"{previous.property_name.title()} stopped at {value}",
                    GREEN,
                )
            self.schedule_job(
                "position_refresh",
                POSITION_REFRESH_DELAY_MS,
                self.refresh_position,
            )

    def refresh_position(self) -> None:
        if not self.is_connected or self.move_pending or self.is_closing:
            return
        generation = self.operation_generation

        def completed(result: WorkerResult) -> None:
            if generation != self.operation_generation:
                return
            if result.error is not None:
                self.handle_camera_failure("Position read failed", result.error)
                return
            self.position = result.value
            self.update_position_display()

        self.submit_camera_operation(
            "read_position",
            self.camera_service.read_position,
            completed,
        )

    def handle_camera_failure(self, prefix: str, error: Exception) -> None:
        self.stop_hold()
        self.invalidate_operations()
        self.clear_camera_state()
        self.cancel_save_mode(render=False)
        self.connection_state = ConnectionState.ERROR
        self.render_state()
        self.write_log(f"{prefix}: {error}", RED)
        self.submit_camera_operation(
            "disconnect_after_failure",
            self.camera_service.disconnect,
            lambda _result: None,
        )

    @staticmethod
    def get_active_message(property_name: str, direction: int) -> str:
        messages = {
            ("pan", -1): "Panning left...",
            ("pan", 1): "Panning right...",
            ("tilt", 1): "Tilting up...",
            ("tilt", -1): "Tilting down...",
            ("zoom", 1): "Zooming in...",
            ("zoom", -1): "Zooming out...",
        }
        return messages.get((property_name, direction), "Moving...")

    def set_speed(self, speed_code: str) -> None:
        if speed_code not in SPEED_MODES:
            return
        self.speed_mode = speed_code
        self.update_speed_buttons()
        self.write_log(
            f"{speed_code.title()} | PT {SPEED_MODES[speed_code]}x | "
            f"Zoom {ZOOM_SPEED_MODES[speed_code]}x",
            TEXT,
        )

    def update_speed_buttons(self) -> None:
        for code, button in self.speed_buttons.items():
            button.config(
                bg=BUTTON_ACTIVE if code == self.speed_mode else BUTTON_BG,
                fg=TEXT if code == self.speed_mode else MUTED,
            )

    def update_position_display(self) -> None:
        def display(value: int | None) -> str:
            return "--" if value is None else str(value)

        self.position_label.config(
            text=(
                f"PAN {display(self.position.pan)}    "
                f"TILT {display(self.position.tilt)}    "
                f"ZOOM {display(self.position.zoom)}"
            )
        )

    def go_home(self) -> None:
        if not self.is_connected:
            return
        self.stop_hold()
        commands: list[tuple[str, int]] = []
        for property_name in ("pan", "tilt"):
            information = self.ranges.get(property_name)
            if information is None:
                continue
            target = (
                0
                if information.minimum <= 0 <= information.maximum
                else information.default
            )
            commands.append((property_name, information.align(target)))
        self.run_command_sequence(commands, "Camera moved to Home")

    def preset_clicked(self, preset_number: int) -> None:
        if self.save_mode:
            self.save_preset(preset_number)
        else:
            self.recall_preset(preset_number)

    def toggle_save_mode(self) -> None:
        if not self.is_connected or not self.ranges:
            self.write_log("Connect a PTZ camera before saving", YELLOW)
            return
        self.save_mode = not self.save_mode
        if self.save_mode:
            self.save_button.config(text="PICK", bg=PRESET_SAVE_MODE)
            self.update_preset_colours()
            self.write_log("Select preset 1, 2, 3 or 4", YELLOW)
        else:
            self.cancel_save_mode()
            self.write_log("Preset save cancelled", YELLOW)

    def cancel_save_mode(self, render: bool = True) -> None:
        self.save_mode = False
        if hasattr(self, "save_button"):
            self.save_button.config(text="SAVE", bg=BUTTON_BG)
        if render:
            self.update_preset_colours()

    def save_preset(self, preset_number: int) -> None:
        self.stop_hold()
        camera_key = self.camera_name
        if not camera_key or not self.ranges:
            return
        generation = self.operation_generation

        def completed(result: WorkerResult) -> None:
            if generation != self.operation_generation:
                return
            if result.error is not None:
                self.handle_camera_failure("Preset save failed", result.error)
                return
            self.position = result.value
            try:
                self.preset_store.save(
                    camera_key.strip(),
                    preset_number,
                    self.position,
                )
            except Exception as error:
                logger.exception("Unable to save preset")
                self.write_log(f"Preset save failed: {error}", RED)
                return
            self.cancel_save_mode()
            self.update_position_display()
            self.write_log(f"Preset {preset_number} saved", GREEN)

        self.submit_camera_operation(
            "read_position_for_preset",
            self.camera_service.read_position,
            completed,
        )

    def recall_preset(self, preset_number: int) -> None:
        self.stop_hold()
        camera_key = self.camera_name
        if not camera_key:
            return
        position = self.preset_store.get(camera_key.strip(), preset_number)
        if position is None:
            self.write_log(f"Preset {preset_number} is empty", YELLOW)
            return
        commands: list[tuple[str, int]] = []
        for property_name, value in position.supported_values(
            self.supported_properties
        ).items():
            commands.append((property_name, self.ranges[property_name].align(value)))
        self.run_command_sequence(commands, f"Preset {preset_number} recalled")

    def update_preset_colours(self) -> None:
        camera_key = (self.camera_name or "").strip()
        saved = self.preset_store.saved_numbers(camera_key)
        for number, button in enumerate(self.preset_buttons, start=1):
            if self.save_mode:
                colour = PRESET_SAVE_MODE
            elif number in saved:
                colour = PRESET_SAVED
            else:
                colour = BUTTON_BG
            button.config(bg=colour)

    def run_command_sequence(
        self,
        commands: list[tuple[str, int]],
        completion_message: str,
    ) -> None:
        self.stop_hold()
        self.invalidate_operations()
        if not commands:
            self.write_log("No supported PTZ command", YELLOW)
            return
        generation = self.operation_generation

        def execute_next(index: int = 0) -> None:
            if self.is_closing or generation != self.operation_generation:
                return
            if index >= len(commands):
                self.write_log(completion_message, GREEN)
                self.schedule_job(
                    "position_refresh",
                    POSITION_REFRESH_DELAY_MS,
                    self.refresh_position,
                )
                return
            property_name, target_value = commands[index]

            def operation() -> int:
                return self.camera_service.set_value(property_name, target_value)

            def completed(result: WorkerResult) -> None:
                if generation != self.operation_generation:
                    return
                if result.error is not None:
                    self.handle_camera_failure("Command failed", result.error)
                    return
                actual = int(result.value)
                self.position.set(property_name, actual)
                self.update_position_display()
                self.write_log(f"Setting {property_name.upper()} to {actual}", TEXT)
                self.schedule_job(
                    "sequence",
                    PRESET_COMMAND_DELAY_MS,
                    lambda: execute_next(index + 1),
                )

            self.submit_camera_operation("set_value", operation, completed)

        execute_next()

    def handle_escape(self, _event: tk.Event | None = None) -> str:
        if self.save_mode:
            self.cancel_save_mode()
            self.write_log("Preset save cancelled", YELLOW)
        elif self.active_hold is not None:
            self.stop_hold()
            self.write_log("Movement stopped", YELLOW)
        else:
            self.invalidate_operations()
            self.write_log("Operation cancelled", YELLOW)
        return "break"

    def keyboard_pressed(self, event: tk.Event) -> str | None:
        if isinstance(event.widget, (ttk.Combobox, tk.Entry, tk.Text)):
            return None
        movement_keys = {
            "Left": ("pan", -1),
            "Right": ("pan", 1),
            "Up": ("tilt", 1),
            "Down": ("tilt", -1),
            "plus": ("zoom", 1),
            "equal": ("zoom", 1),
            "minus": ("zoom", -1),
            "KP_Add": ("zoom", 1),
            "KP_Subtract": ("zoom", -1),
        }
        if event.keysym in movement_keys:
            owner = f"key:{event.keysym}"
            if self.active_hold is None:
                property_name, direction = movement_keys[event.keysym]
                self.start_hold(property_name, direction, owner)
            return "break"
        if event.keysym.lower() == "h":
            self.go_home()
            return "break"
        if event.keysym in {"1", "2", "3", "4"}:
            preset_number = int(event.keysym)
            if event.state & 0x0004:
                self.save_preset(preset_number)
            else:
                self.preset_clicked(preset_number)
            return "break"
        return None

    def keyboard_released(self, event: tk.Event) -> None:
        self.stop_hold(f"key:{event.keysym}")

    def schedule_job(
        self,
        name: str,
        delay_ms: int,
        callback: Callable[[], None],
    ) -> None:
        self.cancel_job(name)

        def wrapped() -> None:
            self.jobs.pop(name, None)
            if not self.is_closing:
                callback()

        self.jobs[name] = self.root.after(delay_ms, wrapped)

    def cancel_job(self, name: str) -> None:
        job_id = self.jobs.pop(name, None)
        if job_id is not None and job_id != "active":
            try:
                self.root.after_cancel(job_id)
            except tk.TclError:
                pass

    def invalidate_operations(self) -> None:
        self.operation_generation += 1
        self.cancel_job("sequence")
        self.cancel_job("connect")
        self.cancel_job("position_refresh")

    def cancel_all_jobs(self) -> None:
        for name in list(self.jobs):
            self.cancel_job(name)

    def start_drag(self, event: tk.Event) -> None:
        self.drag_offset_x = event.x_root - self.root.winfo_x()
        self.drag_offset_y = event.y_root - self.root.winfo_y()

    def drag_window(self, event: tk.Event) -> None:
        self.root.geometry(
            f"+{event.x_root - self.drag_offset_x}"
            f"+{event.y_root - self.drag_offset_y}"
        )

    def place_bottom_right(self) -> None:
        self.root.update_idletasks()
        x_position = max(
            0,
            self.root.winfo_screenwidth()
            - self.root.winfo_reqwidth()
            - RIGHT_MARGIN,
        )
        y_position = max(
            0,
            self.root.winfo_screenheight()
            - self.root.winfo_reqheight()
            - BOTTOM_MARGIN,
        )
        self.root.geometry(f"+{x_position}+{y_position}")

    def toggle_tooltips(self) -> None:
        self.tooltips_enabled = not self.tooltips_enabled
        ToolTip.set_enabled(self.tooltips_enabled)
        if self.tooltips_enabled:
            self.tooltip_toggle_button.config(fg=TOOLTIP_ENABLED)
            self.write_log("Help tooltips enabled", TEXT)
        else:
            self.tooltip_toggle_button.config(fg=TOOLTIP_DISABLED)
            self.write_log("Help tooltips disabled", MUTED)

    def change_opacity(self) -> None:
        self.opacity_index = (self.opacity_index + 1) % len(OPACITY_VALUES)
        opacity = OPACITY_VALUES[self.opacity_index]
        self.root.attributes("-alpha", opacity)
        self.write_log(f"Opacity: {int(opacity * 100)}%", TEXT)

    def minimize_window(self) -> None:
        self.stop_hold()
        self.is_minimized = True
        self.root.overrideredirect(False)
        self.root.update_idletasks()
        self.root.iconify()

    def window_mapped(self, _event: tk.Event | None = None) -> None:
        if self.is_minimized and self.root.state() == "normal":
            self.is_minimized = False
            self.schedule_job("restore", 80, self.restore_overlay_style)

    def restore_overlay_style(self) -> None:
        if self.is_closing or not self.root.winfo_exists():
            return
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", OPACITY_VALUES[self.opacity_index])
        self.root.lift()
        self.write_log("PTZ utility restored", TEXT)

    def write_log(self, message: str, colour: str) -> None:
        if self.is_closing:
            return
        short_message = str(message)
        if len(short_message) > 55:
            short_message = short_message[:52] + "..."
        try:
            self.log_label.config(text=short_message, fg=colour)
        except tk.TclError:
            pass

    def close_application(self) -> None:
        if self.is_closing:
            return
        self.is_closing = True
        self.active_hold = None
        self.callbacks.clear()
        self.cancel_all_jobs()
        self.camera_worker.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        context = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(context):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        logger.warning("Unable to configure Windows DPI awareness")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    configure_logging()
    enable_windows_dpi_awareness()
    root = tk.Tk()
    CompactPTZRemote(root)
    root.mainloop()


if __name__ == "__main__":
    main()

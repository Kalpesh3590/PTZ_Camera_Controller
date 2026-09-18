from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import sys
import threading
import tkinter as tk
from dataclasses import asdict, dataclass
from enum import Enum, auto
from pathlib import Path
from tkinter import messagebox, ttk
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

THEMES = {"DARK": {"BG": "#0F172A", "HEADER_BG": "#1E293B", "SECTION_BG": "#172033", "BUTTON_BG": "#334155",
                   "BUTTON_HOVER": "#475569", "BUTTON_ACTIVE": "#2563EB", "BUTTON_PRESSED": "#1D4ED8",
                   "BORDER": "#475569", "TEXT": "#F8FAFC", "MUTED": "#94A3B8", "DISABLED": "#64748B",
                   "GREEN": "#22C55E", "YELLOW": "#F59E0B", "RED": "#EF4444", "PRESET_SAVED": "#047857",
                   "PRESET_SAVE_MODE": "#D97706", "TOOLTIP_BG": "#020617", "TOOLTIP_ENABLED": "#3B82F6",
                   "TOOLTIP_DISABLED": "#64748B", "ROW_ALT": "#1B2940", "ON_ACCENT": "#FFFFFF", "ON_WARNING": "#111827",
                   "DISABLED_BG": "#253247", "DISABLED_FG": "#718096", "INPUT_BG": "#334155"},
          "LIGHT": {"BG": "#F3F6FA", "HEADER_BG": "#E2E8F0", "SECTION_BG": "#FFFFFF", "BUTTON_BG": "#D9E2EC",
                    "BUTTON_HOVER": "#C5D2E0", "BUTTON_ACTIVE": "#2563EB", "BUTTON_PRESSED": "#1D4ED8",
                    "BORDER": "#B7C3D0", "TEXT": "#172033", "MUTED": "#526273", "DISABLED": "#8A98A8",
                    "GREEN": "#15803D", "YELLOW": "#B45309", "RED": "#DC2626", "PRESET_SAVED": "#047857",
                    "PRESET_SAVE_MODE": "#C2410C", "TOOLTIP_BG": "#FFFFFF", "TOOLTIP_ENABLED": "#1D4ED8",
                    "TOOLTIP_DISABLED": "#7B8794", "ROW_ALT": "#E8EEF5", "ON_ACCENT": "#FFFFFF",
                    "ON_WARNING": "#111827", "DISABLED_BG": "#E4EAF1", "DISABLED_FG": "#7F8C9B", "INPUT_BG": "#D6E0EA"}}


def apply_theme_palette(theme_name: str) -> None:
    global BG, HEADER_BG, SECTION_BG, BUTTON_BG, BUTTON_HOVER, BUTTON_ACTIVE
    global BUTTON_PRESSED, BORDER, TEXT, MUTED, DISABLED, GREEN, YELLOW, RED
    global PRESET_SAVED, PRESET_SAVE_MODE, TOOLTIP_BG, TOOLTIP_ENABLED, TOOLTIP_DISABLED
    palette = THEMES.get(str(theme_name).upper(), THEMES["DARK"])
    for name in ("BG", "HEADER_BG", "SECTION_BG", "BUTTON_BG", "BUTTON_HOVER", "BUTTON_ACTIVE", "BUTTON_PRESSED",
                 "BORDER", "TEXT", "MUTED", "DISABLED", "GREEN", "YELLOW", "RED", "PRESET_SAVED", "PRESET_SAVE_MODE",
                 "TOOLTIP_BG", "TOOLTIP_ENABLED", "TOOLTIP_DISABLED"):
        globals()[name] = palette[name]


def current_palette() -> dict[str, str]:
    return THEMES["LIGHT"] if BG == THEMES["LIGHT"]["BG"] else THEMES["DARK"]


def accent_text() -> str:
    return current_palette()["ON_ACCENT"]


def warning_text() -> str:
    return current_palette()["ON_WARNING"]


APP_TITLE: Final = "PTZ Remote"
DEFAULT_OPACITY: Final = 1.0
OPACITY_VALUES: Final = (1.00, 0.50, 0.40, 0.30, 0.20)
INITIAL_HOLD_DELAY_MS: Final = 120
REPEAT_INTERVAL_MS: Final = 90
POSITION_REFRESH_DELAY_MS: Final = 300
PRESET_COMMAND_DELAY_MS: Final = 300
WORKER_POLL_INTERVAL_MS: Final = 30
HALL_STEP_INTERVAL_MS: Final = 220
HALL_MIN_STEPS: Final = 12
HALL_MAX_STEPS: Final = 42
HALL_SPEED_PROFILES: Final = {"CINEMATIC": (100, 34, 90), "SLOW": (80, 26, 68), "NORMAL": (60, 18, 48),
                              "FAST": (35, 8, 22), }
HALL_RETURN_PROFILE: Final = (30, 7, 18)
ENABLE_DEMO_MODE: Final = True
RIGHT_MARGIN: Final = 12
BOTTOM_MARGIN: Final = 58
PRESET_NUMBERS: Final = range(1, 5)
PTZ_PROPERTIES: Final = ("pan", "tilt", "zoom")
PREFERRED_CAMERA_SCORES: Final = {"c1612": 100, "rapoo": 80, "ptz": 40, "conference": 30, "usb video": 10, }
SPEED_MODES: Final = {"FINE": 1, "NORMAL": 3, "FAST": 6}
ZOOM_SPEED_MODES: Final = {"FINE": 100, "NORMAL": 200, "FAST": 350}

DEFAULT_USER_SETTINGS = {"schema_version": 1,
                         "general": {"theme": "DARK", "opacity": 1.0, "hover_boost": 0.18, "demo_mode": True,
                                     "tooltips_enabled": False, },
                         "manual": {"fine_pt": 1, "normal_pt": 3, "fast_pt": 6, "fine_zoom": 100, "normal_zoom": 200,
                                    "fast_zoom": 350, "hold_delay_ms": 120, "repeat_interval_ms": 90, },
                         "hall": {"cinematic_interval": 100, "cinematic_min": 34, "cinematic_max": 90,
                                  "slow_interval": 80, "slow_min": 26, "slow_max": 68, "normal_interval": 60,
                                  "normal_min": 18, "normal_max": 48, "fast_interval": 35, "fast_min": 8,
                                  "fast_max": 22, "return_interval": 30, "return_min": 7, "return_max": 18, }, }


def settings_file_path() -> Path:
    base = Path(os.getenv("LOCALAPPDATA", Path.home() / ".ptzremote")) / "PTZRemote"
    return base / "settings.json"


def merged_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    result = json.loads(json.dumps(DEFAULT_USER_SETTINGS))
    if not isinstance(raw, dict):
        return result
    for section in ("general", "manual", "hall"):
        supplied = raw.get(section)
        if isinstance(supplied, dict):
            for key, value in supplied.items():
                if key in result[section]:
                    result[section][key] = value
    return result


def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    result = merged_settings(settings)
    general = result["general"]
    general["theme"] = str(general.get("theme", "DARK")).upper()
    if general["theme"] not in THEMES:
        general["theme"] = "DARK"
    general["opacity"] = max(0.2, min(1.0, float(general["opacity"])))
    general["hover_boost"] = max(0.0, min(0.5, float(general["hover_boost"])))
    general["demo_mode"] = bool(general["demo_mode"])
    general["tooltips_enabled"] = bool(general.get("tooltips_enabled", False))
    manual = result["manual"]
    for key in ("fine_pt", "normal_pt", "fast_pt"):
        manual[key] = max(1, min(50, int(manual[key])))
    for key in ("fine_zoom", "normal_zoom", "fast_zoom"):
        manual[key] = max(1, min(5000, int(manual[key])))
    manual["hold_delay_ms"] = max(50, min(1000, int(manual["hold_delay_ms"])))
    manual["repeat_interval_ms"] = max(30, min(1000, int(manual["repeat_interval_ms"])))
    hall = result["hall"]
    for profile in ("cinematic", "slow", "normal", "fast", "return"):
        interval = f"{profile}_interval"
        minimum = f"{profile}_min"
        maximum = f"{profile}_max"
        hall[interval] = max(20, min(1000, int(hall[interval])))
        hall[minimum] = max(2, min(200, int(hall[minimum])))
        hall[maximum] = max(hall[minimum], min(300, int(hall[maximum])))
    return result


def load_user_settings() -> dict[str, Any]:
    path = settings_file_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = None
    return validate_settings(raw or {})


def save_user_settings(settings: dict[str, Any]) -> None:
    path = settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(validate_settings(settings), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def apply_user_settings(settings: dict[str, Any]) -> None:
    global DEFAULT_OPACITY, INITIAL_HOLD_DELAY_MS, REPEAT_INTERVAL_MS, ENABLE_DEMO_MODE, HALL_RETURN_PROFILE
    validated = validate_settings(settings)
    general = validated["general"]
    apply_theme_palette(general["theme"])
    manual = validated["manual"]
    hall = validated["hall"]
    DEFAULT_OPACITY = general["opacity"]
    INITIAL_HOLD_DELAY_MS = manual["hold_delay_ms"]
    REPEAT_INTERVAL_MS = manual["repeat_interval_ms"]
    ENABLE_DEMO_MODE = general["demo_mode"]
    SPEED_MODES.update({"FINE": manual["fine_pt"], "NORMAL": manual["normal_pt"], "FAST": manual["fast_pt"]})
    ZOOM_SPEED_MODES.update({"FINE": manual["fine_zoom"], "NORMAL": manual["normal_zoom"], "FAST": manual["fast_zoom"]})
    HALL_SPEED_PROFILES.update({"CINEMATIC": (hall["cinematic_interval"], hall["cinematic_min"], hall["cinematic_max"]),
                                "SLOW": (hall["slow_interval"], hall["slow_min"], hall["slow_max"]),
                                "NORMAL": (hall["normal_interval"], hall["normal_min"], hall["normal_max"]),
                                "FAST": (hall["fast_interval"], hall["fast_min"], hall["fast_max"]), })
    HALL_RETURN_PROFILE = (hall["return_interval"], hall["return_min"], hall["return_max"])


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
    transition_speed: str = "DEFAULT"
    pause_enabled: bool = False
    pause_seconds: int = 1

    def get(self, property_name: str) -> int | None:
        return getattr(self, property_name)

    def set(self, property_name: str, value: int | None) -> None:
        setattr(self, property_name, value)

    def supported_values(self, supported: set[str]) -> dict[str, int]:
        return {name: value for name in PTZ_PROPERTIES if name in supported and (value := self.get(name)) is not None}


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

    def save(self, camera_key: str, preset_number: int, position: PTZPosition, ) -> None:
        if preset_number not in PRESET_NUMBERS:
            raise ValueError(f"Invalid preset number: {preset_number}")
        values = {name: value for name, value in asdict(position).items() if
                  name in PTZ_PROPERTIES and isinstance(value, int) and not isinstance(value, bool)}
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
                clean_values = {name: value for name, value in values.items() if
                                name in PTZ_PROPERTIES and isinstance(value, int) and not isinstance(value, bool)}
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
        self.demo_mode = False

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
            camera_properties = (supported.get("camera", []) if isinstance(supported, dict) else [])
            normalized = {self.normalize_property_name(name) for name in camera_properties}
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
            if not ranges and ENABLE_DEMO_MODE:
                self.demo_mode = True
                ranges = {"pan": PropertyRange(-170, 170, 1, 0), "tilt": PropertyRange(-90, 90, 1, 0),
                          "zoom": PropertyRange(100, 1600, 10, 100), }
                self.ranges = ranges
                self.position = PTZPosition(0, 0, 100)
                return CameraSnapshot(camera_name + " [DEMO]", dict(ranges), PTZPosition(0, 0, 100))
            self.demo_mode = False
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
        self.demo_mode = False
        if controller is not None:
            try:
                controller.close()
            except Exception:
                logger.exception("Unable to close camera")

    def read_position(self) -> PTZPosition:
        if self.demo_mode:
            return PTZPosition(self.position.pan, self.position.tilt, self.position.zoom)
        position = PTZPosition()
        if self.controller is not None:
            for property_name in self.ranges:
                try:
                    position.set(property_name, int(getattr(self.controller, property_name)), )
                except Exception:
                    logger.exception("Unable to read %s", property_name)
        self.position = position
        return PTZPosition(position.pan, position.tilt, position.zoom)

    def set_value(self, property_name: str, requested_value: int) -> int:
        self._validate_property(property_name)
        aligned_value = self.ranges[property_name].align(requested_value)
        if not self.demo_mode:
            setattr(self.controller, property_name, aligned_value)
        self.position.set(property_name, aligned_value)
        return aligned_value

    def set_position(self, position: PTZPosition) -> PTZPosition:
        if self.controller is None and not self.demo_mode:
            raise RuntimeError("Camera disconnected")
        result = PTZPosition(self.position.pan, self.position.tilt, self.position.zoom)
        for name in PTZ_PROPERTIES:
            value = position.get(name)
            if value is None or name not in self.ranges:
                continue
            aligned = self.ranges[name].align(value)
            if not self.demo_mode:
                setattr(self.controller, name, aligned)
            result.set(name, aligned)
        self.position = result
        return PTZPosition(result.pan, result.tilt, result.zoom)

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
        return self.set_value(property_name, current_value + direction * movement, )

    def home_commands(self) -> list[tuple[str, int]]:
        commands: list[tuple[str, int]] = []
        for property_name in ("pan", "tilt"):
            information = self.ranges.get(property_name)
            if information is None:
                continue
            target = (0 if information.minimum <= 0 <= information.maximum else information.default)
            commands.append((property_name, information.align(target)))
        return commands

    def _validate_property(self, property_name: str) -> None:
        if self.controller is None and not self.demo_mode:
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
            minimum = getattr(raw_range, "min", getattr(raw_range, "minimum", None), )
            maximum = getattr(raw_range, "max", getattr(raw_range, "maximum", None), )
            step = getattr(raw_range, "step", None)
            default = getattr(raw_range, "default", None)
        values = {"minimum": minimum, "maximum": maximum, "step": step, "default": default, }
        missing = [name for name, value in values.items() if value is None]
        if missing:
            raise ValueError(f"Invalid property range; missing {', '.join(missing)}: {raw_range!r}")
        minimum_value = int(minimum)
        maximum_value = int(maximum)
        if minimum_value > maximum_value:
            raise ValueError(f"Invalid property range: {minimum_value} > {maximum_value}")
        parsed = PropertyRange(minimum=minimum_value, maximum=maximum_value, step=max(1, abs(int(step))),
                               default=int(default), )
        return PropertyRange(minimum=parsed.minimum, maximum=parsed.maximum, step=parsed.step,
                             default=parsed.align(parsed.default), )

    @staticmethod
    def normalize_property_name(value: Any) -> str:
        return str(value).strip().lower().rsplit(".", 1)[-1]


class CameraWorker:
    def __init__(self, service: CameraService) -> None:
        self.service = service
        self.requests: queue.Queue[tuple[int, str, Callable[[], Any]] | None] = queue.Queue()
        self.results: queue.Queue[WorkerResult] = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="PTZCameraWorker", daemon=True, )
        self.thread.start()

    def submit(self, request_id: int, operation: str, action: Callable[[], Any], ) -> None:
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
            label = tk.Label(self.window, text=self.text, bg=TOOLTIP_BG, fg=TEXT, padx=8, pady=5, justify="left",
                             relief="solid", borderwidth=1, font=("Segoe UI", 8), )
            label.pack()
            self.window.update_idletasks()
            width = self.window.winfo_reqwidth()
            height = self.window.winfo_reqheight()
            screen_width = self.widget.winfo_screenwidth()
            screen_height = self.widget.winfo_screenheight()
            x_position = max(5, min(center_x - width // 2, screen_width - width - 5), )
            if y_position + height > screen_height - 5:
                y_position = self.widget.winfo_rooty() - height - 7
            y_position = max(5, min(y_position, screen_height - height - 5), )
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


class HallMapStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.data: dict[str, list[dict[str, int]]] = {}

    def load(self) -> None:
        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError):
            logger.exception("Unable to load hall map")
            return
        if isinstance(raw, dict):
            self.data = raw

    def get(self, camera_key: str) -> list[PTZPosition]:
        result: list[PTZPosition] = []
        for item in self.data.get(camera_key.strip(), []):
            if isinstance(item, dict):
                clean = {k: v for k, v in item.items() if
                         k in PTZ_PROPERTIES and isinstance(v, int) and not isinstance(v, bool)}
                speed = str(item.get("transition_speed", "DEFAULT")).upper()
                if speed not in {"DEFAULT", *HALL_SPEED_PROFILES}:
                    speed = "DEFAULT"
                pause_enabled = item.get("pause_enabled", False) is True
                pause_seconds = item.get("pause_seconds", 1)
                if not isinstance(pause_seconds, int) or isinstance(pause_seconds, bool):
                    pause_seconds = 1
                pause_seconds = max(1, min(5, pause_seconds))
                if clean:
                    result.append(PTZPosition(**clean, transition_speed=speed, pause_enabled=pause_enabled,
                                              pause_seconds=pause_seconds))
        return result

    def delete(self, camera_key: str) -> None:
        self.data.pop(camera_key.strip(), None)
        self._write_atomic()

    def _write_atomic(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.file_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.file_path)

    def save(self, camera_key: str, points: list[PTZPosition]) -> None:
        if len(points) < 2:
            raise ValueError("At least two mapping points are required")
        self.data[camera_key.strip()] = [
            {**{k: v for k, v in asdict(point).items() if k in PTZ_PROPERTIES and v is not None},
             "transition_speed": point.transition_speed, "pause_enabled": bool(point.pause_enabled),
             "pause_seconds": max(1, min(5, int(point.pause_seconds)))} for point in points]
        self._write_atomic()


class CompactPTZRemote:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.user_settings = load_user_settings()
        apply_user_settings(self.user_settings)
        self.settings_window: tk.Toplevel | None = None
        self.settings_variables: dict[str, tk.Variable] = {}
        # Super Compact Mode uses the same camera service and worker as the full UI.
        self.compact_window: tk.Toplevel | None = None
        self.compact_status_dot: tk.Label | None = None
        self.compact_speed_button: tk.Button | None = None
        self.compact_control_buttons: list[tuple[tk.Button, str]] = []
        self.compact_drag_offset_x = 0
        self.compact_drag_offset_y = 0
        self.compact_last_position: tuple[int, int] | None = None
        self.camera_service = CameraService(duvc)
        self.camera_worker = CameraWorker(self.camera_service)
        self.camera_names: list[str] = []
        self.camera_name: str | None = None
        self.ranges: dict[str, PropertyRange] = {}
        self.position = PTZPosition()
        self.preset_store = PresetStore(self._preset_file_path())
        self.hall_map_store = HallMapStore(self._hall_map_file_path())
        self.hall_points: list[PTZPosition] = []
        self.hall_wizard: tk.Toplevel | None = None
        self.camera_info_window: tk.Toplevel | None = None
        self.camera_info_pinned = False
        self.hall_point_list: ttk.Treeview | None = None
        self.hall_count_label: tk.Label | None = None
        self.hall_running = False
        self.hall_paused = False
        self.hall_speed_mode = "CINEMATIC"
        self.hall_speed_variable: tk.StringVar | None = None
        self.hall_speed_buttons: dict[str, tk.Button] = {}
        self.point_speed_variable: tk.StringVar | None = None
        self.point_speed_buttons: dict[str, tk.Button] = {}
        self.hall_wizard_status: tk.Label | None = None
        self.hall_finish_button: tk.Button | None = None
        self.hall_test_pause_button: tk.Button | None = None
        self.hall_returning = False
        self.hall_return_position: PTZPosition | None = None
        self.current_hall_segment_speed = "CINEMATIC"
        self.connection_state = ConnectionState.DISCONNECTED
        self.active_hold: HoldAction | None = None
        self.pressed_keyboard_keys: set[str] = set()
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
        # Shared opacity state for both the full controller and Super Compact Mode.
        self.base_opacity = max(0.2, min(1.0, float(self.user_settings["general"]["opacity"])), )
        self.opacity_index = min(range(len(OPACITY_VALUES)),
                                 key=lambda index: abs(OPACITY_VALUES[index] - self.base_opacity), )
        self.pointer_inside_root = False
        self.pointer_inside_compact = False
        self.speed_mode = "NORMAL"
        self.tooltips_enabled = bool(self.user_settings["general"].get("tooltips_enabled", False))
        ToolTip.set_enabled(self.tooltips_enabled)
        self.configure_window()
        self.configure_styles()
        self.create_interface()
        self.preset_store.load()
        self.hall_map_store.load()
        self.render_state()
        self.root.protocol("WM_DELETE_WINDOW", self.close_application)
        self.root.bind("<Map>", self.window_mapped, add="+")
        self.root.bind("<Escape>", self.handle_escape, add="+")
        self.root.bind("<Enter>", self.controller_pointer_enter, add="+")
        self.root.bind("<Leave>", self.controller_pointer_leave, add="+")
        self.root.bind("<Button-1>", self.activate_keyboard_control, add="+")
        self.root.bind("<FocusOut>", self.keyboard_focus_lost, add="+")
        self.root.bind_all("<KeyPress>", self.keyboard_pressed, add="+")
        self.root.bind_all("<KeyRelease>", self.keyboard_released, add="+")
        self.schedule_job("worker", WORKER_POLL_INTERVAL_MS, self.poll_worker)
        self.schedule_job("refresh", 200, self.refresh_cameras)
        self.schedule_job("placement", 500, self.place_bottom_right)
        self.schedule_job("keyboard_focus", 550, self.activate_keyboard_control)

    @staticmethod
    def _preset_file_path() -> Path:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            directory = Path(base) / "PTZRemote"
        else:
            directory = Path.home() / "AppData" / "Local" / "PTZRemote"
        return directory / "ptz_presets.json"

    @staticmethod
    def _hall_map_file_path() -> Path:
        base = os.environ.get("LOCALAPPDATA")
        directory = Path(base) / "PTZRemote" if base else Path.home() / "AppData" / "Local" / "PTZRemote"
        return directory / "hall_map.json"

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
        self.root.attributes("-alpha", self.base_opacity)
        self.root.resizable(False, False)

    def configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        palette = current_palette()
        style.configure("Compact.TCombobox", fieldbackground=palette["INPUT_BG"], background=palette["INPUT_BG"],
                        foreground=TEXT, arrowcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        padding=5)
        style.map("Compact.TCombobox",
                  fieldbackground=[("disabled", palette["DISABLED_BG"]), ("readonly", palette["INPUT_BG"])],
                  foreground=[("disabled", palette["DISABLED_FG"]), ("readonly", TEXT)],
                  selectbackground=[("readonly", palette["INPUT_BG"])], selectforeground=[("readonly", TEXT)])
        style.configure("Hall.Treeview", background=SECTION_BG, fieldbackground=SECTION_BG, foreground=TEXT,
                        rowheight=30, borderwidth=0, relief="flat", font=("Segoe UI", 9))
        style.map("Hall.Treeview", background=[("selected", BUTTON_ACTIVE)],
                  foreground=[("selected", palette["ON_ACCENT"])])
        style.configure("Hall.Treeview.Heading", background=HEADER_BG, foreground=TEXT, borderwidth=0, relief="flat",
                        padding=(8, 8), font=("Segoe UI", 9, "bold"))
        style.map("Hall.Treeview.Heading", background=[("active", BUTTON_HOVER)])
        style.configure("Settings.Vertical.TScrollbar", background=BUTTON_BG, troughcolor=BG, bordercolor=BORDER,
                        arrowcolor=TEXT, lightcolor=BUTTON_BG, darkcolor=BUTTON_BG)
        style.map("Settings.Vertical.TScrollbar", background=[("active", BUTTON_HOVER)])

    def create_interface(self) -> None:
        self.outer_frame = tk.Frame(self.root, bg=BG, highlightbackground=BORDER, highlightthickness=1, )
        self.outer_frame.pack(fill="both", expand=True)
        self.create_header()
        self.content_frame = tk.Frame(self.outer_frame, bg=BG)
        self.content_frame.pack(fill="both", padx=6, pady=5)
        self.create_camera_row()
        self.create_ptz_section()
        self.create_zoom_section()
        self.create_speed_section()
        self.create_preset_section()
        self.create_hall_section()
        self.create_position_display()
        self.create_log_display()

    def create_header(self) -> None:
        self.header_frame = tk.Frame(self.outer_frame, bg=HEADER_BG, height=27)
        self.header_frame.pack(fill="x")
        self.header_frame.pack_propagate(False)
        self.status_dot = tk.Label(self.header_frame, text="●", bg=HEADER_BG, fg=RED, font=("Segoe UI", 9), )
        self.status_dot.pack(side="left", padx=(8, 4))
        ToolTip(self.status_dot, "Connection status\nGreen: PTZ ready\nYellow: connecting\nRed: disconnected", )
        self.title_label = tk.Label(self.header_frame, text="PTZ CONTROL", bg=HEADER_BG, fg=TEXT,
                                    font=("Segoe UI", 8, "bold"), )
        self.title_label.pack(side="left", padx=(0, 4))
        buttons = (("×", self.close_application, RED, "Close PTZ utility"),
                   ("▰", self.enter_super_compact_mode, GREEN, "Open super compact screen-sharing mode"),
                   ("◐", self.change_opacity, MUTED, "Change window transparency"),
                   ("_", self.minimize_window, MUTED, "Minimize to taskbar"),
                   ("⚙", self.open_settings, MUTED, "Open settings and help"),
                   ("↻", self.refresh_cameras, MUTED, "Refresh USB cameras"),)
        for text, command, colour, tooltip in buttons:
            button = self.create_header_button(text, command, colour)
            button.pack(side="right", padx=(0, 2) if text == "×" else 0)
            if text == "⚙":
                self.settings_button = button
            ToolTip(button, tooltip)
        for widget in (self.header_frame, self.status_dot, self.title_label):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag_window)
        ToolTip(self.title_label, "Drag to move the utility")

    def enter_super_compact_mode(self) -> None:
        """Hide the full controller and show a discreet shared-backend overlay."""
        if self.is_closing:
            return
        self.stop_hold()
        if self.compact_window is None or not self.compact_window.winfo_exists():
            self.create_super_compact_window()
        self.root.withdraw()
        self.position_super_compact_window()
        self.pointer_inside_compact = False
        self.compact_window.deiconify()
        self.apply_compact_opacity()
        self.compact_window.lift()
        self.compact_window.focus_force()
        self.update_super_compact_state()

    def create_super_compact_window(self) -> None:
        window = tk.Toplevel(self.root)
        self.compact_window = window
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-alpha", self.base_opacity)
        window.configure(bg=BORDER)
        window.protocol("WM_DELETE_WINDOW", self.exit_super_compact_mode)
        window.bind("<Escape>", lambda _event: self.exit_super_compact_mode())
        window.bind("<FocusOut>", lambda _event: self.stop_hold())
        window.bind("<Enter>", self.compact_pointer_enter, add="+")
        window.bind("<Leave>", self.compact_pointer_leave, add="+")

        panel = tk.Frame(window, bg=HEADER_BG, highlightbackground=BORDER, highlightthickness=1)
        panel.pack(fill="both", expand=True)

        drag = tk.Frame(panel, bg=HEADER_BG, width=18)
        drag.pack(side="left", fill="y")
        drag.pack_propagate(False)
        grip = tk.Label(drag, text="⋮", bg=HEADER_BG, fg=MUTED, font=("Segoe UI", 12, "bold"), cursor="fleur")
        grip.pack(expand=True)
        for widget in (drag, grip):
            widget.bind("<ButtonPress-1>", self.start_super_compact_drag)
            widget.bind("<B1-Motion>", self.drag_super_compact_window)
            widget.bind("<ButtonRelease-1>", self.finish_super_compact_drag)

        self.compact_status_dot = tk.Label(panel, text="●", bg=HEADER_BG, fg=RED, font=("Segoe UI", 9))
        self.compact_status_dot.pack(side="left", padx=(5, 4))

        controls = tk.Frame(panel, bg=HEADER_BG)
        controls.pack(side="left", padx=(0, 3), pady=4)
        self.compact_control_buttons = []

        def hold_button(text: str, prop: str, direction: int, owner: str) -> tk.Button:
            button = tk.Button(controls, text=text, width=2, bg=BUTTON_BG, fg=TEXT, activebackground=BUTTON_ACTIVE,
                               activeforeground=accent_text(), relief="flat", borderwidth=0,
                               font=("Segoe UI Symbol", 10, "bold"), cursor="hand2", takefocus=False, )
            button.pack(side="left", padx=1, ipady=2)
            self.bind_hold_button(button, prop, direction, owner)
            # A release can occur outside the button/window. This is a final safety net.
            button.bind("<ButtonRelease-1>", lambda _event, token=owner: self.stop_hold(token), add="+")
            self.compact_control_buttons.append((button, prop))
            return button

        hold_button("◀", "pan", -1, "compact:left")
        hold_button("▲", "tilt", 1, "compact:up")
        hold_button("▼", "tilt", -1, "compact:down")
        hold_button("▶", "pan", 1, "compact:right")
        hold_button("−", "zoom", -1, "compact:zoom_out")
        hold_button("+", "zoom", 1, "compact:zoom_in")

        for number in (1, 2, 3):
            button = tk.Button(controls, text=str(number), width=2,
                               command=lambda preset=number: self.recall_preset(preset), bg=BUTTON_BG, fg=TEXT,
                               activebackground=PRESET_SAVED, activeforeground=accent_text(), relief="flat",
                               borderwidth=0, font=("Segoe UI", 8, "bold"), cursor="hand2", takefocus=False, )
            button.pack(side="left", padx=1, ipady=3)
            self.compact_control_buttons.append((button, "preset"))

        self.compact_speed_button = tk.Button(controls, text="N", width=2, command=self.cycle_compact_speed,
                                              bg=BUTTON_ACTIVE, fg=accent_text(), activebackground=BUTTON_PRESSED,
                                              activeforeground=accent_text(), relief="flat", borderwidth=0,
                                              font=("Segoe UI", 8, "bold"), cursor="hand2", takefocus=False, )
        self.compact_speed_button.pack(side="left", padx=1, ipady=3)

        restore = tk.Button(controls, text="□", width=2, command=self.exit_super_compact_mode, bg=BUTTON_BG, fg=GREEN,
                            activebackground=BUTTON_HOVER, activeforeground=TEXT, relief="flat", borderwidth=0,
                            font=("Segoe UI Symbol", 10, "bold"), cursor="hand2", takefocus=False, )
        restore.pack(side="left", padx=1, ipady=2)

        close = tk.Button(controls, text="×", width=2, command=self.close_application, bg=HEADER_BG, fg=RED,
                          activebackground=BUTTON_HOVER, activeforeground=TEXT, relief="flat", borderwidth=0,
                          font=("Segoe UI Symbol", 10, "bold"), cursor="hand2", takefocus=False, )
        close.pack(side="left", padx=(1, 2), ipady=2)

        window.update_idletasks()
        self.position_super_compact_window()

    def rebuild_super_compact_for_theme(self) -> None:
        """Recreate Super Compact Mode so every widget uses the active palette."""
        window = self.compact_window
        if window is None or not window.winfo_exists():
            self.compact_window = None
            return

        try:
            was_visible = window.state() != "withdrawn"
        except tk.TclError:
            was_visible = False

        try:
            self.compact_last_position = (window.winfo_x(), window.winfo_y())
        except tk.TclError:
            pass

        self.pointer_inside_compact = False
        try:
            window.destroy()
        except tk.TclError:
            pass
        self.compact_window = None

        # Hidden compact windows are recreated lazily on the next mode switch.
        if not was_visible or self.is_closing:
            return

        self.create_super_compact_window()
        self.root.withdraw()
        self.position_super_compact_window()
        self.compact_window.deiconify()
        self.apply_compact_opacity()
        self.compact_window.lift()
        self.update_super_compact_state()

    def position_super_compact_window(self) -> None:
        if self.compact_window is None or not self.compact_window.winfo_exists():
            return
        self.compact_window.update_idletasks()
        width = self.compact_window.winfo_reqwidth()
        height = self.compact_window.winfo_reqheight()
        if self.compact_last_position is None:
            screen_width = self.compact_window.winfo_screenwidth()
            screen_height = self.compact_window.winfo_screenheight()
            x = max(8, screen_width - width - 18)
            y = max(8, screen_height - height - 58)
        else:
            x, y = self.compact_last_position
        x, y = self.clamp_super_compact_position(x, y, width, height)
        self.compact_window.geometry(f"{width}x{height}+{x}+{y}")

    def clamp_super_compact_position(self, x: int, y: int, width: int, height: int) -> tuple[int, int]:
        if self.compact_window is None:
            return x, y
        max_x = max(0, self.compact_window.winfo_screenwidth() - width)
        max_y = max(0, self.compact_window.winfo_screenheight() - height)
        return max(0, min(max_x, x)), max(0, min(max_y, y))

    def start_super_compact_drag(self, event: tk.Event) -> None:
        if self.compact_window is None:
            return
        self.compact_drag_offset_x = event.x_root - self.compact_window.winfo_x()
        self.compact_drag_offset_y = event.y_root - self.compact_window.winfo_y()

    def drag_super_compact_window(self, event: tk.Event) -> None:
        if self.compact_window is None:
            return
        width = self.compact_window.winfo_width()
        height = self.compact_window.winfo_height()
        x = event.x_root - self.compact_drag_offset_x
        y = event.y_root - self.compact_drag_offset_y
        x, y = self.clamp_super_compact_position(x, y, width, height)
        self.compact_window.geometry(f"+{x}+{y}")

    def finish_super_compact_drag(self, _event: tk.Event | None = None) -> None:
        if self.compact_window is None:
            return
        self.compact_last_position = (self.compact_window.winfo_x(), self.compact_window.winfo_y())

    def exit_super_compact_mode(self) -> None:
        """Return to the full controller without reconnecting the camera."""
        self.stop_hold()
        if self.compact_window is not None and self.compact_window.winfo_exists():
            self.finish_super_compact_drag()
            self.compact_window.withdraw()
        if not self.is_closing:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.restore_overlay_style()

    def cycle_compact_speed(self) -> None:
        sequence = ("FINE", "NORMAL", "FAST")
        try:
            index = sequence.index(self.speed_mode)
        except ValueError:
            index = 1
        self.set_speed(sequence[(index + 1) % len(sequence)])
        self.update_super_compact_state()

    def update_super_compact_state(self) -> None:
        if self.compact_window is None or not self.compact_window.winfo_exists():
            return
        palette = current_palette()
        state_colours = {ConnectionState.DISCONNECTED: RED, ConnectionState.CONNECTING: YELLOW,
                         ConnectionState.CONNECTED_NO_PTZ: YELLOW, ConnectionState.READY: GREEN,
                         ConnectionState.ERROR: RED, }
        if self.compact_status_dot is not None:
            self.compact_status_dot.config(fg=state_colours[self.connection_state])

        ready = self.connection_state == ConnectionState.READY
        supported = self.supported_properties if ready else set()
        for button, capability in self.compact_control_buttons:
            enabled = ready and (capability == "preset" or capability in supported)
            button.config(state="normal" if enabled else "disabled",
                          bg=BUTTON_BG if enabled else palette["DISABLED_BG"],
                          fg=TEXT if enabled else palette["DISABLED_FG"], disabledforeground=palette["DISABLED_FG"], )
        if self.compact_speed_button is not None:
            labels = {"FINE": "F", "NORMAL": "N", "FAST": "X"}
            self.compact_speed_button.config(text=labels.get(self.speed_mode, "N"),
                                             state="normal" if ready else "disabled",
                                             disabledforeground=palette["DISABLED_FG"], )

    def create_header_button(self, text: str, command: Callable[[], None], foreground: str, ) -> tk.Button:
        return tk.Button(self.header_frame, text=text, command=command, width=2, bg=HEADER_BG, fg=foreground,
                         activebackground=BUTTON_HOVER, activeforeground=TEXT, relief="flat", borderwidth=0,
                         font=("Segoe UI Symbol", 9, "bold"), cursor="hand2", )

    def create_camera_row(self) -> None:
        frame = tk.Frame(self.content_frame, bg=BG)
        frame.pack(fill="x", pady=(0, 4))
        self.camera_combo = ttk.Combobox(frame, state="readonly", width=25, style="Compact.TCombobox",
                                         font=("Segoe UI", 8), )
        self.camera_combo.pack(side="left", fill="x", expand=True)
        self.camera_combo.bind("<<ComboboxSelected>>", lambda _event: self.camera_selection_changed(), )
        ToolTip(self.camera_combo, "Select the USB camera to control")
        self.connect_button = tk.Button(frame, text="●", command=self.connect_selected_camera, width=3,
                                        bg=BUTTON_ACTIVE, fg=accent_text(), activebackground=BUTTON_PRESSED,
                                        activeforeground=TEXT, relief="flat", borderwidth=0,
                                        font=("Segoe UI Symbol", 9, "bold"), cursor="hand2", )
        self.connect_button.pack(side="left", padx=(5, 0), ipady=3)
        ToolTip(self.connect_button, "Connect or reconnect selected camera")
        self.camera_info_button = tk.Button(frame, text="ℹ", command=self.toggle_camera_info, width=3, bg=BUTTON_BG,
                                            fg=MUTED, activebackground=BUTTON_ACTIVE, activeforeground=TEXT,
                                            relief="flat", borderwidth=0, font=("Segoe UI Symbol", 10, "bold"),
                                            cursor="hand2")
        self.camera_info_button.pack(side="left", padx=(4, 0), ipady=2)
        self.camera_info_button.bind("<Enter>", self.camera_info_enter, add="+")
        self.camera_info_button.bind("<Leave>", self.camera_info_leave, add="+")
        ToolTip(self.camera_info_button, "Hover for selected camera information")

    def create_ptz_section(self) -> None:
        frame = tk.Frame(self.content_frame, bg=SECTION_BG)
        frame.pack(fill="x", pady=(0, 4))
        pad = tk.Frame(frame, bg=SECTION_BG)
        pad.pack(pady=5)
        self.up_button = self.create_hold_button(pad, "▲", 0, 1, "tilt", 1, "Tilt camera up")
        self.left_button = self.create_hold_button(pad, "◀", 1, 0, "pan", -1, "Pan camera left")
        self.home_button = tk.Button(pad, text="⌂", command=self.go_home, width=4, height=1, bg=BUTTON_ACTIVE,
                                     fg="#FACC15", disabledforeground=DISABLED, activebackground=BUTTON_PRESSED,
                                     activeforeground="#FACC15", relief="flat", borderwidth=0,
                                     font=("Segoe UI Symbol", 12, "bold"), cursor="hand2", state="disabled", )
        self.home_button.grid(row=1, column=1, padx=3, pady=3, ipady=3)
        ToolTip(self.home_button, "Move Pan and Tilt to Home")
        self.right_button = self.create_hold_button(pad, "▶", 1, 2, "pan", 1, "Pan camera right")
        self.down_button = self.create_hold_button(pad, "▼", 2, 1, "tilt", -1, "Tilt camera down")

    def create_hold_button(self, parent: tk.Widget, text: str, row: int, column: int, property_name: str,
                           direction: int, tooltip_text: str, ) -> tk.Button:
        button = tk.Button(parent, text=text, width=4, height=1, bg=BUTTON_BG, fg=TEXT, disabledforeground=DISABLED,
                           activebackground=BUTTON_ACTIVE, activeforeground=TEXT, relief="flat", borderwidth=0,
                           font=("Segoe UI Symbol", 11, "bold"), cursor="hand2", state="disabled", )
        button.grid(row=row, column=column, padx=3, pady=3, ipady=3)
        owner = f"mouse:{property_name}:{direction}"
        self.bind_hold_button(button, property_name, direction, owner)
        ToolTip(button, tooltip_text + "\nPress and hold")
        return button

    def create_zoom_section(self) -> None:
        frame = tk.Frame(self.content_frame, bg=SECTION_BG)
        frame.pack(fill="x", pady=(0, 4))
        self.zoom_out_button = self.create_zoom_button(frame, "−", -1, "Zoom out")
        self.zoom_out_button.pack(side="left", fill="x", expand=True, padx=(7, 3), pady=6, ipady=3)
        label = tk.Label(frame, text="ZOOM", bg=SECTION_BG, fg=MUTED, width=7, font=("Segoe UI", 7, "bold"), )
        label.pack(side="left")
        ToolTip(label, "Camera Zoom control")
        self.zoom_in_button = self.create_zoom_button(frame, "+", 1, "Zoom in")
        self.zoom_in_button.pack(side="left", fill="x", expand=True, padx=(3, 7), pady=6, ipady=3)

    def create_zoom_button(self, parent: tk.Widget, text: str, direction: int, tooltip_text: str, ) -> tk.Button:
        button = tk.Button(parent, text=text, bg=BUTTON_BG, fg=TEXT, disabledforeground=DISABLED,
                           activebackground=BUTTON_ACTIVE, activeforeground=TEXT, relief="flat", borderwidth=0,
                           font=("Segoe UI", 12, "bold"), cursor="hand2", state="disabled", )
        self.bind_hold_button(button, "zoom", direction, f"mouse:zoom:{direction}", )
        ToolTip(button, tooltip_text + "\nPress and hold")
        return button

    def create_speed_section(self) -> None:
        frame = tk.Frame(self.content_frame, bg=BG)
        frame.pack(fill="x", pady=(0, 4))
        label = tk.Label(frame, text="SPEED", bg=BG, fg=MUTED, font=("Segoe UI", 7, "bold"), )
        label.pack(side="left", padx=(1, 5))
        ToolTip(label, "Movement amount per command")
        details = {"FINE": ("Fine", "Precise movement"), "NORMAL": ("Normal", "General movement"),
                   "FAST": ("Fast", "Large position changes"), }
        self.speed_buttons: dict[str, tk.Button] = {}
        for code in SPEED_MODES:
            display_text, tooltip_text = details[code]
            button = tk.Button(frame, text=display_text, command=lambda selected=code: self.set_speed(selected),
                               bg=BUTTON_BG, fg=MUTED, activebackground=BUTTON_ACTIVE, activeforeground=TEXT,
                               relief="flat", borderwidth=0, font=("Segoe UI", 7, "bold"), cursor="hand2", )
            button.pack(side="left", fill="x", expand=True, padx=1, ipady=3)
            self.speed_buttons[code] = button
            ToolTip(button, tooltip_text)
        self.update_speed_buttons()

    def create_preset_section(self) -> None:
        frame = tk.Frame(self.content_frame, bg=BG)
        frame.pack(fill="x", pady=(0, 4))
        label = tk.Label(frame, text="PRESETS", bg=BG, fg=MUTED, font=("Segoe UI", 7, "bold"), )
        label.pack(side="left", padx=(1, 4))
        ToolTip(label, "Saved Pan, Tilt and Zoom positions")
        self.preset_buttons: list[tk.Button] = []
        for number in PRESET_NUMBERS:
            button = tk.Button(frame, text=str(number), command=lambda selected=number: self.preset_clicked(selected),
                               width=3, bg=BUTTON_BG, fg=TEXT, disabledforeground=DISABLED,
                               activebackground=BUTTON_ACTIVE, activeforeground=TEXT, relief="flat", borderwidth=0,
                               font=("Segoe UI", 8, "bold"), cursor="hand2", state="disabled", )
            button.pack(side="left", fill="x", expand=True, padx=1, ipady=3)
            button.bind("<Button-3>", lambda _event, selected=number: self.save_preset(selected), )
            ToolTip(button, f"Preset {number}\nLeft-click: recall\nRight-click: save", )
            self.preset_buttons.append(button)
        self.save_button = tk.Button(frame, text="SAVE", command=self.toggle_save_mode, width=5, bg=BUTTON_BG, fg=TEXT,
                                     disabledforeground=DISABLED, activebackground=BUTTON_ACTIVE, activeforeground=TEXT,
                                     relief="flat", borderwidth=0, font=("Segoe UI", 7, "bold"), cursor="hand2",
                                     state="disabled", )
        self.save_button.pack(side="left", padx=(3, 0), ipady=3)
        ToolTip(self.save_button, "Click SAVE, then select preset 1 to 4")

    def create_hall_section(self) -> None:
        frame = tk.Frame(self.content_frame, bg=BG)
        frame.pack(fill="x", pady=(0, 4))
        tk.Label(frame, text="HALL", bg=BG, fg=MUTED, font=("Segoe UI", 7, "bold")).pack(side="left", padx=(1, 4))
        self.map_hall_button = tk.Button(frame, text="MAP", command=self.open_hall_wizard, bg=BUTTON_BG, fg=TEXT,
                                         disabledforeground=DISABLED, activebackground=BUTTON_ACTIVE,
                                         activeforeground=TEXT, relief="flat", borderwidth=0,
                                         font=("Segoe UI", 7, "bold"), cursor="hand2", state="disabled")
        self.map_hall_button.pack(side="left", fill="x", expand=True, padx=1, ipady=3)
        self.show_hall_button = tk.Button(frame, text="SHOW", command=self.show_hall_once, bg=BUTTON_ACTIVE,
                                          fg=accent_text(), disabledforeground=DISABLED,
                                          activebackground=BUTTON_PRESSED, activeforeground=TEXT, relief="flat",
                                          borderwidth=0, font=("Segoe UI", 7, "bold"), cursor="hand2", state="disabled")
        self.show_hall_button.pack(side="left", fill="x", expand=True, padx=1, ipady=3)
        self.pause_hall_button = tk.Button(frame, text="PAUSE", command=self.toggle_hall_pause, bg=YELLOW,
                                           fg=warning_text(), disabledforeground=DISABLED, activebackground="#FBBF24",
                                           activeforeground=BG, relief="flat", borderwidth=0,
                                           font=("Segoe UI", 7, "bold"), cursor="hand2", state="disabled")
        self.pause_hall_button.pack(side="left", fill="x", expand=True, padx=1, ipady=3)
        self.stop_hall_button = tk.Button(frame, text="STOP", command=self.stop_hall_playback, bg=RED, fg=accent_text(),
                                          disabledforeground=DISABLED, activebackground="#DC2626",
                                          activeforeground=TEXT, relief="flat", borderwidth=0,
                                          font=("Segoe UI", 7, "bold"), cursor="hand2", state="disabled")
        self.stop_hall_button.pack(side="left", fill="x", expand=True, padx=1, ipady=3)
        ToolTip(self.map_hall_button, "Open the hall mapping wizard")
        ToolTip(self.show_hall_button, "Run the saved Hall route")
        ToolTip(self.pause_hall_button, "Pause or resume Hall route playback")
        ToolTip(self.stop_hall_button, "Stop Hall route playback")

    def create_position_display(self) -> None:
        self.position_label = tk.Label(self.content_frame, text="PAN --    TILT --    ZOOM --", bg=HEADER_BG, fg=TEXT,
                                       anchor="center", padx=5, pady=6, font=("Consolas", 8, "bold"), )
        self.position_label.pack(fill="x", pady=(0, 4))
        ToolTip(self.position_label, "Last known camera PTZ values")

    def create_log_display(self) -> None:
        self.log_frame = tk.Frame(self.content_frame, bg=HEADER_BG, height=24)
        self.log_frame.pack(fill="x", pady=(0, 1))
        self.log_frame.pack_propagate(False)
        self.log_dot = tk.Label(self.log_frame, text="●", bg=HEADER_BG, fg=YELLOW, font=("Segoe UI", 8))
        self.log_dot.pack(side="left", padx=(6, 4))
        self.log_label = tk.Label(self.log_frame, text="Searching for cameras...", bg=HEADER_BG, fg=TEXT, anchor="w",
                                  justify="left", font=("Segoe UI", 8))
        self.log_label.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ToolTip(self.log_frame, "Latest camera status or PTZ activity")
        ToolTip(self.log_dot, "Latest camera status or PTZ activity")
        ToolTip(self.log_label, "Latest camera status or PTZ activity")

    def toggle_camera_info(self) -> None:
        if self.camera_info_window is not None and self.camera_info_window.winfo_exists():
            if self.camera_info_pinned:
                self.close_camera_info()
            else:
                self.camera_info_pinned = True
                self.cancel_job("camera_info_hide")
                self.update_camera_info_button_state()
            return
        self.camera_info_pinned = True
        self.open_camera_info()

    def update_camera_info_button_state(self) -> None:
        connected = self.connection_state in {ConnectionState.READY, ConnectionState.CONNECTED_NO_PTZ}
        visible = self.camera_info_window is not None and self.camera_info_window.winfo_exists()
        if not connected:
            self.camera_info_button.config(bg=BUTTON_BG, fg=DISABLED, activebackground=BUTTON_BG)
        elif visible and self.camera_info_pinned:
            self.camera_info_button.config(bg=GREEN, fg=accent_text(), activebackground=PRESET_SAVED)
        elif visible:
            self.camera_info_button.config(bg=BUTTON_ACTIVE, fg=accent_text(), activebackground=BUTTON_PRESSED)
        else:
            self.camera_info_button.config(bg=BUTTON_BG, fg=MUTED, activebackground=BUTTON_ACTIVE)

    def camera_info_enter(self, _event: tk.Event | None = None) -> None:
        self.cancel_job("camera_info_hide")
        if self.camera_info_window is None or not self.camera_info_window.winfo_exists():
            self.camera_info_pinned = False
            self.open_camera_info()

    def camera_info_leave(self, _event: tk.Event | None = None) -> None:
        if not self.camera_info_pinned:
            self.schedule_job("camera_info_hide", 300, self.close_camera_info_if_outside)

    def camera_info_popup_enter(self, _event: tk.Event | None = None) -> None:
        self.cancel_job("camera_info_hide")

    def camera_info_popup_leave(self, _event: tk.Event | None = None) -> None:
        if not self.camera_info_pinned:
            self.schedule_job("camera_info_hide", 300, self.close_camera_info_if_outside)

    def close_camera_info_if_outside(self) -> None:
        if self.camera_info_pinned:
            return
        try:
            x, y = self.root.winfo_pointerxy()
            widget = self.root.winfo_containing(x, y)
            if widget is self.camera_info_button:
                return
            window = self.camera_info_window
            if window is not None and window.winfo_exists():
                left = window.winfo_rootx()
                top = window.winfo_rooty()
                right = left + window.winfo_width()
                bottom = top + window.winfo_height()
                if left <= x <= right and top <= y <= bottom:
                    return
        except tk.TclError:
            pass
        self.close_camera_info()

    def open_camera_info(self) -> None:
        self.close_camera_info(False)
        window = tk.Toplevel(self.root)
        self.camera_info_window = window
        window.configure(bg=BG)
        window.resizable(False, False)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.bind("<Enter>", self.camera_info_popup_enter, add="+")
        window.bind("<Leave>", self.camera_info_popup_leave, add="+")

        wrapper = tk.Frame(window, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        wrapper.pack(fill="both", expand=True)
        header = tk.Frame(wrapper, bg=HEADER_BG)
        header.pack(fill="x")
        tk.Label(header, text="CAMERA INFO", bg=HEADER_BG, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(side="left",
                                                                                                       padx=10, pady=7)

        body = tk.Frame(wrapper, bg=BG)
        body.pack(fill="both", padx=10, pady=8)
        state_text = {ConnectionState.DISCONNECTED: "Disconnected", ConnectionState.CONNECTING: "Connecting",
                      ConnectionState.READY: "Ready", ConnectionState.CONNECTED_NO_PTZ: "Connected without PTZ",
                      ConnectionState.ERROR: "Error", }.get(self.connection_state, self.connection_state.name.title())
        mode_text = "Demo camera" if self.camera_service.demo_mode else "Real camera"
        rows = [("Name", self.camera_name or self.camera_combo.get() or "Not selected"), ("Status", state_text),
                ("Mode", mode_text if self.camera_name else "Not connected")]
        for name in PTZ_PROPERTIES:
            info = self.ranges.get(name)
            value = "Not supported" if info is None else f"{info.minimum:,} to {info.maximum:,} | Step {info.step:,} | Default {info.default:,}"
            rows.append((name.title(), value))
        rows.append(("Current",
                     f"P {self._display_ptz(self.position.pan)} | T {self._display_ptz(self.position.tilt)} | Z {self._display_ptz(self.position.zoom)}"))
        for row, (label, value) in enumerate(rows):
            tk.Label(body, text=label, bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 8, "bold"), width=8).grid(row=row,
                                                                                                                column=0,
                                                                                                                sticky="nw",
                                                                                                                pady=2)
            tk.Label(body, text=value, bg=BG, fg=TEXT, anchor="w", justify="left", font=("Segoe UI", 8),
                     wraplength=370).grid(row=row, column=1, sticky="nw", pady=2)

        window.update_idletasks()
        self.update_camera_info_button_state()
        self.position_camera_info()
        self.root.after_idle(self.position_camera_info)

    def position_camera_info(self) -> None:
        window = self.camera_info_window
        if window is None or not window.winfo_exists() or self.is_closing:
            return
        self.root.update_idletasks()
        window.update_idletasks()
        self.normalize_theme_contrast(window)
        self.schedule_theme_normalization(window)
        width = max(360, window.winfo_reqwidth(), window.winfo_width())
        height = max(window.winfo_reqheight(), window.winfo_height())
        gap = 7
        margin = 8
        work_left = 0
        work_top = 0
        work_right = self.root.winfo_screenwidth()
        work_bottom = self.root.winfo_screenheight()
        if sys.platform == "win32":
            try:
                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long),
                                ("bottom", ctypes.c_long)]

                rect = RECT()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    work_left, work_top = rect.left, rect.top
                    work_right, work_bottom = rect.right, rect.bottom
            except (AttributeError, OSError, TypeError):
                pass
        controller_x = self.root.winfo_x()
        controller_y = self.root.winfo_y()
        controller_width = self.root.winfo_width()
        controller_height = self.root.winfo_height()
        x = controller_x + controller_width - width
        y = controller_y - height - gap
        if y < work_top + margin:
            y = controller_y + controller_height + gap
        x = max(work_left + margin, min(x, work_right - width - margin))
        y = max(work_top + margin, min(y, work_bottom - height - margin))
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.lift()

    def close_camera_info(self, reset_pin: bool = True) -> None:
        self.cancel_job("camera_info_hide")
        window = self.camera_info_window
        self.camera_info_window = None
        if reset_pin:
            self.camera_info_pinned = False
        if window is not None:
            try:
                if window.winfo_exists():
                    window.destroy()
            except tk.TclError:
                pass
        if hasattr(self, "camera_info_button") and not self.is_closing:
            self.update_camera_info_button_state()

    def open_settings(self) -> None:
        self.keyboard_focus_lost()
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("PTZ Controller Settings")
        window.configure(bg=BG)
        window.geometry("760x640")
        window.minsize(620, 480)
        window.resizable(True, True)
        window.attributes("-topmost", True)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self.close_settings)
        self.settings_button.config(bg=HEADER_BG, fg=GREEN)
        self.settings_variables = {}
        self.settings_value_labels = {}
        self.settings_theme_buttons = {}
        self.settings_pages = {}
        self.settings_value_labels = {}
        self.settings_page_canvases = {}
        self.settings_page_windows = {}
        self.settings_nav_buttons = {}

        shell = tk.Frame(window, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg=HEADER_BG, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="CONTROLLER SETTINGS", bg=HEADER_BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(
            side="left", padx=18)
        tk.Label(header, text="Essential controls, guidance and support", bg=HEADER_BG, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="right", padx=18)

        nav = tk.Frame(shell, bg=SECTION_BG, height=40)
        nav.pack(fill="x")
        nav.pack_propagate(False)
        for key, label in (("general", "GENERAL"), ("manual", "MANUAL SPEED"), ("hall", "HALL MOTION"),
                           ("help", "HELP & SUPPORT")):
            button = tk.Button(nav, text=label, command=lambda page=key: self.show_settings_page(page), bg=SECTION_BG,
                               fg=MUTED, activebackground=BUTTON_HOVER, activeforeground=TEXT, relief="flat",
                               borderwidth=0, font=("Segoe UI", 8, "bold"), cursor="hand2", padx=18)
            button.pack(side="left", fill="y")
            self.settings_nav_buttons[key] = button

        content = tk.Frame(shell, bg=BG)
        content.pack(fill="both", expand=True, padx=14, pady=12)
        for key in ("general", "manual", "hall", "help"):
            holder = tk.Frame(content, bg=BG)
            holder.place(relx=0, rely=0, relwidth=1, relheight=1)
            canvas = tk.Canvas(holder, bg=BG, highlightthickness=0, borderwidth=0)
            scrollbar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview,
                                      style="Settings.Vertical.TScrollbar")
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            page = tk.Frame(canvas, bg=BG)
            page_window = canvas.create_window((0, 0), window=page, anchor="nw")
            page.bind("<Configure>", lambda _event, target=canvas: self.update_settings_scroll_region(target), add="+")
            canvas.bind("<Configure>", lambda event, target=canvas, item=page_window: target.itemconfigure(item,
                                                                                                           width=max(1,
                                                                                                                     event.width)),
                        add="+")
            canvas.bind("<Enter>", lambda _event, target=canvas: self.bind_settings_mousewheel(target), add="+")
            canvas.bind("<Leave>", lambda _event: self.unbind_settings_mousewheel(), add="+")
            self.settings_pages[key] = page
            self.settings_page_canvases[key] = canvas
            self.settings_page_windows[key] = holder

        self.build_general_settings_page(self.settings_pages["general"])
        self.build_manual_settings_page(self.settings_pages["manual"])
        self.build_hall_settings_page(self.settings_pages["hall"])
        self.build_help_settings_page(self.settings_pages["help"])

        footer = tk.Frame(shell, bg=HEADER_BG, height=58)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Button(footer, text="RESTORE DEFAULTS", command=self.restore_settings_defaults, bg=BUTTON_BG, fg=TEXT,
                  activebackground=PRESET_SAVE_MODE, activeforeground=TEXT, relief="flat", borderwidth=0,
                  font=("Segoe UI", 8, "bold"), cursor="hand2", width=18, pady=8).pack(side="left", padx=14, pady=11)
        tk.Button(footer, text="CANCEL", command=self.close_settings, bg=BUTTON_BG, fg=TEXT,
                  activebackground=BUTTON_HOVER, activeforeground=TEXT, relief="flat", borderwidth=0,
                  font=("Segoe UI", 8, "bold"), cursor="hand2", width=11, pady=8).pack(side="right", padx=(7, 14),
                                                                                       pady=11)
        tk.Button(footer, text="SAVE SETTINGS", command=self.save_settings_from_window, bg=GREEN, fg=accent_text(),
                  activebackground=PRESET_SAVED, activeforeground=accent_text(), relief="flat", borderwidth=0,
                  font=("Segoe UI", 8, "bold"), cursor="hand2", width=16, pady=8).pack(side="right", pady=11)

        self.show_settings_page("general")
        window.update_idletasks()
        self.normalize_theme_contrast(window)
        self.schedule_theme_normalization(window)
        self.position_settings_window()

    def update_settings_scroll_region(self, canvas: tk.Canvas) -> None:
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except tk.TclError:
            pass

    def bind_settings_mousewheel(self, canvas: tk.Canvas) -> None:
        self.active_settings_canvas = canvas
        self.root.bind_all("<MouseWheel>", self.settings_mousewheel, add="+")

    def unbind_settings_mousewheel(self) -> None:
        self.active_settings_canvas = None
        try:
            self.root.unbind_all("<MouseWheel>")
            self.root.bind_all("<KeyPress>", self.keyboard_pressed, add="+")
            self.root.bind_all("<KeyRelease>", self.keyboard_released, add="+")
        except tk.TclError:
            pass

    def settings_mousewheel(self, event: tk.Event) -> str | None:
        canvas = getattr(self, "active_settings_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return None
        direction = -1 if event.delta > 0 else 1
        canvas.yview_scroll(direction, "units")
        return "break"

    def show_settings_page(self, page_name: str) -> None:
        holder = self.settings_page_windows.get(page_name)
        canvas = self.settings_page_canvases.get(page_name)
        if holder is None or canvas is None:
            return
        holder.lift()
        canvas.yview_moveto(0.0)
        self.active_settings_canvas = canvas
        for name, button in self.settings_nav_buttons.items():
            selected = name == page_name
            button.config(bg=BUTTON_ACTIVE if selected else SECTION_BG, fg=accent_text() if selected else MUTED,
                          activeforeground=accent_text() if selected else TEXT)
        self.schedule_theme_normalization(self.settings_window)

    def settings_card(self, parent: tk.Widget, title: str, subtitle: str = "") -> tk.Frame:
        card = tk.Frame(parent, bg=SECTION_BG, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 10))
        heading = tk.Frame(card, bg=SECTION_BG)
        heading.pack(fill="x", padx=14, pady=(11, 7))
        tk.Label(heading, text=title, bg=SECTION_BG, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(side="left")
        if subtitle:
            tk.Label(heading, text=subtitle, bg=SECTION_BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="right")
        body = tk.Frame(card, bg=SECTION_BG)
        body.pack(fill="x", expand=True)
        return body

    def build_general_settings_page(self, page: tk.Frame) -> None:
        appearance = self.settings_card(page, "APPEARANCE", "Theme and transparency")
        theme_row = tk.Frame(appearance, bg=SECTION_BG)
        theme_row.pack(fill="x", padx=14, pady=(2, 10))
        tk.Label(theme_row, text="Theme", bg=SECTION_BG, fg=TEXT, font=("Segoe UI", 9), width=18, anchor="w").pack(
            side="left")
        theme_variable = tk.StringVar(value=str(self.user_settings["general"].get("theme", "DARK")))
        self.settings_variables["general.theme"] = theme_variable
        self.settings_theme_buttons = {}
        for theme_name in ("DARK", "LIGHT"):
            button = tk.Button(theme_row, text=theme_name.title(),
                               command=lambda selected=theme_name: self.select_settings_theme(selected), bg=BUTTON_BG,
                               fg=MUTED, activebackground=BUTTON_ACTIVE, activeforeground=TEXT, relief="flat",
                               borderwidth=0, font=("Segoe UI", 8, "bold"), cursor="hand2", width=10, pady=6)
            button.pack(side="left", padx=(0, 5))
            self.settings_theme_buttons[theme_name] = button
        self.update_settings_theme_buttons()
        self.add_modern_scale(appearance, "Default opacity", "general.opacity", 20, 100,
                              float(self.user_settings["general"]["opacity"]) * 100, "%")
        self.add_modern_scale(appearance, "Hover boost", "general.hover_boost", 0, 50,
                              float(self.user_settings["general"]["hover_boost"]) * 100, "%")
        fallback = self.settings_card(page, "DEMO MODE")
        variable = tk.BooleanVar(value=bool(self.user_settings["general"]["demo_mode"]))
        self.settings_variables["general.demo_mode"] = variable
        row = tk.Frame(fallback, bg=SECTION_BG)
        row.pack(fill="x", padx=14, pady=(3, 13))
        tk.Label(row, text="Use simulated PTZ if real PTZ is unavailable", bg=SECTION_BG, fg=TEXT,
                 font=("Segoe UI", 9)).pack(side="left")
        self.demo_mode_toggle_button = tk.Button(row, command=self.toggle_demo_mode_setting, relief="flat",
                                                 borderwidth=0, font=("Segoe UI", 8, "bold"), cursor="hand2", width=12,
                                                 pady=6)
        self.demo_mode_toggle_button.pack(side="right")
        self.update_demo_mode_setting_button()
        behavior = self.settings_card(page, "HELP BEHAVIOR")
        tooltip_variable = tk.BooleanVar(value=bool(self.user_settings["general"].get("tooltips_enabled", False)))
        self.settings_variables["general.tooltips_enabled"] = tooltip_variable
        tooltip_row = tk.Frame(behavior, bg=SECTION_BG)
        tooltip_row.pack(fill="x", padx=14, pady=(3, 13))
        tk.Label(tooltip_row, text="Show guidance when hovering over controls", bg=SECTION_BG, fg=TEXT,
                 font=("Segoe UI", 9)).pack(side="left")
        self.tooltip_setting_button = tk.Button(tooltip_row, command=self.toggle_tooltip_setting, relief="flat",
                                                borderwidth=0, font=("Segoe UI", 8, "bold"), cursor="hand2", width=12,
                                                pady=6)
        self.tooltip_setting_button.pack(side="right")
        self.update_tooltip_setting_button()

    def select_settings_theme(self, theme_name: str) -> None:
        variable = self.settings_variables.get("general.theme")
        if variable is not None:
            variable.set(theme_name)
        self.update_settings_theme_buttons()

    def update_settings_theme_buttons(self) -> None:
        variable = self.settings_variables.get("general.theme")
        selected_name = str(variable.get()).upper() if variable is not None else "DARK"
        for name, button in getattr(self, "settings_theme_buttons", {}).items():
            selected = name == selected_name
            button.config(bg=BUTTON_ACTIVE if selected else BUTTON_BG, fg=accent_text() if selected else TEXT,
                          activeforeground=accent_text() if selected else TEXT)
        self.schedule_theme_normalization(self.settings_window)

    def toggle_demo_mode_setting(self) -> None:
        variable = self.settings_variables.get("general.demo_mode")
        if variable is None:
            return
        variable.set(not bool(variable.get()))
        self.update_demo_mode_setting_button()

    def update_demo_mode_setting_button(self) -> None:
        button = getattr(self, "demo_mode_toggle_button", None)
        variable = self.settings_variables.get("general.demo_mode")
        if button is None or variable is None:
            return
        enabled = bool(variable.get())
        palette = current_palette()
        button.config(text="ENABLED" if enabled else "DISABLED", bg=GREEN if enabled else BUTTON_BG,
                      fg=palette["ON_ACCENT"] if enabled else palette["TEXT"],
                      activebackground=PRESET_SAVED if enabled else BUTTON_HOVER,
                      activeforeground=palette["ON_ACCENT"] if enabled else palette["TEXT"])
        self.schedule_theme_normalization(button)

    def toggle_tooltip_setting(self) -> None:
        variable = self.settings_variables.get("general.tooltips_enabled")
        if variable is None:
            return
        variable.set(not bool(variable.get()))
        self.update_tooltip_setting_button()

    def update_tooltip_setting_button(self) -> None:
        button = getattr(self, "tooltip_setting_button", None)
        variable = self.settings_variables.get("general.tooltips_enabled")
        if button is None or variable is None:
            return
        enabled = bool(variable.get())
        palette = current_palette()
        button.config(text="ENABLED" if enabled else "DISABLED", bg=GREEN if enabled else BUTTON_BG,
                      fg=palette["ON_ACCENT"] if enabled else TEXT,
                      activebackground=PRESET_SAVED if enabled else BUTTON_HOVER,
                      activeforeground=palette["ON_ACCENT"] if enabled else TEXT)

    def build_help_settings_page(self, page: tk.Frame) -> None:
        identity = tk.Frame(page, bg=BUTTON_ACTIVE, highlightbackground=BUTTON_PRESSED, highlightthickness=1)
        identity.pack(fill="x", pady=(0, 10))
        tk.Label(identity, text="SHREE BAITHAK CHINCHAVALI", bg=BUTTON_ACTIVE, fg=accent_text(),
                 font=("Segoe UI", 13, "bold")).pack(pady=(12, 2))
        tk.Label(identity, text="PTZ Camera Controller | Help & Support", bg=BUTTON_ACTIVE, fg=accent_text(),
                 font=("Segoe UI", 8)).pack(pady=(0, 11))

        body = tk.Frame(page, bg=BG)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(5, 0))

        guide = self.settings_card(left, "QUICK START", "Basic operation")
        guide_text = ("1. Select the required camera and click the connection button.\n"
                      "2. Wait until Pan, Tilt and Zoom controls become active.\n"
                      "3. Choose Fine, Normal or Fast movement speed.\n"
                      "4. Click or hold movement controls, or use supported keyboard keys.\n"
                      "5. Use SAVE and preset 1 to 4 for frequently used camera positions.")
        tk.Label(guide, text=guide_text, bg=SECTION_BG, fg=TEXT, justify="left", anchor="nw", wraplength=270,
                 font=("Segoe UI", 8)).pack(fill="x", padx=12, pady=(2, 11))

        hall = self.settings_card(left, "HALL ROUTE", "Mapping and playback")
        hall_text = ("Open MAP and capture the HOME position first. Add remaining points in route order. "
                     "Set movement speed and an optional 1 to 5 second pause for each point. Test the route, "
                     "use Pause, Resume or Stop when required, then save the map.")
        tk.Label(hall, text=hall_text, bg=SECTION_BG, fg=TEXT, justify="left", anchor="nw", wraplength=270,
                 font=("Segoe UI", 8)).pack(fill="x", padx=12, pady=(2, 11))

        keyboard = self.settings_card(left, "KEYBOARD CONTROLS", "Main controller must have focus")
        keyboard_text = ("Arrow keys: Pan and Tilt\n"
                         "+, = or Numpad +: Zoom In\n"
                         "- or Numpad -: Zoom Out\n"
                         "H: Home | 1 to 4: Recall preset\n"
                         "Ctrl + 1 to 4: Save preset | Esc: Stop or cancel")
        tk.Label(keyboard, text=keyboard_text, bg=SECTION_BG, fg=TEXT, justify="left", anchor="nw", wraplength=270,
                 font=("Segoe UI", 8)).pack(fill="x", padx=12, pady=(2, 11))

        troubleshooting = self.settings_card(right, "TROUBLESHOOTING", "Common checks")
        troubleshooting_text = (
            "Camera not listed\nClose other camera applications, reconnect USB and click Refresh.\n\n"
            "Controls are disabled\nOpen Camera Info and confirm Pan, Tilt or Zoom support.\n\n"
            "Keyboard does not respond\nClick the main controller once. Shortcuts are blocked while editing settings.\n\n"
            "Hall route does not pause\nSelect a point, choose 1 to 5 seconds, save the map and restart the test.\n\n"
            "Camera stops responding\nPress Esc, stop Hall playback, reconnect the camera and refresh the list.")
        tk.Label(troubleshooting, text=troubleshooting_text, bg=SECTION_BG, fg=TEXT, justify="left", anchor="nw",
                 wraplength=270, font=("Segoe UI", 8)).pack(fill="x", padx=12, pady=(2, 11))

        credits = self.settings_card(right, "CREDITS & CONTACT")
        credits_text = ("Designed by\nPragati Shelar\nPhone: +91 90000 00001\nEmail: pragati.shelar@example.com\n\n"
                        "Developed and Implemented by\nKalpesh Kashivale\nPhone: +91 90000 00002\nEmail: kalpesh.kashivale@example.com")
        tk.Label(credits, text=credits_text, bg=SECTION_BG, fg=TEXT, justify="left", anchor="nw", wraplength=270,
                 font=("Segoe UI", 8)).pack(fill="x", padx=12, pady=(2, 11))

        actions = tk.Frame(right, bg=BG)
        actions.pack(fill="x", pady=(0, 6))
        tk.Button(actions, text="OPEN DATA FOLDER", command=self.open_data_folder, bg=BUTTON_BG, fg=TEXT,
                  activebackground=BUTTON_HOVER, activeforeground=TEXT, relief="flat", borderwidth=0,
                  font=("Segoe UI", 8, "bold"), cursor="hand2", width=18, pady=7).pack(side="left", fill="x",
                                                                                       expand=True)
        tk.Button(actions, text="COPY DIAGNOSTICS", command=self.copy_diagnostics, bg=BUTTON_ACTIVE, fg=accent_text(),
                  activebackground=BUTTON_PRESSED, activeforeground=accent_text(), relief="flat", borderwidth=0,
                  font=("Segoe UI", 8, "bold"), cursor="hand2", width=18, pady=7).pack(side="left", fill="x",
                                                                                       expand=True, padx=(8, 0))

    def open_data_folder(self) -> None:
        folder = settings_file_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(folder))
        except (AttributeError, OSError) as error:
            messagebox.showerror("Open folder failed", str(error), parent=self.settings_window)

    def diagnostic_text(self) -> str:
        supported = ", ".join(sorted(self.supported_properties)) or "None"
        ranges = []
        for name in sorted(self.ranges):
            item = self.ranges[name]
            ranges.append(f"{name}: {item.minimum} to {item.maximum}, step {item.step}")
        range_text = "; ".join(ranges) or "None"
        return "\n".join((f"Application: {APP_TITLE}", f"Connection: {self.connection_state.name}",
                          f"Camera: {self.camera_name or 'None'}",
                          f"Mode: {'Demo' if self.camera_service.demo_mode else 'Real'}", f"Supported PTZ: {supported}",
                          f"Ranges: {range_text}",
                          f"Position: pan={self.position.pan}, tilt={self.position.tilt}, zoom={self.position.zoom}",
                          f"Speed: {self.speed_mode}", f"Theme: {self.user_settings['general']['theme']}",
                          f"Settings schema: {self.user_settings.get('schema_version', 1)}",))

    def copy_diagnostics(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.diagnostic_text())
            self.root.update()
            self.write_log("Diagnostics copied", GREEN)
        except tk.TclError as error:
            messagebox.showerror("Copy failed", str(error), parent=self.settings_window)

    def build_manual_settings_page(self, page: tk.Frame) -> None:
        card = self.settings_card(page, "MANUAL MOVEMENT", "Steps sent per repeat")
        card.grid_columnconfigure((0, 1, 2), weight=1, uniform="manual")
        for column, profile in enumerate(("FINE", "NORMAL", "FAST")):
            tk.Label(card, text=profile, bg=SECTION_BG, fg=MUTED, font=("Segoe UI", 8, "bold")).grid(row=0,
                                                                                                     column=column,
                                                                                                     pady=(3, 7))
        for row, (label, suffix, minimum, maximum) in enumerate(
                (("Pan / Tilt", "pt", 1, 50), ("Zoom", "zoom", 1, 5000)), 1):
            for column, profile in enumerate(("fine", "normal", "fast")):
                holder = tk.Frame(card, bg=SECTION_BG)
                holder.grid(row=row, column=column, padx=10, pady=(2, 12), sticky="ew")
                tk.Label(holder, text=label, bg=SECTION_BG, fg=TEXT, font=("Segoe UI", 8)).pack(anchor="w")
                self.add_compact_spin(holder, f"manual.{profile}_{suffix}", minimum, maximum,
                                      self.user_settings["manual"][f"{profile}_{suffix}"])

    def build_hall_settings_page(self, page: tk.Frame) -> None:
        card = self.settings_card(page, "HALL MOTION", "Lower interval is faster")
        headers = ("PROFILE", "INTERVAL MS", "SMOOTHNESS")
        for column, text in enumerate(headers):
            tk.Label(card, text=text, bg=SECTION_BG, fg=MUTED, font=("Segoe UI", 7, "bold")).grid(row=0, column=column,
                                                                                                  padx=10, pady=(3, 7),
                                                                                                  sticky="ew")
            card.grid_columnconfigure(column, weight=2 if column == 0 else 1)
        profiles = (("Cinematic", "cinematic"), ("Slow", "slow"), ("Normal", "normal"), ("Fast", "fast"),
                    ("Return Home", "return"))
        for row, (label, profile) in enumerate(profiles, 1):
            tk.Label(card, text=label, bg=SECTION_BG, fg=TEXT, font=("Segoe UI", 8, "bold")).grid(row=row, column=0,
                                                                                                  padx=(14, 10), pady=7,
                                                                                                  sticky="w")
            for column, suffix, minimum, maximum in ((1, "interval", 20, 1000), (2, "max", 2, 300)):
                variable = tk.IntVar(value=int(self.user_settings["hall"][f"{profile}_{suffix}"]))
                self.settings_variables[f"hall.{profile}_{suffix}"] = variable
                tk.Spinbox(card, from_=minimum, to=maximum, textvariable=variable, width=12, justify="center",
                           bg=BUTTON_BG, fg=TEXT, buttonbackground=BUTTON_BG, insertbackground=TEXT, relief="flat",
                           font=("Segoe UI", 8)).grid(row=row, column=column, padx=10, pady=7, ipady=4)
        tk.Frame(card, bg=SECTION_BG, height=8).grid(row=6, column=0, columnspan=3)

    def add_modern_scale(self, parent: tk.Widget, label: str, key: str, minimum: int, maximum: int, value: float,
                         suffix: str) -> None:
        row = tk.Frame(parent, bg=SECTION_BG)
        row.pack(fill="x", padx=14, pady=(2, 10))
        row.grid_columnconfigure(1, weight=1)
        tk.Label(row, text=label, bg=SECTION_BG, fg=TEXT, font=("Segoe UI", 9), width=18, anchor="w").grid(row=0,
                                                                                                           column=0,
                                                                                                           sticky="w")
        variable = tk.DoubleVar(value=value)
        self.settings_variables[key] = variable
        value_label = tk.Label(row, text=f"{int(value)}{suffix}", bg=BUTTON_ACTIVE, fg=accent_text(),
                               font=("Segoe UI", 8, "bold"), width=7, pady=4)
        value_label.grid(row=0, column=2, padx=(10, 0))
        if not hasattr(self, "settings_value_labels"):
            self.settings_value_labels = {}
        self.settings_value_labels[key] = value_label
        tk.Scale(row, from_=minimum, to=maximum, resolution=1, orient="horizontal", variable=variable, showvalue=False,
                 bg=SECTION_BG, troughcolor=current_palette()["INPUT_BG"], activebackground=BUTTON_ACTIVE,
                 highlightthickness=0, borderwidth=0, length=280,
                 command=lambda current, target=value_label, unit=suffix: target.config(
                     text=f"{int(float(current))}{unit}")).grid(row=0, column=1, sticky="ew")

    def add_compact_spin(self, parent: tk.Widget, key: str, minimum: int, maximum: int, value: int) -> None:
        variable = tk.IntVar(value=int(value))
        self.settings_variables[key] = variable
        tk.Spinbox(parent, from_=minimum, to=maximum, textvariable=variable, justify="center", bg=BUTTON_BG, fg=TEXT,
                   buttonbackground=BUTTON_BG, insertbackground=TEXT, relief="flat", font=("Segoe UI", 9)).pack(
            fill="x", pady=(4, 0), ipady=4)

    def collect_settings_from_window(self) -> dict[str, Any]:
        settings = json.loads(json.dumps(self.user_settings))
        for path, variable in self.settings_variables.items():
            section, key = path.split(".", 1)
            value = variable.get()
            if path in {"general.opacity", "general.hover_boost"}:
                value = float(value) / 100.0
            settings[section][key] = value
        return validate_settings(settings)

    def save_settings_from_window(self) -> None:
        try:
            settings = self.collect_settings_from_window()
        except (ValueError, TypeError, tk.TclError) as error:
            messagebox.showerror("Invalid settings", str(error), parent=self.settings_window)
            return

        previous_settings = validate_settings(self.user_settings)
        theme_changed = previous_settings["general"]["theme"] != settings["general"]["theme"]
        opacity_changed = previous_settings["general"]["opacity"] != settings["general"]["opacity"]
        demo_changed = previous_settings["general"]["demo_mode"] != settings["general"]["demo_mode"]

        try:
            save_user_settings(settings)
        except OSError as error:
            messagebox.showerror("Settings save failed", str(error), parent=self.settings_window)
            return

        status_text = self.log_label.cget("text") if hasattr(self, "log_label") else "Ready"
        status_colour = self.log_dot.cget("fg") if hasattr(self, "log_dot") else MUTED
        hall_was_open = self.hall_wizard is not None and self.hall_wizard.winfo_exists()
        info_was_open = self.camera_info_window is not None and self.camera_info_window.winfo_exists()
        info_was_pinned = self.camera_info_pinned
        hall_points_snapshot = [
            PTZPosition(pan=point.pan, tilt=point.tilt, zoom=point.zoom, transition_speed=point.transition_speed,
                        pause_enabled=point.pause_enabled, pause_seconds=point.pause_seconds, ) for point in
            self.hall_points]

        self.user_settings = settings
        self.close_settings()
        apply_user_settings(settings)
        self.tooltips_enabled = bool(settings["general"].get("tooltips_enabled", False))
        ToolTip.set_enabled(self.tooltips_enabled)

        if theme_changed:
            self.rebuild_interface_for_theme()
            if hall_was_open:
                self.open_hall_wizard()
                self.hall_points = hall_points_snapshot
                self.refresh_hall_point_list(0 if self.hall_points else None)
            if info_was_open:
                self.camera_info_pinned = info_was_pinned
                self.open_camera_info()
        elif opacity_changed:
            self.set_base_opacity(float(settings["general"]["opacity"]), persist=False)

        self.write_log(str(status_text), str(status_colour))
        if demo_changed:
            self.write_log("Demo preference saved | Reconnect to apply", YELLOW)

    def restore_settings_defaults(self) -> None:
        if not messagebox.askyesno("Restore defaults",
                                   "Load all default values into this window? Changes are applied only after Save Settings.",
                                   parent=self.settings_window):
            return
        defaults = validate_settings(DEFAULT_USER_SETTINGS)
        missing_paths: list[str] = []
        for path, variable in self.settings_variables.items():
            section, key = path.split(".", 1)
            if section not in defaults or key not in defaults[section]:
                missing_paths.append(path)
                continue
            value = defaults[section][key]
            if path in {"general.opacity", "general.hover_boost"}:
                value = float(value) * 100.0
            variable.set(value)
        self.update_settings_theme_buttons()
        self.update_demo_mode_setting_button()
        self.update_tooltip_setting_button()
        self.refresh_settings_value_labels()
        if missing_paths:
            messagebox.showwarning("Defaults partially restored",
                                   "No default value exists for: " + ", ".join(missing_paths),
                                   parent=self.settings_window, )

    def refresh_settings_value_labels(self) -> None:
        for key, label in getattr(self, "settings_value_labels", {}).items():
            variable = self.settings_variables.get(key)
            if variable is None:
                continue
            suffix = "%" if key in {"general.opacity", "general.hover_boost"} else ""
            try:
                label.config(text=f"{int(float(variable.get()))}{suffix}")
            except (tk.TclError, TypeError, ValueError):
                pass

    def rebuild_interface_for_theme(self) -> None:
        selected_name = self.camera_combo.get() if hasattr(self, "camera_combo") else ""
        selected_index = self.camera_combo.current() if hasattr(self, "camera_combo") else -1
        opacity = float(self.user_settings["general"]["opacity"])
        connection_state = self.connection_state
        camera_name = self.camera_name
        position = PTZPosition(pan=self.position.pan, tilt=self.position.tilt, zoom=self.position.zoom,
                               transition_speed=self.position.transition_speed,
                               pause_enabled=self.position.pause_enabled, pause_seconds=self.position.pause_seconds, )
        ranges = dict(self.ranges)
        speed_mode = self.speed_mode
        save_mode = self.save_mode

        self.close_camera_info()
        self.close_hall_wizard()
        self.stop_hold()
        try:
            self.outer_frame.destroy()
        except (AttributeError, tk.TclError):
            pass

        self.connection_state = connection_state
        self.camera_name = camera_name
        self.position = position
        self.ranges = ranges
        self.speed_mode = speed_mode
        self.save_mode = save_mode

        self.root.configure(bg=BG)
        self.configure_styles()
        self.create_interface()
        self.camera_combo["values"] = self.camera_names
        if 0 <= selected_index < len(self.camera_names):
            self.camera_combo.current(selected_index)
        elif selected_name and selected_name in self.camera_names:
            self.camera_combo.current(self.camera_names.index(selected_name))
        elif selected_name:
            self.camera_combo.set(selected_name)

        self.render_state()
        self.update_position_display()
        self.update_speed_buttons()
        self.update_preset_colours()
        self.normalize_theme_contrast(self.root)
        self.schedule_theme_normalization(self.root)
        self.rebuild_super_compact_for_theme()

        self.set_base_opacity(opacity, persist=False)
        self.root.update_idletasks()

    def position_settings_window(self) -> None:
        window = self.settings_window
        if window is None or not window.winfo_exists():
            return
        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        gap = 8
        margin = 8
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = self.root.winfo_x() + self.root.winfo_width() - width
        y = self.root.winfo_y() - height - gap
        if y < margin:
            y = self.root.winfo_y()
            x = self.root.winfo_x() - width - gap
        x = max(margin, min(x, screen_width - width - margin))
        y = max(margin, min(y, screen_height - height - margin))
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.lift()

    def close_settings(self) -> None:
        window = self.settings_window
        self.settings_window = None
        self.settings_pages = {}
        self.settings_page_canvases = {}
        self.settings_page_windows = {}
        self.settings_nav_buttons = {}
        self.active_settings_canvas = None
        self.tooltip_setting_button = None
        if window is not None:
            try:
                if window.winfo_exists():
                    window.destroy()
            except tk.TclError:
                pass
        if hasattr(self, "settings_button") and not self.is_closing:
            self.settings_button.config(bg=HEADER_BG, fg=MUTED)
            self.restore_controller_focus()

    def submit_camera_operation(self, operation: str, action: Callable[[], Any],
                                callback: Callable[[WorkerResult], None], ) -> int:
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

        self.submit_camera_operation("list_cameras", self.camera_service.list_cameras, completed, )

    def find_preferred_camera(self) -> int:
        best_index = 0
        best_score = -1
        for index, camera_name in enumerate(self.camera_names):
            lower_name = camera_name.lower()
            score = sum(weight for word, weight in PREFERRED_CAMERA_SCORES.items() if word in lower_name)
            if score > best_score:
                best_index = index
                best_score = score
        return best_index

    def camera_selection_changed(self) -> None:
        self.close_camera_info()
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
                if self.camera_service.demo_mode:
                    self.write_log(f"DEMO MODE | Simulated {supported}", YELLOW)
                else:
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
        self.submit_camera_operation("disconnect", self.camera_service.disconnect, lambda _result: None, )
        if show_log:
            self.write_log("Disconnected", YELLOW)

    def clear_camera_state(self) -> None:
        self.camera_name = None
        self.ranges = {}
        self.position = PTZPosition()
        self.move_pending = False

    def render_state(self) -> None:
        palette = current_palette()
        state_colours = {ConnectionState.DISCONNECTED: RED, ConnectionState.CONNECTING: YELLOW,
                         ConnectionState.CONNECTED_NO_PTZ: YELLOW, ConnectionState.READY: GREEN,
                         ConnectionState.ERROR: RED, }
        self.status_dot.config(fg=state_colours[self.connection_state])

        if self.connection_state == ConnectionState.READY:
            connect_background = GREEN
            connect_foreground = palette["ON_ACCENT"]
            connect_active = PRESET_SAVED
        elif self.connection_state in {ConnectionState.CONNECTING, ConnectionState.CONNECTED_NO_PTZ}:
            connect_background = YELLOW
            connect_foreground = palette["ON_WARNING"]
            connect_active = PRESET_SAVE_MODE
        elif self.connection_state == ConnectionState.ERROR:
            connect_background = RED
            connect_foreground = palette["ON_ACCENT"]
            connect_active = "#B91C1C"
        else:
            connect_background = BUTTON_ACTIVE
            connect_foreground = palette["ON_ACCENT"]
            connect_active = BUTTON_PRESSED
        self.connect_button.config(bg=connect_background, fg=connect_foreground, activebackground=connect_active,
                                   activeforeground=connect_foreground, )

        supported = self.supported_properties
        pan_enabled = "pan" in supported
        tilt_enabled = "tilt" in supported
        zoom_enabled = "zoom" in supported
        home_enabled = bool({"pan", "tilt"} & supported)

        for button, enabled in ((self.left_button, pan_enabled), (self.right_button, pan_enabled),
                                (self.up_button, tilt_enabled), (self.down_button, tilt_enabled),
                                (self.zoom_out_button, zoom_enabled), (self.zoom_in_button, zoom_enabled),):
            button.config(state="normal" if enabled else "disabled",
                          bg=BUTTON_BG if enabled else palette["DISABLED_BG"],
                          fg=TEXT if enabled else palette["DISABLED_FG"], disabledforeground=palette["DISABLED_FG"],
                          activebackground=BUTTON_ACTIVE if enabled else palette["DISABLED_BG"],
                          activeforeground=palette["ON_ACCENT"] if enabled else palette["DISABLED_FG"], )

        self.home_button.config(state="normal" if home_enabled else "disabled",
                                bg=BUTTON_ACTIVE if home_enabled else palette["DISABLED_BG"],
                                fg="#FACC15" if home_enabled else palette["DISABLED_FG"],
                                disabledforeground=palette["DISABLED_FG"],
                                activebackground=BUTTON_PRESSED if home_enabled else palette["DISABLED_BG"],
                                activeforeground="#FACC15" if home_enabled else palette["DISABLED_FG"], )

        preset_enabled = self.is_connected and bool(supported)
        preset_state = "normal" if preset_enabled else "disabled"
        for button in self.preset_buttons:
            button.config(state=preset_state, disabledforeground=palette["DISABLED_FG"], )
        self.save_button.config(state=preset_state, disabledforeground=palette["DISABLED_FG"], )

        hall_enabled = self.connection_state == ConnectionState.READY and not self.hall_running
        key = (self.camera_name or "").strip()
        has_map = len(self.hall_map_store.get(key)) >= 2
        show_enabled = hall_enabled and has_map

        self.map_hall_button.config(state="normal" if hall_enabled else "disabled",
                                    bg=BUTTON_BG if hall_enabled else palette["DISABLED_BG"],
                                    fg=TEXT if hall_enabled else palette["DISABLED_FG"],
                                    disabledforeground=palette["DISABLED_FG"],
                                    activebackground=BUTTON_ACTIVE if hall_enabled else palette["DISABLED_BG"],
                                    activeforeground=palette["ON_ACCENT"] if hall_enabled else palette["DISABLED_FG"], )
        self.show_hall_button.config(state="normal" if show_enabled else "disabled",
                                     bg=BUTTON_ACTIVE if show_enabled else palette["DISABLED_BG"],
                                     fg=palette["ON_ACCENT"] if show_enabled else palette["DISABLED_FG"],
                                     disabledforeground=palette["DISABLED_FG"],
                                     activebackground=BUTTON_PRESSED if show_enabled else palette["DISABLED_BG"],
                                     activeforeground=palette["ON_ACCENT"] if show_enabled else palette[
                                         "DISABLED_FG"], )

        if self.hall_running and self.hall_paused:
            self.pause_hall_button.config(state="normal", text="RESUME", bg=GREEN, fg=palette["ON_ACCENT"],
                                          activebackground=PRESET_SAVED, activeforeground=palette["ON_ACCENT"], )
        elif self.hall_running:
            self.pause_hall_button.config(state="normal", text="PAUSE", bg=YELLOW, fg=palette["ON_WARNING"],
                                          activebackground=PRESET_SAVE_MODE, activeforeground=palette["ON_WARNING"], )
        else:
            self.pause_hall_button.config(state="disabled", text="PAUSE", bg=palette["DISABLED_BG"],
                                          fg=palette["DISABLED_FG"], disabledforeground=palette["DISABLED_FG"],
                                          activebackground=palette["DISABLED_BG"],
                                          activeforeground=palette["DISABLED_FG"], )

        self.stop_hall_button.config(state="normal" if self.hall_running else "disabled",
                                     bg=RED if self.hall_running else palette["DISABLED_BG"],
                                     fg=palette["ON_ACCENT"] if self.hall_running else palette["DISABLED_FG"],
                                     disabledforeground=palette["DISABLED_FG"],
                                     activebackground="#B91C1C" if self.hall_running else palette["DISABLED_BG"],
                                     activeforeground=palette["ON_ACCENT"] if self.hall_running else palette[
                                         "DISABLED_FG"], )

        self.update_speed_buttons()
        self.update_preset_colours()
        self.update_camera_info_button_state()
        self.update_position_display()
        self.update_super_compact_state()

    def normalize_theme_contrast(self, widget: tk.Widget | None) -> None:
        if widget is None:
            return
        palette = current_palette()
        accent_backgrounds = {palette["BUTTON_ACTIVE"].lower(), palette["BUTTON_PRESSED"].lower(),
                              palette["GREEN"].lower(), palette["RED"].lower(), palette["PRESET_SAVED"].lower(),
                              palette["PRESET_SAVE_MODE"].lower(), }
        warning_backgrounds = {palette["YELLOW"].lower()}
        disabled_background = palette["DISABLED_BG"]
        disabled_foreground = palette["DISABLED_FG"]
        try:
            widget_class = widget.winfo_class()
            configuration = widget.configure()
            if widget_class in {"Button", "Label"} and "background" in configuration:
                background = str(widget.cget("background")).lower()
                if background in accent_backgrounds:
                    widget.configure(fg=palette["ON_ACCENT"], activeforeground=palette["ON_ACCENT"])
                elif background in warning_backgrounds:
                    widget.configure(fg=palette["ON_WARNING"], activeforeground=palette["ON_WARNING"])
                elif widget_class == "Button":
                    try:
                        state = str(widget.cget("state"))
                    except tk.TclError:
                        state = "normal"
                    if state == "disabled":
                        widget.configure(bg=disabled_background, fg=disabled_foreground,
                                         disabledforeground=disabled_foreground, activebackground=disabled_background,
                                         activeforeground=disabled_foreground)
                    elif background in {palette["BUTTON_BG"].lower(), palette["INPUT_BG"].lower()}:
                        widget.configure(fg=palette["TEXT"], activeforeground=palette["TEXT"])
            if widget_class == "Entry":
                widget.configure(bg=palette["INPUT_BG"], fg=palette["TEXT"], insertbackground=palette["TEXT"])
            if widget_class == "Spinbox":
                widget.configure(bg=palette["INPUT_BG"], fg=palette["TEXT"], insertbackground=palette["TEXT"],
                                 buttonbackground=palette["BUTTON_BG"])
        except (tk.TclError, TypeError):
            pass
        try:
            children = widget.winfo_children()
        except tk.TclError:
            children = []
        for child in children:
            self.normalize_theme_contrast(child)

    def schedule_theme_normalization(self, widget: tk.Widget | None) -> None:
        if widget is None:
            return
        try:
            widget.after_idle(lambda target=widget: self.normalize_theme_contrast(target))
        except tk.TclError:
            pass

    def style_control_button(self, button: tk.Button, enabled: bool, role: str = "neutral") -> None:
        palette = current_palette()
        if not enabled:
            button.config(state="disabled", bg=palette["DISABLED_BG"], fg=palette["DISABLED_FG"],
                          disabledforeground=palette["DISABLED_FG"], activebackground=palette["DISABLED_BG"])
            return
        roles = {"neutral": (BUTTON_BG, TEXT, BUTTON_HOVER),
                 "primary": (BUTTON_ACTIVE, palette["ON_ACCENT"], BUTTON_PRESSED),
                 "success": (GREEN, palette["ON_ACCENT"], PRESET_SAVED),
                 "danger": (RED, palette["ON_ACCENT"], "#B91C1C"),
                 "warning": (YELLOW, palette["ON_WARNING"], "#D97706"), }
        background, foreground, active = roles[role]
        button.config(state="normal", bg=background, fg=foreground, activebackground=active,
                      activeforeground=foreground, disabledforeground=palette["DISABLED_FG"])

        self.schedule_theme_normalization(self.root)

    def bind_hold_button(self, button: tk.Button, property_name: str, direction: int, owner: str, ) -> None:
        button.bind("<ButtonPress-1>", lambda _event: self.start_hold(property_name, direction, owner), )
        button.bind("<ButtonRelease-1>", lambda _event: self.stop_hold(owner))
        button.bind("<Leave>", lambda _event: self.stop_hold(owner))

    def start_hold(self, property_name: str, direction: int, owner: str, ) -> None:
        if self.hall_running:
            self.stop_hall_playback()
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
            ZOOM_SPEED_MODES[self.speed_mode] if action.property_name == "zoom" else SPEED_MODES[self.speed_mode])
        self.move_pending = True
        generation = self.operation_generation

        def operation() -> int:
            return self.camera_service.move(action.property_name, action.direction, multiplier, )

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
                self.schedule_job("repeat",
                                  INITIAL_HOLD_DELAY_MS if not self.jobs.get("repeat_started") else REPEAT_INTERVAL_MS,
                                  self.repeat_movement, )
                self.jobs["repeat_started"] = "active"

        self.submit_camera_operation("move", operation, completed)

    def repeat_movement(self) -> None:
        if self.active_hold is not None and not self.is_closing:
            self.move_active_hold()

    def stop_hold(self, owner: str | None = None) -> None:
        if (owner is not None and self.active_hold is not None and self.active_hold.owner != owner):
            return
        previous = self.active_hold
        self.active_hold = None
        if previous is None or previous.owner.startswith("key:"):
            self.pressed_keyboard_keys.clear()
        self.cancel_job("repeat")
        self.jobs.pop("repeat_started", None)
        if previous is not None:
            value = self.position.get(previous.property_name)
            if value is not None:
                self.write_log(f"{previous.property_name.title()} stopped at {value}", GREEN, )
            self.schedule_job("position_refresh", POSITION_REFRESH_DELAY_MS, self.refresh_position, )

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

        self.submit_camera_operation("read_position", self.camera_service.read_position, completed, )

    def handle_camera_failure(self, prefix: str, error: Exception) -> None:
        self.stop_hold()
        self.invalidate_operations()
        self.clear_camera_state()
        self.cancel_save_mode(render=False)
        self.connection_state = ConnectionState.ERROR
        self.render_state()
        self.write_log(f"{prefix}: {error}", RED)
        self.submit_camera_operation("disconnect_after_failure", self.camera_service.disconnect, lambda _result: None, )

    @staticmethod
    def get_active_message(property_name: str, direction: int) -> str:
        messages = {("pan", -1): "Panning left...", ("pan", 1): "Panning right...", ("tilt", 1): "Tilting up...",
                    ("tilt", -1): "Tilting down...", ("zoom", 1): "Zooming in...", ("zoom", -1): "Zooming out...", }
        return messages.get((property_name, direction), "Moving...")

    def set_speed(self, speed_code: str) -> None:
        if speed_code not in SPEED_MODES:
            return
        self.speed_mode = speed_code
        self.update_speed_buttons()
        self.update_super_compact_state()
        self.write_log(f"{speed_code.title()} | PT {SPEED_MODES[speed_code]}x | "
                       f"Zoom {ZOOM_SPEED_MODES[speed_code]}x", TEXT, )

    def update_speed_buttons(self) -> None:
        palette = current_palette()
        available = self.connection_state == ConnectionState.READY and bool(self.supported_properties)
        for code, button in self.speed_buttons.items():
            selected = code == self.speed_mode
            if not available:
                button.config(state="disabled", bg=palette["DISABLED_BG"], fg=palette["DISABLED_FG"],
                              disabledforeground=palette["DISABLED_FG"], activebackground=palette["DISABLED_BG"],
                              activeforeground=palette["DISABLED_FG"], )
            else:
                button.config(state="normal", bg=BUTTON_ACTIVE if selected else BUTTON_BG,
                              fg=palette["ON_ACCENT"] if selected else TEXT, disabledforeground=palette["DISABLED_FG"],
                              activebackground=BUTTON_PRESSED if selected else BUTTON_HOVER,
                              activeforeground=palette["ON_ACCENT"] if selected else TEXT, )

    def update_position_display(self) -> None:
        def display(value: int | None) -> str:
            return "--" if value is None else str(value)

        self.position_label.config(text=(f"PAN {display(self.position.pan)}    "
                                         f"TILT {display(self.position.tilt)}    "
                                         f"ZOOM {display(self.position.zoom)}"))

    def go_home(self) -> None:
        if not self.is_connected:
            return
        self.stop_hold()
        commands: list[tuple[str, int]] = []
        for property_name in ("pan", "tilt"):
            information = self.ranges.get(property_name)
            if information is None:
                continue
            target = (0 if information.minimum <= 0 <= information.maximum else information.default)
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
                self.preset_store.save(camera_key.strip(), preset_number, self.position, )
            except Exception as error:
                logger.exception("Unable to save preset")
                self.write_log(f"Preset save failed: {error}", RED)
                return
            self.cancel_save_mode()
            self.update_position_display()
            self.write_log(f"Preset {preset_number} saved", GREEN)

        self.submit_camera_operation("read_position_for_preset", self.camera_service.read_position, completed, )

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
        for property_name, value in position.supported_values(self.supported_properties).items():
            commands.append((property_name, self.ranges[property_name].align(value)))
        self.run_command_sequence(commands, f"Preset {preset_number} recalled")

    def update_preset_colours(self) -> None:
        palette = current_palette()
        camera_key = (self.camera_name or "").strip()
        saved = self.preset_store.saved_numbers(camera_key)
        available = self.is_connected and bool(self.supported_properties)
        for number, button in enumerate(self.preset_buttons, start=1):
            if not available:
                button.config(bg=palette["DISABLED_BG"], fg=palette["DISABLED_FG"],
                              disabledforeground=palette["DISABLED_FG"], activebackground=palette["DISABLED_BG"],
                              activeforeground=palette["DISABLED_FG"], )
            elif self.save_mode:
                button.config(bg=PRESET_SAVE_MODE, fg=palette["ON_ACCENT"], activebackground=YELLOW,
                              activeforeground=palette["ON_WARNING"], )
            elif number in saved:
                button.config(bg=PRESET_SAVED, fg=palette["ON_ACCENT"], activebackground=GREEN,
                              activeforeground=palette["ON_ACCENT"], )
            else:
                button.config(bg=BUTTON_BG, fg=TEXT, activebackground=BUTTON_ACTIVE,
                              activeforeground=palette["ON_ACCENT"], )

        if not available:
            self.save_button.config(bg=palette["DISABLED_BG"], fg=palette["DISABLED_FG"],
                                    disabledforeground=palette["DISABLED_FG"], activebackground=palette["DISABLED_BG"],
                                    activeforeground=palette["DISABLED_FG"], )
        elif self.save_mode:
            self.save_button.config(text="PICK", bg=PRESET_SAVE_MODE, fg=palette["ON_ACCENT"], activebackground=YELLOW,
                                    activeforeground=palette["ON_WARNING"], )
        else:
            self.save_button.config(text="SAVE", bg=BUTTON_BG, fg=TEXT, activebackground=BUTTON_ACTIVE,
                                    activeforeground=palette["ON_ACCENT"], )

    def run_command_sequence(self, commands: list[tuple[str, int]], completion_message: str, ) -> None:
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
                self.schedule_job("position_refresh", POSITION_REFRESH_DELAY_MS, self.refresh_position, )
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
                self.schedule_job("sequence", PRESET_COMMAND_DELAY_MS, lambda: execute_next(index + 1), )

            self.submit_camera_operation("set_value", operation, completed)

        execute_next()

    def open_hall_wizard(self) -> None:
        self.keyboard_focus_lost()
        if not self.is_connected or not self.ranges:
            self.write_log("Connect a PTZ camera before mapping", YELLOW)
            return
        if self.hall_wizard is not None and self.hall_wizard.winfo_exists():
            self.hall_wizard.lift()
            return

        self.hall_points = self.hall_map_store.get((self.camera_name or "").strip())
        window = tk.Toplevel(self.root)
        self.hall_wizard = window
        window.title("Hall Mapping Wizard")
        window.configure(bg=BG)
        window.attributes("-topmost", True)
        window.geometry("940x650")
        window.minsize(820, 590)
        window.resizable(True, True)
        window.protocol("WM_DELETE_WINDOW", self.close_hall_wizard)
        window.transient(self.root)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(2, weight=1)

        header = tk.Frame(window, bg=HEADER_BG, height=42)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)
        tk.Label(header, text="HALL MAPPING WIZARD", bg=HEADER_BG, fg=TEXT, font=("Segoe UI", 12, "bold")).grid(row=0,
                                                                                                                column=0,
                                                                                                                padx=(
                                                                                                                    16,
                                                                                                                    12),
                                                                                                                sticky="w")
        tk.Label(header, text=(self.camera_name or "Camera"), bg=HEADER_BG, fg=MUTED, font=("Segoe UI", 8)).grid(row=0,
                                                                                                                 column=1,
                                                                                                                 padx=(
                                                                                                                     8,
                                                                                                                     16),
                                                                                                                 sticky="e")

        toolbar = tk.Frame(window, bg=BG)
        toolbar.grid(row=1, column=0, sticky="ew", padx=16, pady=10)
        tk.Button(toolbar, text="START NEW MAP", command=self.start_new_hall_map, bg=PRESET_SAVE_MODE, fg=accent_text(),
                  activebackground=YELLOW, activeforeground=TEXT, relief="flat", borderwidth=0,
                  font=("Segoe UI", 8, "bold"), cursor="hand2", width=16, pady=7).pack(side="left")
        tk.Button(toolbar, text="+ CAPTURE POSITION", command=self.save_hall_point, bg=GREEN, fg=accent_text(),
                  activebackground=PRESET_SAVED, activeforeground=TEXT, relief="flat", borderwidth=0,
                  font=("Segoe UI", 8, "bold"), cursor="hand2", width=20, pady=7).pack(side="left", padx=(8, 0))
        speed_box = tk.Frame(toolbar, bg=BG)
        speed_box.pack(side="right")
        tk.Label(speed_box, text="DEFAULT SPEED", bg=BG, fg=MUTED, font=("Segoe UI", 7, "bold")).pack(side="left",
                                                                                                      padx=(0, 8))
        self.hall_speed_buttons = {}
        for speed_name in HALL_SPEED_PROFILES:
            button = tk.Button(speed_box, text=speed_name.title(),
                               command=lambda selected=speed_name: self.set_default_hall_speed(selected), bg=BUTTON_BG,
                               fg=MUTED, activebackground=BUTTON_ACTIVE, activeforeground=TEXT, relief="flat",
                               borderwidth=0, font=("Segoe UI", 7, "bold"), cursor="hand2", width=10, pady=6)
            button.pack(side="left", padx=1)
            self.hall_speed_buttons[speed_name] = button
        self.update_hall_speed_buttons()

        table_container = tk.Frame(window, bg=BORDER, highlightbackground=BORDER, highlightthickness=1)
        table_container.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)
        columns = ("number", "pan", "tilt", "zoom", "speed", "pause", "status")
        tree = ttk.Treeview(table_container, columns=columns, show="headings", selectmode="browse",
                            style="Hall.Treeview")
        self.hall_point_list = tree
        headings = {"number": "#", "pan": "PAN", "tilt": "TILT", "zoom": "ZOOM", "speed": "SEGMENT SPEED",
                    "pause": "PAUSE", "status": "ROLE / STATUS"}
        widths = {"number": 42, "pan": 90, "tilt": 90, "zoom": 95, "speed": 130, "pause": 90, "status": 205}
        for column in columns:
            anchor = "w" if column == "status" else "center"
            tree.heading(column, text=headings[column], anchor=anchor)
            tree.column(column, width=widths[column], minwidth=40, stretch=column == "status", anchor=anchor)
        y_scroll = ttk.Scrollbar(table_container, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=y_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        tree.tag_configure("odd", background=SECTION_BG)
        tree.tag_configure("even", background=THEMES[self.user_settings["general"]["theme"]]["ROW_ALT"])
        tree.tag_configure("home", foreground="#FACC15")
        tree.bind("<<TreeviewSelect>>", self.hall_point_selected)
        tree.bind("<Double-1>", lambda _event: self.go_to_hall_point())
        tree.bind("<Delete>", lambda _event: self.delete_hall_point())

        editor = tk.Frame(window, bg=SECTION_BG)
        editor.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 8))
        editor.grid_columnconfigure(1, weight=1)
        tk.Label(editor, text="SELECTED POINT", bg=SECTION_BG, fg=TEXT, font=("Segoe UI", 8, "bold")).grid(row=0,
                                                                                                           column=0,
                                                                                                           padx=(12,
                                                                                                                 18),
                                                                                                           pady=11,
                                                                                                           sticky="w")
        controls = tk.Frame(editor, bg=SECTION_BG)
        controls.grid(row=0, column=1, sticky="ew", pady=7)
        tk.Label(controls, text="SPEED", bg=SECTION_BG, fg=MUTED, font=("Segoe UI", 7, "bold")).pack(side="left",
                                                                                                     padx=(0, 6))
        self.point_speed_buttons = {}
        speed_widths = {"DEFAULT": 9, "CINEMATIC": 11, "SLOW": 7, "NORMAL": 9, "FAST": 7}
        for speed_name in ("DEFAULT", "CINEMATIC", "SLOW", "NORMAL", "FAST"):
            button = tk.Button(controls, text=speed_name.title(),
                               command=lambda selected=speed_name: self.set_selected_point_speed(selected),
                               bg=BUTTON_BG, fg=MUTED, activebackground=BUTTON_ACTIVE, activeforeground=TEXT,
                               relief="flat", borderwidth=0, font=("Segoe UI", 7, "bold"), cursor="hand2",
                               width=speed_widths[speed_name], pady=5)
            button.pack(side="left", padx=(0, 3))
            self.point_speed_buttons[speed_name] = button
        tk.Frame(controls, bg=BORDER, width=1, height=24).pack(side="left", padx=(8, 9))
        tk.Label(controls, text="PAUSE", bg=SECTION_BG, fg=MUTED, font=("Segoe UI", 7, "bold")).pack(side="left",
                                                                                                     padx=(0, 6))
        self.point_pause_buttons = {}
        for value, label in ((0, "Off"), (1, "1s"), (2, "2s"), (3, "3s"), (4, "4s"), (5, "5s")):
            button = tk.Button(controls, text=label,
                               command=lambda selected=value: self.set_selected_point_pause_value(selected),
                               bg=BUTTON_BG, fg=MUTED, activebackground=BUTTON_ACTIVE, activeforeground=TEXT,
                               relief="flat", borderwidth=0, font=("Segoe UI", 7, "bold"), cursor="hand2", width=4,
                               pady=5)
            button.pack(side="left", padx=(0, 3))
            self.point_pause_buttons[value] = button

        actions = tk.Frame(window, bg=BG)
        actions.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))
        action_specs = (("RECALL", self.go_to_hall_point, BUTTON_ACTIVE),
                        ("UPDATE POSITION", self.update_hall_point, BUTTON_BG),
                        ("INSERT AFTER", self.insert_hall_point, BUTTON_BG),
                        ("MOVE UP", lambda: self.move_hall_point(-1), BUTTON_BG),
                        ("MOVE DOWN", lambda: self.move_hall_point(1), BUTTON_BG),
                        ("DELETE POINT", self.delete_hall_point, RED))
        for column, (text, command, colour) in enumerate(action_specs):
            actions.grid_columnconfigure(column, weight=1, uniform="point_actions")
            tk.Button(actions, text=text, command=command, bg=colour, fg=TEXT,
                      activebackground=BUTTON_PRESSED if colour == BUTTON_ACTIVE else BUTTON_ACTIVE,
                      activeforeground=TEXT, relief="flat", borderwidth=0, font=("Segoe UI", 7, "bold"), cursor="hand2",
                      pady=7).grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0))

        footer = tk.Frame(window, bg=HEADER_BG)
        footer.grid(row=5, column=0, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        status_area = tk.Frame(footer, bg=HEADER_BG)
        status_area.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        self.hall_count_label = tk.Label(status_area, bg=HEADER_BG, fg=TEXT, anchor="w", font=("Segoe UI", 9, "bold"))
        self.hall_count_label.pack(anchor="w")
        self.hall_wizard_status = tk.Label(status_area, bg=HEADER_BG, fg=YELLOW, anchor="w", justify="left",
                                           font=("Segoe UI", 8))
        self.hall_wizard_status.pack(anchor="w", pady=(2, 0))
        footer_buttons = tk.Frame(footer, bg=HEADER_BG)
        footer_buttons.grid(row=0, column=1, sticky="e", padx=16, pady=10)
        tk.Button(footer_buttons, text="DELETE MAP", command=self.delete_entire_hall_map, bg=RED, fg=accent_text(),
                  activebackground="#DC2626", activeforeground=TEXT, relief="flat", borderwidth=0,
                  font=("Segoe UI", 8, "bold"), cursor="hand2", width=13, pady=8).pack(side="left", padx=(0, 6))
        self.hall_test_pause_button = tk.Button(footer_buttons, text="PAUSE TEST", command=self.toggle_hall_pause,
                                                bg=BUTTON_BG, fg=DISABLED, disabledforeground=DISABLED,
                                                activebackground=YELLOW, activeforeground=BG, relief="flat",
                                                borderwidth=0, font=("Segoe UI", 8, "bold"), cursor="hand2", width=13,
                                                pady=8, state="disabled")
        self.hall_test_pause_button.pack(side="left", padx=(0, 6))
        self.hall_test_stop_button = tk.Button(footer_buttons, text="STOP TEST", command=self.stop_hall_playback,
                                               bg=BUTTON_BG, fg=DISABLED, disabledforeground=DISABLED,
                                               activebackground="#DC2626", activeforeground=TEXT, relief="flat",
                                               borderwidth=0, font=("Segoe UI", 8, "bold"), cursor="hand2", width=12,
                                               pady=8, state="disabled")
        self.hall_test_stop_button.pack(side="left", padx=(0, 6))
        tk.Button(footer_buttons, text="TEST ROUTE", command=self.test_hall_map, bg=BUTTON_ACTIVE, fg=accent_text(),
                  activebackground=BUTTON_PRESSED, activeforeground=TEXT, relief="flat", borderwidth=0,
                  font=("Segoe UI", 8, "bold"), cursor="hand2", width=13, pady=8).pack(side="left", padx=(0, 6))
        self.hall_finish_button = tk.Button(footer_buttons, text="SAVE MAP", command=self.finish_hall_map, bg=GREEN,
                                            fg=accent_text(), disabledforeground=DISABLED,
                                            activebackground=PRESET_SAVED, activeforeground=TEXT, relief="flat",
                                            borderwidth=0, font=("Segoe UI", 8, "bold"), cursor="hand2", width=13,
                                            pady=8)
        self.hall_finish_button.pack(side="left")

        self.refresh_hall_point_list(0 if self.hall_points else None)
        self.update_hall_test_controls()
        self.normalize_theme_contrast(window)
        self.schedule_theme_normalization(window)
        self.position_hall_wizard()
        self.write_log("Hall mapping wizard opened", TEXT)

    def position_hall_wizard(self) -> None:
        """Place the wizard directly to the left of the controller and keep it visible."""
        window = self.hall_wizard
        if window is None or not window.winfo_exists():
            return

        self.root.update_idletasks()
        window.update_idletasks()

        gap = 8
        margin = 8
        work_left = 0
        work_top = 0
        work_right = self.root.winfo_screenwidth()
        work_bottom = self.root.winfo_screenheight()

        if sys.platform == "win32":
            try:
                import ctypes

                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long),
                                ("bottom", ctypes.c_long)]

                rect = RECT()
                spi_getworkarea = 0x0030
                if ctypes.windll.user32.SystemParametersInfoW(spi_getworkarea, 0, ctypes.byref(rect), 0):
                    work_left, work_top = rect.left, rect.top
                    work_right, work_bottom = rect.right, rect.bottom
            except (AttributeError, OSError, TypeError):
                logger.debug("Could not read Windows work area", exc_info=True)

        available_width = max(1, work_right - work_left - (2 * margin))
        available_height = max(1, work_bottom - work_top - (2 * margin))
        width = min(900, available_width)
        height = min(600, available_height)

        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()

        x = root_x - width - gap
        if x < work_left + margin:
            right_x = root_x + root_width + gap
            if right_x + width <= work_right - margin:
                x = right_x
            else:
                x = max(work_left + margin, work_right - width - margin)

        window.geometry(f"{width}x{height}+{work_left + margin}+{work_top + margin}")
        window.update_idletasks()

        wizard_title_height = max(0, window.winfo_rooty() - window.winfo_y())
        wizard_left_border = max(0, window.winfo_rootx() - window.winfo_x())
        root_client_bottom = self.root.winfo_rooty() + self.root.winfo_height()

        y = root_client_bottom - height - wizard_title_height
        x = root_x - width - gap - wizard_left_border

        if x < work_left + margin:
            right_x = root_x + root_width + gap
            if right_x + width <= work_right - margin:
                x = right_x
            else:
                x = max(work_left + margin, work_right - width - margin)

        max_x = work_right - width - margin - wizard_left_border
        max_y = work_bottom - height - margin - wizard_title_height
        x = max(work_left + margin, min(x, max_x))
        y = max(work_top + margin, min(y, max_y))

        window.geometry(f"{width}x{height}+{x}+{y}")
        window.update_idletasks()
        window.lift()

    def start_new_hall_map(self) -> None:
        if self.hall_points and not messagebox.askyesno("Start new map", "Clear the current working points?",
                                                        parent=self.hall_wizard):
            return
        self.stop_hall_playback(False)
        self.hall_points = []
        self.refresh_hall_point_list()
        self.write_log("New hall map started", YELLOW)

    def set_default_hall_speed(self, speed_name: str) -> None:
        if speed_name not in HALL_SPEED_PROFILES:
            return
        self.hall_speed_mode = speed_name
        self.update_hall_speed_buttons()
        self.write_log(f"Default hall speed: {speed_name.title()}", TEXT)

    def update_hall_speed_buttons(self) -> None:
        for name, button in self.hall_speed_buttons.items():
            selected = name == self.hall_speed_mode
            button.config(bg=BUTTON_ACTIVE if selected else BUTTON_BG, fg=accent_text() if selected else MUTED,
                          activeforeground=accent_text() if selected else TEXT)

    def hall_point_selected(self, _event: tk.Event | None = None) -> None:
        self.update_point_speed_buttons()
        self.update_point_pause_controls()

    def update_point_speed_buttons(self) -> None:
        index = self.selected_hall_point()
        current = self.hall_points[index].transition_speed if index is not None else None
        for name, button in getattr(self, "point_speed_buttons", {}).items():
            selected = name == current
            button.config(bg=BUTTON_ACTIVE if selected else BUTTON_BG, fg=accent_text() if selected else MUTED,
                          state="normal" if index is not None else "disabled")

    def update_point_pause_controls(self) -> None:
        index = self.selected_hall_point()
        current = 0
        if index is not None:
            point = self.hall_points[index]
            current = point.pause_seconds if point.pause_enabled else 0
        for value, button in getattr(self, "point_pause_buttons", {}).items():
            selected = index is not None and value == current
            if selected and value == 0:
                background, foreground = PRESET_SAVE_MODE, TEXT
            elif selected:
                background, foreground = GREEN, TEXT
            else:
                background, foreground = BUTTON_BG, MUTED
            button.config(state="normal" if index is not None else "disabled", bg=background, fg=foreground,
                          activebackground=GREEN if value else PRESET_SAVE_MODE, activeforeground=TEXT)

    def set_selected_point_pause_value(self, seconds: int) -> None:
        index = self.selected_hall_point()
        if index is None:
            self.write_log("Select a hall point first", YELLOW)
            return
        point = self.hall_points[index]
        point.pause_enabled = seconds > 0
        point.pause_seconds = max(1, min(5, seconds if seconds > 0 else 1))
        self.refresh_hall_point_list(index)
        self.write_log("Point pause off" if seconds == 0 else f"Point pause: {seconds} seconds",
                       TEXT if seconds == 0 else GREEN)

    def set_selected_point_speed(self, speed: str) -> None:
        index = self.selected_hall_point()
        if index is None:
            self.write_log("Select a hall point first", YELLOW)
            return
        speed = speed.upper()
        if speed not in {"DEFAULT", *HALL_SPEED_PROFILES}:
            return
        self.hall_points[index].transition_speed = speed
        self.refresh_hall_point_list(index)
        self.update_point_speed_buttons()
        self.write_log(f"Point {index + 1} speed set to {speed.title()}", GREEN)

    def delete_entire_hall_map(self) -> None:
        if not messagebox.askyesno("Delete hall map", "Delete the entire saved hall map? This cannot be undone.",
                                   parent=self.hall_wizard):
            return
        camera_key = (self.camera_name or "").strip()
        self.hall_points = []
        try:
            self.hall_map_store.delete(camera_key)
        except OSError as error:
            self.write_log(f"Map delete failed: {error}", RED)
            return
        self.refresh_hall_point_list()
        self.render_state()
        self.write_log("Entire hall map deleted", YELLOW)

    def close_hall_wizard(self) -> None:
        if self.hall_wizard is not None:
            try:
                self.hall_wizard.destroy()
            except tk.TclError:
                pass
        self.hall_wizard = None
        self.hall_point_list = None
        self.hall_count_label = None
        self.hall_wizard_status = None
        self.hall_finish_button = None
        self.hall_speed_buttons = {}
        self.point_speed_variable = None
        self.point_speed_buttons = {}
        self.restore_controller_focus()

    def refresh_hall_point_list(self, select: int | None = None) -> None:
        tree = self.hall_point_list
        if tree is None:
            return
        for item_id in tree.get_children():
            tree.delete(item_id)
        for index, point in enumerate(self.hall_points):
            speed = point.transition_speed.title()
            status = "HOME / return position" if index == 0 else "Hall coverage point"
            tags = ("even" if index % 2 == 0 else "odd", "home" if index == 0 else "")
            tree.insert("", "end", iid=str(index),
                        values=(index + 1, self._display_ptz(point.pan), self._display_ptz(point.tilt),
                                self._display_ptz(point.zoom), speed,
                                f"{point.pause_seconds} sec" if point.pause_enabled else "No", status),
                        tags=tuple(tag for tag in tags if tag))
        count = len(self.hall_points)
        if self.hall_count_label is not None:
            self.hall_count_label.config(text=f"{count} point{'s' if count != 1 else ''} captured")
        if self.hall_finish_button is not None:
            self.hall_finish_button.config(state="normal" if count >= 2 else "disabled")
        if self.hall_wizard_status is not None:
            if count == 0:
                message, colour = "Capture Point 1 as the HOME position.", YELLOW
            elif count == 1:
                message, colour = "HOME saved. Capture at least one hall coverage point.", YELLOW
            else:
                message, colour = "Route is valid and ready to save or test.", GREEN
            self.hall_wizard_status.config(text=message, fg=colour)
        if select is not None and self.hall_points:
            select = max(0, min(select, len(self.hall_points) - 1))
            item_id = str(select)
            tree.selection_set(item_id)
            tree.focus(item_id)
            tree.see(item_id)
        self.update_point_speed_buttons()
        self.update_point_pause_controls()

    @staticmethod
    def _display_ptz(value: int | None) -> str:
        return "--" if value is None else f"{value:,}"

    def selected_hall_point(self) -> int | None:
        if self.hall_point_list is None:
            return None
        selected = self.hall_point_list.selection()
        if not selected:
            return None
        try:
            return int(selected[0])
        except (TypeError, ValueError):
            return None

    def read_hall_position(self, callback: Callable[[PTZPosition], None]) -> None:
        self.stop_hold()
        generation = self.operation_generation

        def completed(result: WorkerResult) -> None:
            if generation != self.operation_generation:
                return
            if result.error is not None:
                self.write_log(f"Map point failed: {result.error}", RED)
                return
            self.position = result.value
            self.update_position_display()
            callback(PTZPosition(self.position.pan, self.position.tilt, self.position.zoom, "DEFAULT"))

        self.submit_camera_operation("read_hall_point", self.camera_service.read_position, completed)

    def save_hall_point(self) -> None:
        def add(point: PTZPosition) -> None:
            self.hall_points.append(point)
            self.refresh_hall_point_list(len(self.hall_points) - 1)
            self.write_log(f"Hall point {len(self.hall_points)} captured", GREEN)

        self.read_hall_position(add)

    def undo_hall_point(self) -> None:
        if self.hall_points:
            self.hall_points.pop()
            self.refresh_hall_point_list()
            self.write_log("Last hall point removed", YELLOW)

    def go_to_hall_point(self) -> None:
        index = self.selected_hall_point()
        if index is None:
            self.write_log("Select a hall point first", YELLOW)
            return
        point = self.hall_points[index]
        commands = [(name, value) for name in PTZ_PROPERTIES if
                    (value := point.get(name)) is not None and name in self.ranges]
        self.run_command_sequence(commands, f"Moved to hall point {index + 1}")

    def move_hall_point(self, offset: int) -> None:
        index = self.selected_hall_point()
        if index is None:
            self.write_log("Select a hall point first", YELLOW)
            return
        if index == 0:
            self.write_log("Point 1 HOME cannot be reordered", YELLOW)
            return
        target = index + offset
        if target <= 0 or target >= len(self.hall_points):
            return
        self.hall_points[index], self.hall_points[target] = self.hall_points[target], self.hall_points[index]
        self.refresh_hall_point_list(target)
        self.write_log(f"Hall point moved to position {target + 1}", TEXT)

    def update_hall_point(self) -> None:
        index = self.selected_hall_point()
        if index is None:
            self.write_log("Select a hall point first", YELLOW)
            return

        def update(point: PTZPosition) -> None:
            existing = self.hall_points[index]
            point.transition_speed = existing.transition_speed
            point.pause_enabled = existing.pause_enabled
            point.pause_seconds = existing.pause_seconds
            self.hall_points[index] = point
            self.refresh_hall_point_list(index)
            self.write_log(f"Hall point {index + 1} updated", GREEN)

        self.read_hall_position(update)

    def insert_hall_point(self) -> None:
        index = self.selected_hall_point()
        if index is None:
            self.write_log("Select an insertion point", YELLOW)
            return

        def insert(point: PTZPosition) -> None:
            self.hall_points.insert(index + 1, point)
            self.refresh_hall_point_list(index + 1)
            self.write_log(f"Hall point {index + 2} inserted", GREEN)

        self.read_hall_position(insert)

    def delete_hall_point(self) -> None:
        index = self.selected_hall_point()
        if index is None:
            self.write_log("Select a hall point first", YELLOW)
            return
        if index == 0:
            self.write_log("Point 1 HOME cannot be deleted; use START NEW MAP", YELLOW)
            return
        self.hall_points.pop(index)
        self.refresh_hall_point_list(min(index, len(self.hall_points) - 1))
        self.write_log("Hall point deleted", YELLOW)

    def finish_hall_map(self) -> None:
        if len(self.hall_points) < 2:
            self.write_log("Hall map needs at least 2 points", RED)
            return
        try:
            self.hall_map_store.save((self.camera_name or "").strip(), self.hall_points)
        except Exception as error:
            self.write_log(f"Hall map save failed: {error}", RED)
            return
        self.write_log(f"Hall map saved | {len(self.hall_points)} points", GREEN)
        self.close_hall_wizard()
        self.render_state()

    def test_hall_map(self) -> None:
        if len(self.hall_points) < 2:
            self.write_log("Hall map needs at least 2 points", RED)
            return
        self.start_hall_playback(list(self.hall_points), "Hall map test completed")

    def show_hall_once(self) -> None:
        points = self.hall_map_store.get((self.camera_name or "").strip())
        if len(points) < 2:
            self.write_log("Map the hall first", YELLOW)
            return
        self.start_hall_playback(points, "Hall view completed")

    def start_hall_playback(self, points: list[PTZPosition], completion: str) -> None:
        if not self.is_connected or self.hall_running:
            return
        if len(points) < 2:
            self.write_log("Hall map needs HOME plus at least one Hall point", RED)
            return
        home = PTZPosition(points[0].pan, points[0].tilt, points[0].zoom, "FAST")
        if any(home.get(name) is None for name in self.ranges):
            self.write_log("Point 1 HOME has incomplete PTZ values", RED)
            return
        self.stop_hold()
        self.invalidate_operations()
        generation = self.operation_generation
        self.hall_return_position = home

        route = [PTZPosition(pan=p.pan, tilt=p.tilt, zoom=p.zoom, transition_speed=p.transition_speed,
                             pause_enabled=p.pause_enabled, pause_seconds=max(1, min(5, int(p.pause_seconds))), ) for p
                 in points]
        route.append(PTZPosition(home.pan, home.tilt, home.zoom, "FAST", False, 1))
        self.hall_returning = False
        self.hall_paused = False
        self.hall_running = True
        self.render_state()
        self.update_hall_test_controls()
        self.write_log(f"Moving to HOME | 1/{len(points)}", TEXT)
        self.play_hall_segment(route, completion, generation, 0, self.position, route[0], 0, 1)

    def hall_segment_steps(self, start: PTZPosition, target: PTZPosition) -> int:
        ratio = 0.0
        for name in PTZ_PROPERTIES:
            info = self.ranges.get(name)
            a, b = start.get(name), target.get(name)
            if info is not None and a is not None and b is not None:
                ratio = max(ratio, abs(b - a) / max(1, info.maximum - info.minimum))
        _interval, minimum_steps, maximum_steps = (
            HALL_RETURN_PROFILE if self.hall_returning else HALL_SPEED_PROFILES[self.current_hall_segment_speed])
        return max(minimum_steps, min(maximum_steps, round(minimum_steps + ratio * maximum_steps)))

    def interpolate_hall_position(self, start: PTZPosition, target: PTZPosition, step: int, total: int) -> PTZPosition:
        progress = min(1.0, step / max(1, total))
        smooth = progress * progress * progress * (progress * (progress * 6.0 - 15.0) + 10.0)
        result = PTZPosition()
        for name in PTZ_PROPERTIES:
            info = self.ranges.get(name)
            a, b = start.get(name), target.get(name)
            if info is not None and a is not None and b is not None:
                result.set(name, info.align(round(a + (b - a) * smooth)))
        return result

    def finalize_hall_return(self, completion: str, generation: int) -> None:
        """Force all PTZ axes to the captured start and verify the accepted values."""
        expected = self.hall_return_position
        if expected is None:
            self.stop_hall_playback(False)
            self.write_log("Return failed: starting PTZ position was not captured", RED)
            return

        def exact_set_done(result: WorkerResult) -> None:
            if generation != self.operation_generation or not self.hall_running:
                return
            if result.error is not None:
                self.stop_hall_playback(False)
                self.write_log(f"Final return failed: {result.error}", RED)
                return
            self.position = result.value
            self.update_position_display()

            def verified(read_result: WorkerResult) -> None:
                if generation != self.operation_generation or not self.hall_running:
                    return
                if read_result.error is not None:
                    self.stop_hall_playback(False)
                    self.write_log(f"Return verification failed: {read_result.error}", RED)
                    return
                actual = read_result.value
                self.position = actual
                self.update_position_display()
                mismatches = []
                for name in self.ranges:
                    wanted = expected.get(name)
                    received = actual.get(name)
                    if wanted is not None and received != self.ranges[name].align(wanted):
                        mismatches.append(f"{name.upper()} {received}/{wanted}")
                self.hall_running = False
                self.hall_returning = False
                self.hall_return_position = None
                self.render_state()
                if mismatches:
                    self.write_log("Return mismatch: " + ", ".join(mismatches), RED)
                else:
                    self.write_log(completion + " | PTZ restored exactly", GREEN)

            self.schedule_job("hall_verify_return", POSITION_REFRESH_DELAY_MS,
                              lambda: self.submit_camera_operation("verify_hall_return",
                                                                   self.camera_service.read_position, verified))

        self.submit_camera_operation("force_exact_hall_return", lambda: self.camera_service.set_position(expected),
                                     exact_set_done)

    def advance_hall_segment(self, points: list[PTZPosition], completion: str, generation: int,
                             point_index: int) -> None:
        """Advance after reaching a waypoint, including a duplicate waypoint."""
        reached = points[point_index]
        if reached.pause_enabled and not self.hall_returning:
            seconds = max(1, min(5, reached.pause_seconds))
            self.write_log(f"Pausing at point {point_index + 1} for {seconds} seconds", YELLOW)
            self.schedule_job("hall_dwell", seconds * 1000,
                              lambda: self.continue_hall_route(points, completion, generation, point_index))
            return
        self.continue_hall_route(points, completion, generation, point_index)

    def continue_hall_route(self, points: list[PTZPosition], completion: str, generation: int,
                            point_index: int) -> None:
        if not self.hall_running or generation != self.operation_generation or self.is_closing:
            return
        if self.hall_paused:
            self.schedule_job("hall_dwell", 100,
                              lambda: self.continue_hall_route(points, completion, generation, point_index))
            return
        following = point_index + 1
        if following >= len(points):
            self.finalize_hall_return(completion, generation)
            return
        if following == len(points) - 1:
            self.hall_returning = True
            self.write_log("Returning directly to initial speaker view", TEXT)
        else:
            self.write_log(f"Showing hall | {following + 1}/{len(points) - 1}", TEXT)
        interval = (
            HALL_RETURN_PROFILE[0] if self.hall_returning else HALL_SPEED_PROFILES[self.current_hall_segment_speed][0])
        self.schedule_job("hall_playback", interval,
                          lambda: self.play_hall_segment(points, completion, generation, following, self.position,
                                                         points[following], 0, 1))

    def play_hall_segment(self, points: list[PTZPosition], completion: str, generation: int, point_index: int,
                          start: PTZPosition, target: PTZPosition, step: int, total: int) -> None:
        if not self.hall_running or generation != self.operation_generation or self.is_closing:
            return
        if self.hall_paused:
            self.schedule_job("hall_playback", 100,
                              lambda: self.play_hall_segment(points, completion, generation, point_index, start, target,
                                                             step, total))
            return
        if point_index < 0 or point_index >= len(points):
            self.stop_hall_playback(False)
            self.write_log("Hall route index is invalid", RED)
            return
        if step == 0:
            start = PTZPosition(self.position.pan, self.position.tilt, self.position.zoom)
            target = points[point_index]
            requested_speed = target.transition_speed
            self.current_hall_segment_speed = (
                self.hall_speed_mode if requested_speed == "DEFAULT" else requested_speed)
            total = self.hall_segment_steps(start, target)
        next_step = min(step + 1, total)
        command = self.interpolate_hall_position(start, target, next_step, total)
        duplicate = ((command.pan, command.tilt, command.zoom) == (self.position.pan, self.position.tilt,
                                                                   self.position.zoom))
        if duplicate:
            if next_step >= total:

                self.advance_hall_segment(points, completion, generation, point_index)
            else:
                self.schedule_job("hall_playback", 15,
                                  lambda: self.play_hall_segment(points, completion, generation, point_index, start,
                                                                 target, next_step, total))
            return

        def completed(result: WorkerResult) -> None:
            if not self.hall_running or generation != self.operation_generation:
                return
            if result.error is not None:
                self.stop_hall_playback(False)
                self.write_log(f"Hall movement failed: {result.error}", RED)
                return
            self.position = result.value
            self.update_position_display()
            if next_step >= total:
                self.advance_hall_segment(points, completion, generation, point_index)
            else:
                interval = (HALL_RETURN_PROFILE[0] if self.hall_returning else
                            HALL_SPEED_PROFILES[self.current_hall_segment_speed][0])
                self.schedule_job("hall_playback", interval,
                                  lambda: self.play_hall_segment(points, completion, generation, point_index, start,
                                                                 target, next_step, total))

        self.submit_camera_operation("hall_step", lambda: self.camera_service.set_position(command), completed)

    def stop_hall_playback(self, show_log: bool = True) -> None:
        was_running = self.hall_running
        self.hall_running = False
        self.hall_paused = False
        self.hall_returning = False
        self.cancel_job("hall_playback")
        self.cancel_job("hall_verify_return")
        self.cancel_job("hall_dwell")
        self.hall_return_position = None
        if was_running:
            self.operation_generation += 1
            self.render_state()
            self.update_hall_test_controls()
            if show_log:
                self.write_log("Hall movement stopped", YELLOW)

    def toggle_hall_pause(self) -> None:
        if not self.hall_running:
            return
        self.hall_paused = not self.hall_paused
        self.render_state()
        self.update_hall_test_controls()
        self.write_log("Hall movement resumed" if not self.hall_paused else "Hall movement paused",
                       GREEN if not self.hall_paused else YELLOW)

    def update_hall_test_controls(self) -> None:
        button = self.hall_test_pause_button
        if button is None or not button.winfo_exists():
            return
        stop_button = getattr(self, "hall_test_stop_button", None)
        if not self.hall_running:
            button.config(state="disabled", text="PAUSE TEST", bg=BUTTON_BG, fg=DISABLED)
            if stop_button is not None and stop_button.winfo_exists():
                stop_button.config(state="disabled", bg=BUTTON_BG, fg=DISABLED)
        elif self.hall_paused:
            button.config(state="normal", text="RESUME TEST", bg=GREEN, fg=accent_text())
            if stop_button is not None and stop_button.winfo_exists():
                stop_button.config(state="normal", bg=RED, fg=accent_text())
        else:
            button.config(state="normal", text="PAUSE TEST", bg=YELLOW, fg=warning_text())
            if stop_button is not None and stop_button.winfo_exists():
                stop_button.config(state="normal", bg=RED, fg=accent_text())

    def handle_escape(self, _event: tk.Event | None = None) -> str:
        if self.hall_running:
            self.stop_hall_playback()
        elif self.save_mode:
            self.cancel_save_mode()
            self.write_log("Preset save cancelled", YELLOW)
        elif self.active_hold is not None:
            self.stop_hold()
            self.write_log("Movement stopped", YELLOW)
        else:
            self.invalidate_operations()
            self.write_log("Operation cancelled", YELLOW)
        return "break"

    def keyboard_input_widget(self, widget: tk.Widget) -> bool:
        blocked_classes = {"TCombobox", "Entry", "Text", "Spinbox", "TSpinbox", "Scale", "TScale", "Treeview",
                           "Listbox"}
        current: tk.Widget | None = widget
        while current is not None:
            try:
                if current.winfo_class() in blocked_classes:
                    return True
                if current is self.settings_window or current is self.hall_wizard:
                    return True
                parent_name = current.winfo_parent()
                current = current._nametowidget(parent_name) if parent_name else None
            except (KeyError, tk.TclError):
                break
        return False

    def main_controller_has_focus(self) -> bool:
        try:
            focused = self.root.focus_get()
            return focused is not None and focused.winfo_toplevel() is self.root
        except tk.TclError:
            return False

    def activate_keyboard_control(self, event: tk.Event | None = None) -> None:
        if event is not None and self.keyboard_input_widget(event.widget):
            return
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def restore_controller_focus(self) -> None:
        if self.is_closing or self.is_minimized:
            return
        self.schedule_job("keyboard_focus", 30, self.activate_keyboard_control)

    def keyboard_focus_lost(self, _event: tk.Event | None = None) -> None:
        self.pressed_keyboard_keys.clear()
        if self.active_hold is not None and self.active_hold.owner.startswith("key:"):
            self.stop_hold()

    def movement_key_map(self) -> dict[str, tuple[str, int]]:
        return {"Left": ("pan", -1), "Right": ("pan", 1), "Up": ("tilt", 1), "Down": ("tilt", -1), "plus": ("zoom", 1),
                "equal": ("zoom", 1), "KP_Add": ("zoom", 1), "minus": ("zoom", -1), "KP_Subtract": ("zoom", -1), }

    def keyboard_pressed(self, event: tk.Event) -> str | None:
        if self.keyboard_input_widget(event.widget) or not self.main_controller_has_focus():
            return None
        movement = self.movement_key_map()
        if event.keysym in movement:
            if event.keysym in self.pressed_keyboard_keys:
                return "break"
            property_name, direction = movement[event.keysym]
            if property_name not in self.supported_properties:
                return "break"
            self.pressed_keyboard_keys.add(event.keysym)
            self.start_hold(property_name, direction, f"key:{event.keysym}")
            return "break"
        if event.keysym.lower() == "h":
            if {"pan", "tilt"} & self.supported_properties:
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

    def schedule_job(self, name: str, delay_ms: int, callback: Callable[[], None], ) -> None:
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
        self.cancel_job("hall_playback")
        self.cancel_job("hall_verify_return")

    def cancel_all_jobs(self) -> None:
        for name in list(self.jobs):
            self.cancel_job(name)

    def start_drag(self, event: tk.Event) -> None:
        self.drag_offset_x = event.x_root - self.root.winfo_x()
        self.drag_offset_y = event.y_root - self.root.winfo_y()

    def drag_window(self, event: tk.Event) -> None:
        self.root.geometry(f"+{event.x_root - self.drag_offset_x}"
                           f"+{event.y_root - self.drag_offset_y}")

    def place_bottom_right(self) -> None:
        self.root.update_idletasks()
        x_position = max(0, self.root.winfo_screenwidth() - self.root.winfo_reqwidth() - RIGHT_MARGIN, )
        y_position = max(0, self.root.winfo_screenheight() - self.root.winfo_reqheight() - BOTTOM_MARGIN, )
        self.root.geometry(f"+{x_position}+{y_position}")

    def toggle_tooltips(self) -> None:
        self.tooltips_enabled = not self.tooltips_enabled
        self.user_settings["general"]["tooltips_enabled"] = self.tooltips_enabled
        ToolTip.set_enabled(self.tooltips_enabled)

    def _effective_opacity(self, pointer_inside: bool) -> float:
        """Calculate hover alpha without changing the saved base opacity."""
        boost = (float(self.user_settings["general"].get("hover_boost", 0.0)) if pointer_inside else 0.0)
        return max(0.2, min(1.0, self.base_opacity + boost))

    def apply_root_opacity(self) -> None:
        if not self.is_closing and self.root.winfo_exists():
            self.root.attributes("-alpha", self._effective_opacity(self.pointer_inside_root))

    def apply_compact_opacity(self) -> None:
        window = self.compact_window
        if (not self.is_closing and window is not None and window.winfo_exists()):
            window.attributes("-alpha", self._effective_opacity(self.pointer_inside_compact))

    def apply_all_opacity(self) -> None:
        """Apply one opacity source of truth to full and compact windows."""
        self.apply_root_opacity()
        self.apply_compact_opacity()

    def set_base_opacity(self, opacity: float, persist: bool = False) -> None:
        """Set the exact base opacity and optionally save it immediately."""
        self.base_opacity = max(0.2, min(1.0, float(opacity)))
        self.opacity_index = min(range(len(OPACITY_VALUES)),
                                 key=lambda index: abs(OPACITY_VALUES[index] - self.base_opacity), )
        self.user_settings["general"]["opacity"] = self.base_opacity
        if persist:
            try:
                save_user_settings(self.user_settings)
            except OSError as error:
                logger.warning("Could not persist opacity: %s", error)
        self.apply_all_opacity()

    def controller_pointer_enter(self, _event: tk.Event | None = None) -> None:
        if self.is_closing:
            return
        self.pointer_inside_root = True
        self.apply_root_opacity()

    def controller_pointer_leave(self, event: tk.Event | None = None) -> None:
        if self.is_closing:
            return
        if event is not None:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            if widget is not None and str(widget).startswith(str(self.root)):
                return
        self.pointer_inside_root = False
        self.apply_root_opacity()

    def compact_pointer_enter(self, _event: tk.Event | None = None) -> None:
        if self.is_closing:
            return
        self.pointer_inside_compact = True
        self.apply_compact_opacity()

    def compact_pointer_leave(self, event: tk.Event | None = None) -> None:
        if self.is_closing:
            return
        window = self.compact_window
        if event is not None and window is not None and window.winfo_exists():
            widget = window.winfo_containing(event.x_root, event.y_root)
            if widget is not None and str(widget).startswith(str(window)):
                return
        self.pointer_inside_compact = False
        self.apply_compact_opacity()

    def change_opacity(self) -> None:
        nearest = min(range(len(OPACITY_VALUES)), key=lambda index: abs(OPACITY_VALUES[index] - self.base_opacity), )
        self.opacity_index = (nearest + 1) % len(OPACITY_VALUES)
        opacity = OPACITY_VALUES[self.opacity_index]
        self.set_base_opacity(opacity, persist=True)
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
        self.pointer_inside_root = False
        self.apply_root_opacity()
        self.root.lift()
        self.write_log("PTZ utility restored", TEXT)

    def write_log(self, message: str, colour: str) -> None:
        if self.is_closing:
            return
        full_message = str(message)
        short_message = full_message
        if len(short_message) > 42:
            short_message = short_message[:39] + "..."
        dot_colour = colour if colour in {GREEN, YELLOW, RED, MUTED, TEXT} else MUTED
        try:
            self.log_dot.config(fg=dot_colour)
            self.log_label.config(text=short_message, fg=TEXT)
        except tk.TclError:
            pass

    def close_application(self) -> None:
        if self.is_closing:
            return
        self.is_closing = True
        self.active_hold = None
        self.callbacks.clear()
        self.cancel_all_jobs()
        self.close_hall_wizard()
        self.close_camera_info()
        self.close_settings()
        if self.compact_window is not None:
            try:
                self.compact_window.destroy()
            except tk.TclError:
                pass
            self.compact_window = None
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", )


def main() -> None:
    configure_logging()
    enable_windows_dpi_awareness()
    root = tk.Tk()
    CompactPTZRemote(root)
    root.mainloop()


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import duvc_ctl as duvc
except ImportError:
    duvc = None

OUTPUT_FILE = Path(__file__).with_name("camera_properties.json")


def normalize_name(value: Any) -> str:
    return str(value).strip().lower().rsplit(".", 1)[-1]


def serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize(item) for item in value]

    result: dict[str, Any] = {}
    for attribute in (
            "min",
            "minimum",
            "max",
            "maximum",
            "step",
            "default",
            "default_val",
            "default_mode",
            "mode",
            "value",
    ):
        try:
            if hasattr(value, attribute):
                result[attribute] = serialize(getattr(value, attribute))
        except Exception as error:
            result[attribute] = f"{type(error).__name__}: {error}"

    return result if result else str(value)


def normalize_supported_properties(raw_supported: Any) -> dict[str, list[str]]:
    if not isinstance(raw_supported, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for category, properties in raw_supported.items():
        category_name = normalize_name(category)
        if isinstance(properties, (list, tuple, set)):
            normalized[category_name] = [normalize_name(item) for item in properties]
        else:
            normalized[category_name] = []
    return normalized


def read_property(controller: Any, property_name: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "current_value": None,
        "range": None,
        "value_error": None,
        "range_error": None,
    }

    try:
        result["current_value"] = serialize(getattr(controller, property_name))
    except Exception as error:
        result["value_error"] = f"{type(error).__name__}: {error}"

    try:
        result["range"] = serialize(controller.get_property_range(property_name))
    except Exception as error:
        result["range_error"] = f"{type(error).__name__}: {error}"

    return result


def camera_identifier(controller: Any) -> str | None:
    for attribute in ("device_path", "path", "device_id", "id"):
        try:
            value = getattr(controller, attribute, None)
        except Exception:
            value = None
        if value:
            return str(value)
    return None


def inspect_camera(device_index: int, camera_name: str) -> dict[str, Any]:
    controller = None
    report: dict[str, Any] = {
        "device_index": device_index,
        "camera_name": camera_name,
        "device_identifier": None,
        "supported_properties": {},
        "properties": {},
        "camera_error": None,
        "close_error": None,
    }

    try:
        controller = duvc.CameraController(device_index=device_index)
        report["device_identifier"] = camera_identifier(controller)
        supported = normalize_supported_properties(controller.get_supported_properties())
        report["supported_properties"] = supported

        for category, property_names in supported.items():
            report["properties"][category] = {
                property_name: read_property(controller, property_name)
                for property_name in property_names
            }
    except Exception as error:
        report["camera_error"] = f"{type(error).__name__}: {error}"
    finally:
        if controller is not None:
            try:
                controller.close()
            except Exception as error:
                report["close_error"] = f"{type(error).__name__}: {error}"

    return report


def print_report(reports: list[dict[str, Any]]) -> None:
    for report in reports:
        print("=" * 80)
        print(f"Camera index: {report['device_index']}")
        print(f"Camera name: {report['camera_name']}")
        print(f"Device identifier: {report['device_identifier'] or 'Unavailable'}")

        if report["camera_error"]:
            print(f"Camera error: {report['camera_error']}")
            continue

        properties = report["properties"]
        if not properties:
            print("No UVC properties were reported by this camera.")
            continue

        for category, category_properties in properties.items():
            print(f"\n[{category.upper()}]")
            if not category_properties:
                print("No properties reported in this category.")
                continue

            for property_name, details in category_properties.items():
                print(f"\nProperty: {property_name}")
                print(f"Current value: {details['current_value']}")
                print(f"Range: {json.dumps(details['range'], ensure_ascii=False)}")
                if details["value_error"]:
                    print(f"Value error: {details['value_error']}")
                if details["range_error"]:
                    print(f"Range error: {details['range_error']}")

        if report["close_error"]:
            print(f"Close error: {report['close_error']}")


def main() -> None:
    if duvc is None:
        print("duvc-ctl is not installed. Run: pip install duvc-ctl")
        return

    try:
        camera_names = [str(name) for name in duvc.list_cameras()]
    except Exception as error:
        print(f"Unable to enumerate cameras: {type(error).__name__}: {error}")
        return

    if not camera_names:
        print("No cameras detected.")
        return

    reports = [
        inspect_camera(device_index, camera_name)
        for device_index, camera_name in enumerate(camera_names)
    ]

    print_report(reports)

    try:
        OUTPUT_FILE.write_text(
            json.dumps(reports, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nJSON report saved to: {OUTPUT_FILE}")
    except OSError as error:
        print(f"Unable to save JSON report: {type(error).__name__}: {error}")


if __name__ == "__main__":
    main()

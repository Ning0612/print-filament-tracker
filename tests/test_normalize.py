import pytest

from src.normalize import normalize_date, normalize_task


def test_normalize_date_accepts_supported_formats() -> None:
    assert normalize_date("2026-07-11") == "2026-07-11"
    assert normalize_date("2026/07/11") == "2026-07-11"
    assert normalize_date("") is None
    assert normalize_date(None) is None


def test_normalize_date_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        normalize_date("2026-13-99")


def test_normalize_task_converts_cloud_fields() -> None:
    raw = {
        "title": "Calibration cube",
        "deviceName": "A1 mini",
        "deviceId": "printer-001",
        "startTime": "2026-07-11T10:00:00Z",
        "endTime": "2026-07-11T10:45:00Z",
        "costTime": "2700",
        "weight": "12.5",
        "amsDetailMapping": [
            {
                "position": "2",
                "filamentType": "PLA",
                "sourceColor": "AABBCCFF",
                "weight": "8.25",
            },
            {
                "position": "bad",
                "filamentType": "PETG",
                "sourceColor": "not-a-color",
                "weight": "bad",
            },
        ],
    }

    task = normalize_task(raw)

    assert task["print_name"] == "Calibration cube"
    assert task["duration_seconds"] == 2700
    assert task["total_used_weight_g"] == 12.5
    assert task["filaments"][0] == {
        "slot": 2,
        "material": "PLA",
        "color": None,
        "color_hex": "#AABBCC",
        "used_weight_g": 8.25,
    }
    assert task["filaments"][1]["slot"] is None
    assert task["filaments"][1]["color_hex"] is None
    assert task["filaments"][1]["used_weight_g"] is None

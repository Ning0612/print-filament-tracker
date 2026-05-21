import sqlite3
from pathlib import Path

from src.normalize import normalize_date as _normalize_date_shared
from src.db import (
    delete_printer_record,
    get_all_printers_full,
    get_connection,
    get_existing_device_ids,
    get_printer_by_id,
    get_printer_stats_all,
    insert_printer,
    update_printer,
    update_printer_image_url,
)


class PrinterNotFoundError(Exception):
    pass


class PrinterValidationError(Exception):
    pass


def _normalize_date(val: "str | None") -> "str | None":
    try:
        return _normalize_date_shared(val)
    except ValueError as exc:
        raise PrinterValidationError(str(exc)) from exc


def _validate_printer_data(data: dict) -> None:
    name = (data.get("name") or "").strip()
    if not name:
        raise PrinterValidationError("印表機名稱為必填。")
    _normalize_date(data.get("purchased_at"))


def _clean_printer_data(data: dict) -> dict:
    return {
        "name":         (data.get("name") or "").strip(),
        "model":        (data.get("model") or "").strip() or None,
        "device_id":    (data.get("device_id") or "").strip() or None,
        "purchased_at": _normalize_date(data.get("purchased_at")),
        "image_url":    data.get("image_url"),
        "note":         (data.get("note") or "").strip() or None,
    }


def _raise_integrity_error(exc: sqlite3.IntegrityError) -> None:
    msg = str(exc)
    if "printer.name" in msg or ("name" in msg and "unique" in msg.lower()):
        raise PrinterValidationError("此印表機名稱已存在。") from exc
    if "printer.device_id" in msg or ("device_id" in msg and "unique" in msg.lower()):
        raise PrinterValidationError("此 Device ID 已被另一台印表機使用。") from exc
    raise exc


def list_printers_with_stats(db_path: Path) -> list:
    with get_connection(db_path) as conn:
        rows = get_all_printers_full(conn)
        stats = get_printer_stats_all(conn)
    result = []
    for row in rows:
        d = dict(row)
        s = stats.get(d["id"], {"task_count": 0, "total_duration_seconds": 0, "total_weight_g": 0.0})
        d.update(s)
        result.append(d)
    return result


def read_printer(db_path: Path, printer_id: int) -> dict:
    with get_connection(db_path) as conn:
        row = get_printer_by_id(conn, printer_id)
    if row is None:
        raise PrinterNotFoundError(f"找不到印表機 id={printer_id}。")
    return dict(row)


def create_printer(db_path: Path, data: dict) -> int:
    _validate_printer_data(data)
    cleaned = _clean_printer_data(data)
    with get_connection(db_path) as conn:
        try:
            return insert_printer(conn, cleaned)
        except sqlite3.IntegrityError as exc:
            _raise_integrity_error(exc)


def update_printer_data(db_path: Path, printer_id: int, data: dict) -> None:
    _validate_printer_data(data)
    cleaned = _clean_printer_data(data)
    with get_connection(db_path) as conn:
        if get_printer_by_id(conn, printer_id) is None:
            raise PrinterNotFoundError(f"找不到印表機 id={printer_id}。")
        try:
            update_printer(conn, printer_id, cleaned)
        except sqlite3.IntegrityError as exc:
            _raise_integrity_error(exc)


def set_printer_image(db_path: Path, printer_id: int, image_url: "str | None") -> None:
    with get_connection(db_path) as conn:
        update_printer_image_url(conn, printer_id, image_url)


def delete_printer_data(db_path: Path, printer_id: int) -> None:
    with get_connection(db_path) as conn:
        if get_printer_by_id(conn, printer_id) is None:
            raise PrinterNotFoundError(f"找不到印表機 id={printer_id}。")
        delete_printer_record(conn, printer_id)


def get_device_id_suggestions(db_path: Path) -> list:
    with get_connection(db_path) as conn:
        return get_existing_device_ids(conn)

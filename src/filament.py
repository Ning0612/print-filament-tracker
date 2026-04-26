import csv
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import (
    DatabaseError,
    delete_spool,
    get_all_spools,
    get_connection,
    get_ignored_filaments,
    get_mapped_filament_by_id,
    get_mapped_filaments,
    get_ptf_by_id,
    get_ptf_material,
    get_spool_by_id,
    get_spool_last_used_map,
    get_spool_used_weight,
    get_tasks_grouped_by_spool,
    get_unmapped_filaments,
    ignore_filament,
    insert_spool,
    map_filament_to_spool,
    unignore_filament,
    unmap_filament,
    update_ptf_material,
    update_spool,
)


class SpoolNotFoundError(Exception):
    pass


class SpoolValidationError(Exception):
    pass


class SpoolImportError(Exception):
    pass


_SPOOL_FIELDS = [
    "uid", "material", "color_name", "color_hex", "initial_weight_g",
    "price", "purchased_at", "product_url", "note",
]

_CSV_FORMULA_CHARS = ("=", "+", "-", "@")

# 支援的日期輸入格式（統一正規化為 YYYY-MM-DD）
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")


def _normalize_date(val: str | None) -> str | None:
    """將常見日期字串正規化為 ISO 8601 YYYY-MM-DD，無效格式拋出 ValueError。"""
    if not val:
        return None
    val = str(val).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(
        f"日期格式不正確：'{val}'，請使用 YYYY-MM-DD（例如 2024-01-15）。"
    )


# --- Computed fields ---

def _compute_status(initial_g: float, remaining_g: float, used_g: float) -> str:
    if used_g == 0:
        return "sealed"
    if remaining_g <= 0:
        return "empty"
    if initial_g > 0 and remaining_g / initial_g < 0.1:
        return "low"
    return "active"


def enrich_spool(spool_row, used_weight: float) -> dict:
    d = dict(spool_row)
    initial = d["initial_weight_g"] or 0.0
    remaining = initial - used_weight
    d["used_weight_g"] = used_weight
    d["remaining_weight_g"] = remaining
    d["usage_ratio"] = (used_weight / initial) if initial > 0 else 0.0
    d["status"] = _compute_status(initial, remaining, used_weight)
    return d


def _validate_spool_data(data: dict) -> None:
    if not data.get("initial_weight_g"):
        raise SpoolValidationError("initial_weight_g 為必填欄位。")
    try:
        val = float(data["initial_weight_g"])
        if val <= 0:
            raise SpoolValidationError("initial_weight_g 必須大於 0。")
    except (ValueError, TypeError):
        raise SpoolValidationError("initial_weight_g 必須為數字。")

    purchased_at = data.get("purchased_at")
    if purchased_at is not None:
        try:
            _normalize_date(str(purchased_at).strip())
        except ValueError as exc:
            raise SpoolValidationError(str(exc)) from exc

    color_hex = data.get("color_hex")
    if color_hex is not None:
        if len(color_hex) != 7 or color_hex[0] != "#":
            raise SpoolValidationError("color_hex 格式不正確，請使用 #RRGGBB 格式（例如 #A6A9AA）。")
        try:
            int(color_hex[1:], 16)
        except ValueError:
            raise SpoolValidationError("color_hex 格式不正確，請使用 #RRGGBB 格式（例如 #A6A9AA）。")


# --- CRUD ---

def create_spool(db_path: Path, data: dict) -> int:
    _validate_spool_data(data)
    if not data.get("uid"):
        data = {**data, "uid": str(uuid.uuid4())}
    with get_connection(db_path) as conn:
        return insert_spool(conn, data)


def read_spool(db_path: Path, spool_id: int) -> dict:
    with get_connection(db_path) as conn:
        row = get_spool_by_id(conn, spool_id)
        if row is None:
            raise SpoolNotFoundError(f"Spool id={spool_id} 不存在。")
        used = get_spool_used_weight(conn, spool_id)
        return enrich_spool(row, used)


def update_spool_data(db_path: Path, spool_id: int, data: dict) -> None:
    _validate_spool_data(data)
    with get_connection(db_path) as conn:
        if get_spool_by_id(conn, spool_id) is None:
            raise SpoolNotFoundError(f"Spool id={spool_id} 不存在。")
        update_spool(conn, spool_id, data)


def delete_spool_data(db_path: Path, spool_id: int) -> None:
    with get_connection(db_path) as conn:
        if get_spool_by_id(conn, spool_id) is None:
            raise SpoolNotFoundError(f"Spool id={spool_id} 不存在。")
        delete_spool(conn, spool_id)


def list_spools(db_path: Path) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = get_all_spools(conn)
        used_map = _get_all_used_weights(conn)
        return [enrich_spool(row, used_map.get(row["id"], 0.0)) for row in rows]


def list_spools_with_tasks(db_path: Path) -> tuple[list[dict], dict]:
    with get_connection(db_path) as conn:
        rows = get_all_spools(conn)
        used_map = _get_all_used_weights(conn)
        spools = [enrich_spool(row, used_map.get(row["id"], 0.0)) for row in rows]
        tasks_by_spool = get_tasks_grouped_by_spool(conn)
    return spools, tasks_by_spool


def _get_all_used_weights(conn) -> dict[int, float]:
    rows = conn.execute(
        """
        SELECT filament_spool_id, COALESCE(SUM(used_weight_g), 0.0) AS total
        FROM print_task_filament
        WHERE filament_spool_id IS NOT NULL
        GROUP BY filament_spool_id
        """
    ).fetchall()
    return {r["filament_spool_id"]: r["total"] for r in rows}


# --- Unmapped & Mapping ---

def list_unmapped(db_path: Path) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = get_unmapped_filaments(conn)
        return [dict(r) for r in rows]


def list_spools_for_mapping(db_path: Path) -> list[dict]:
    """回傳非已耗盡的耗材，最近被 mapping 使用過的排前面，從未使用的排後面。"""
    with get_connection(db_path) as conn:
        rows = get_all_spools(conn)
        used_map = _get_all_used_weights(conn)
        last_used_map = get_spool_last_used_map(conn)

    spools = [enrich_spool(row, used_map.get(row["id"], 0.0)) for row in rows]
    spools = [s for s in spools if s["status"] != "empty"]

    recently_used = [s for s in spools if s["id"] in last_used_map]
    never_used = [s for s in spools if s["id"] not in last_used_map]
    recently_used.sort(key=lambda s: last_used_map[s["id"]], reverse=True)

    return recently_used + never_used


def list_mapped(db_path: Path) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = get_mapped_filaments(conn)
        return [dict(r) for r in rows]


def list_mapped_by_spool(db_path: Path) -> tuple[list[dict], int]:
    """Return (groups, total_count). Each group: spool meta + filaments list."""
    with get_connection(db_path) as conn:
        rows = get_mapped_filaments(conn)
        used_map = _get_all_used_weights(conn)

    groups: dict[int, dict] = {}
    for row in rows:
        r = dict(row)
        sid = r["filament_spool_id"]
        if sid not in groups:
            initial = r.get("spool_initial_weight_g") or 0.0
            used = used_map.get(sid, 0.0)
            groups[sid] = {
                "spool_id": sid,
                "spool_color_name": r["spool_color_name"],
                "spool_color_hex": r["spool_color_hex"],
                "spool_material": r["spool_material"],
                "spool_remaining_weight_g": max(0.0, initial - used),
                "filaments": [],
            }
        groups[sid]["filaments"].append(r)

    group_list = list(groups.values())
    total = sum(len(g["filaments"]) for g in group_list)
    return group_list, total


def list_ignored(db_path: Path) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = get_ignored_filaments(conn)
        return [dict(r) for r in rows]


def do_ignore(db_path: Path, ptf_id: int) -> None:
    with get_connection(db_path) as conn:
        if get_ptf_by_id(conn, ptf_id) is None:
            raise SpoolNotFoundError(f"耗材記錄 id={ptf_id} 不存在。")
        try:
            ignore_filament(conn, ptf_id)
        except DatabaseError as exc:
            raise SpoolNotFoundError(str(exc)) from exc


def do_unignore(db_path: Path, ptf_id: int) -> None:
    with get_connection(db_path) as conn:
        try:
            unignore_filament(conn, ptf_id)
        except DatabaseError as exc:
            raise SpoolNotFoundError(str(exc)) from exc


def read_ptf_material(db_path: Path, ptf_id: int):
    with get_connection(db_path) as conn:
        row = get_ptf_material(conn, ptf_id)
        return row["material"] if row else None


def edit_ptf_material(db_path: Path, ptf_id: int, material) -> None:
    with get_connection(db_path) as conn:
        if get_ptf_by_id(conn, ptf_id) is None:
            raise SpoolNotFoundError(f"耗材記錄 id={ptf_id} 不存在。")
        affected = update_ptf_material(conn, ptf_id, material)
        if affected == 0:
            raise SpoolNotFoundError(f"耗材記錄 id={ptf_id} 已完成對照，無法修改材料。")


def do_unmap(db_path: Path, ptf_id: int) -> None:
    with get_connection(db_path) as conn:
        try:
            unmap_filament(conn, ptf_id)
        except DatabaseError as exc:
            raise SpoolNotFoundError(str(exc)) from exc


def read_mapped_filament(db_path: Path, ptf_id: int) -> dict | None:
    with get_connection(db_path) as conn:
        row = get_mapped_filament_by_id(conn, ptf_id)
        return dict(row) if row else None


def do_map(db_path: Path, ptf_id: int, spool_id: int) -> None:
    with get_connection(db_path) as conn:
        if get_spool_by_id(conn, spool_id) is None:
            raise SpoolNotFoundError(f"Spool id={spool_id} 不存在。")
        if get_ptf_by_id(conn, ptf_id) is None:
            raise SpoolNotFoundError(f"耗材記錄 id={ptf_id} 不存在。")
        try:
            map_filament_to_spool(conn, ptf_id, spool_id)
        except DatabaseError as exc:
            raise SpoolNotFoundError(str(exc)) from exc


# --- Import / Export ---

def _sanitize_csv_value(val) -> str:
    if val is None:
        return ""
    s = str(val)
    if s and s[0] in _CSV_FORMULA_CHARS:
        return "'" + s
    return s


def export_spools_json(db_path: Path) -> str:
    with get_connection(db_path) as conn:
        rows = get_all_spools(conn)
    spools = [{k: dict(row).get(k) for k in _SPOOL_FIELDS} for row in rows]
    return json.dumps(
        {
            "version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "spools": spools,
        },
        ensure_ascii=False,
        indent=2,
    )


def export_spools_csv(db_path: Path) -> str:
    with get_connection(db_path) as conn:
        rows = get_all_spools(conn)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_SPOOL_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        d = dict(row)
        writer.writerow({k: ("" if d.get(k) is None else d[k]) for k in _SPOOL_FIELDS})
    return buf.getvalue()


def import_spools_json(db_path: Path, json_str: str) -> dict:
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise SpoolImportError(f"JSON 格式錯誤：{exc}") from exc
    raw_list = data.get("spools", []) if isinstance(data, dict) else data
    if not isinstance(raw_list, list):
        raise SpoolImportError("JSON 格式錯誤：找不到有效的 spools 陣列。")
    return _import_spool_list(db_path, raw_list)


def import_spools_csv(db_path: Path, csv_str: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_str))
    raw_list = [
        {k.strip().lower(): ((v.strip() or None) if v is not None else None)
         for k, v in row.items() if k is not None}
        for row in reader
    ]
    return _import_spool_list(db_path, raw_list)


def _import_spool_list(db_path: Path, raw_list: list) -> dict:
    imported = 0
    skipped = 0
    errors: list[str] = []
    with get_connection(db_path) as conn:
        existing_uids = {dict(r)["uid"] for r in get_all_spools(conn)}
        for i, s in enumerate(raw_list, start=1):
            uid = str(s.get("uid") or "").strip() or None
            if uid and uid in existing_uids:
                skipped += 1
                continue
            data = {
                "uid": uid or str(uuid.uuid4()),
                "material": s.get("material") or None,
                "color_name": s.get("color_name") or None,
                "color_hex": s.get("color_hex") or None,
                "initial_weight_g": s.get("initial_weight_g"),
                "price": s.get("price") or None,
                "purchased_at": _normalize_date(s.get("purchased_at") or None),
                "product_url": s.get("product_url") or None,
                "note": s.get("note") or None,
            }
            try:
                _validate_spool_data(data)
                insert_spool(conn, data)
                existing_uids.add(data["uid"])
                imported += 1
            except SpoolValidationError as exc:
                errors.append(f"第 {i} 筆：{exc}")
    return {"imported": imported, "skipped": skipped, "failed": len(errors), "errors": errors}

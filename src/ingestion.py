import json
import requests
from pathlib import Path

from .config import AppConfig
from .db import (
    get_connection,
    get_db_path,
    insert_print_task_filament,
    insert_print_task_ignore,
    update_task_cover_if_null,
    upsert_printer,
)


class IngestionError(Exception):
    pass


_ALLOWED_COVER_HOSTS = (
    ".bambulab.com",
    ".amazonaws.com",
    ".bblmw.com",
)


_MAX_COVER_BYTES = 10 * 1024 * 1024  # 10 MB


def _is_allowed_cover_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        host = parsed.netloc.lower()
        return any(host == h.lstrip(".") or host.endswith(h) for h in _ALLOWED_COVER_HOSTS)
    except Exception:
        return False


def _is_valid_image_bytes(data: bytes) -> bool:
    if len(data) < 12:
        return False
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return True
    if data[:3] == b'\xff\xd8\xff':
        return True
    if data[:4] == b'GIF8' and data[4:5] in (b'7', b'9'):
        return True
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    return False


def _cache_cover(external_id: int, url: str, covers_dir: Path) -> str | None:
    if not _is_allowed_cover_url(url):
        print(f"[WARN] cover URL 來源不在白名單，已跳過：{url[:80]}")
        return None
    covers_dir.mkdir(parents=True, exist_ok=True)
    out_path = covers_dir / f"{external_id}.png"
    if out_path.exists():
        return f"/covers/{external_id}.png"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.content
        if len(data) > _MAX_COVER_BYTES:
            print(f"[WARN] 封面圖超過大小限制，已跳過（id={external_id}）")
            return None
        if not _is_valid_image_bytes(data):
            print(f"[WARN] 封面圖格式無效，已跳過（id={external_id}）")
            return None
        tmp = out_path.with_suffix(".tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(out_path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return f"/covers/{external_id}.png"
    except Exception as exc:
        print(f"[WARN] 封面圖下載失敗（id={external_id}），可能為過期 URL：{exc}")
        return None


def _extract_slot_id(item: dict) -> int | None:
    # slotId 優先（真實 Bambu API），position 為 fallback（sample/測試資料）
    for key in ("slotId", "position"):
        val = item.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                continue
    return None


def _convert_color(raw_color: str | None) -> str | None:
    if not raw_color or len(raw_color) != 8:
        return None
    try:
        int(raw_color, 16)
        return f"#{raw_color[:6].upper()}"
    except ValueError:
        return None


def _extract_print_name(raw: dict) -> str | None:
    for key in ("designTitle", "title", "name"):
        val = raw.get(key)
        if val:
            return str(val)
    return None


def _build_filament_rows(raw_task: dict, print_task_id: int) -> list[dict]:
    ams = raw_task.get("amsDetailMapping") or []
    total_weight = raw_task.get("weight")

    if not ams:
        return [{
            "print_task_id": print_task_id,
            "filament_spool_id": None,
            "slot_id": None,
            "used_weight_g": total_weight,
            "color_hex": None,
            "material": None,
        }]

    return [
        {
            "print_task_id": print_task_id,
            "filament_spool_id": None,
            "slot_id": _extract_slot_id(item),
            "used_weight_g": item.get("weight"),
            "color_hex": _convert_color(item.get("sourceColor")),
            "material": item.get("filamentType"),
        }
        for item in ams
    ]


def ingest_raw_tasks(
    raw_hits: list[dict], db_path: Path, covers_dir: Path | None = None
) -> dict[str, int]:
    stats: dict[str, int] = {"inserted": 0, "skipped": 0, "filaments": 0}

    errors: list[str] = []

    for raw in raw_hits:
        if "id" not in raw:
            errors.append(f"記錄缺少 id 欄位，已跳過：{str(raw)[:80]}")
            stats["skipped"] += 1
            continue

        try:
            local_cover: str | None = None
            raw_cover = raw.get("cover")
            if raw_cover and covers_dir:
                local_cover = _cache_cover(raw["id"], raw_cover, covers_dir)

            with get_connection(db_path) as conn:
                device_id = raw.get("deviceId")
                printer_id = None
                if device_id:
                    printer_id = upsert_printer(
                        conn,
                        device_id=device_id,
                        name=raw.get("deviceName") or device_id,
                        model=raw.get("deviceModel"),
                    )

                plate_name_raw = str(raw.get("plateName") or "").strip()
                task_row = {
                    "external_id": raw["id"],
                    "print_name": _extract_print_name(raw),
                    "printer_id": printer_id,
                    "started_at": raw.get("startTime"),
                    "ended_at": raw.get("endTime"),
                    "duration_seconds": raw.get("costTime"),
                    "total_weight_g": raw.get("weight"),
                    "cover_url": local_cover,
                    "raw_json": json.dumps(raw, ensure_ascii=False),
                    "plate_index": raw.get("plateIndex"),
                    "plate_name": plate_name_raw or None,
                }

                task_db_id = insert_print_task_ignore(conn, task_row)
                if task_db_id is None:
                    stats["skipped"] += 1
                    if local_cover:
                        update_task_cover_if_null(conn, raw["id"], local_cover)
                    continue

                stats["inserted"] += 1
                for row in _build_filament_rows(raw, task_db_id):
                    insert_print_task_filament(conn, row)
                    stats["filaments"] += 1

        except Exception as exc:  # noqa: BLE001
            errors.append(f"task id={raw.get('id')} 處理失敗，已跳過：{exc}")
            stats["skipped"] += 1

    if errors:
        print(f"[WARN] 匯入時有 {len(errors)} 筆記錄發生錯誤：")
        for e in errors:
            print(f"  - {e}")

    return stats


def _parse_raw_file(raw_file: Path) -> list[dict]:
    with open(raw_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if "pages" in data:
        hits: list[dict] = []
        for page in data["pages"]:
            page_hits = page.get("hits")
            if not isinstance(page_hits, list):
                raise IngestionError(
                    f"raw_tasks.json 格式錯誤：pages[] 中的頁面缺少 hits 陣列。"
                )
            hits.extend(page_hits)
        return hits

    if "hits" in data:
        return data["hits"]

    raise IngestionError(
        "raw_tasks.json 格式無法識別。預期格式：{\"pages\": [...]} 或 {\"hits\": [...]} 或 [...]"
    )


def try_redownload_cover(external_id: int, covers_dir: Path, db_path: Path) -> str | None:
    """若本地封面圖不存在，從 raw_json 取回原始 URL 並重新下載。"""
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT raw_json FROM print_task WHERE external_id=? AND is_manual=0",
                (external_id,),
            ).fetchone()
        if not row or not row["raw_json"]:
            return None
        raw = json.loads(row["raw_json"])
        url = raw.get("cover")
        if not url:
            return None
        return _cache_cover(external_id, url, covers_dir)
    except Exception as exc:
        print(f"[WARN] 封面圖重新下載失敗（external_id={external_id}）：{exc}")
        return None


def run_ingestion_from_file(raw_file: Path, db_path: Path) -> dict[str, int]:
    if not raw_file.exists():
        raise IngestionError(f"找不到 raw_tasks.json：{raw_file}")
    hits = _parse_raw_file(raw_file)
    if not hits:
        raise IngestionError("raw_tasks.json 中沒有任何列印記錄。")
    covers_dir = (db_path.parent / "covers").resolve()
    return ingest_raw_tasks(hits, db_path, covers_dir)


def run_ingestion_from_cloud(config: AppConfig, db_path: Path) -> dict[str, int]:
    from .cloud_client import BambuCloudClient
    client = BambuCloudClient(config)
    hits = client.fetch_all_tasks()
    client.save_raw_tasks(config.output_dir / "raw_tasks.json")
    covers_dir = (db_path.parent / "covers").resolve()
    return ingest_raw_tasks(hits, db_path, covers_dir)

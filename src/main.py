import argparse
import sys
from pathlib import Path

from .auth import AuthError
from .cloud_client import BambuCloudClient, EmptyResultError, NetworkError, RateLimitError
from .config import ConfigError, load_config
from .export_csv import export_csv
from .export_json import export_json
from .normalize import normalize_tasks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bambu-print-manager",
        description="Bambu Lab 列印歷史與耗材管理工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- export ---
    export_parser = subparsers.add_parser("export", help="匯出列印歷史（JSON/CSV）")
    export_parser.add_argument(
        "--format",
        choices=["json", "csv", "both"],
        default="json",
        help="輸出格式（預設：json）",
    )
    export_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="輸出目錄（預設：data/）",
    )

    # --- import ---
    import_parser = subparsers.add_parser("import", help="匯入列印歷史到 SQLite")
    import_parser.add_argument(
        "--from-file",
        action="store_true",
        help="從已存在的 raw_tasks.json 匯入（不呼叫 Cloud API）",
    )

    # --- unmapped ---
    subparsers.add_parser("unmapped", help="顯示未 mapping 的耗材記錄")

    # --- map ---
    subparsers.add_parser("map", help="互動式手動 mapping 耗材")

    # --- filament ---
    filament_parser = subparsers.add_parser("filament", help="耗材管理")
    filament_sub = filament_parser.add_subparsers(dest="filament_command", required=True)
    filament_sub.add_parser("status", help="查詢所有 spool 狀態")

    # --- web ---
    web_parser = subparsers.add_parser("web", help="啟動 Web UI")
    web_parser.add_argument("--host", default="127.0.0.1", help="監聽位址（預設：127.0.0.1）")
    web_parser.add_argument("--port", type=int, default=5000, help="埠號（預設：5000）")
    web_parser.add_argument("--debug", action="store_true", help="啟用 Flask debug 模式")

    return parser


# --- export ---

def cmd_export(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(exc)
        return 1

    if args.output_dir is not None:
        config.output_dir = args.output_dir

    config.output_dir.mkdir(parents=True, exist_ok=True)
    client = BambuCloudClient(config)

    try:
        hits = client.fetch_all_tasks()
    except AuthError as exc:
        print(exc)
        return 1
    except RateLimitError as exc:
        print(exc)
        return 1
    except NetworkError as exc:
        print(exc)
        return 1
    except EmptyResultError as exc:
        print(exc)
        return 0

    try:
        client.save_raw_tasks(config.output_dir / "raw_tasks.json")
        records = normalize_tasks(hits)
        fmt = args.format
        if fmt in ("json", "both"):
            export_json(records, config.output_dir / "print_history.json")
        if fmt in ("csv", "both"):
            export_csv(records, config.output_dir / "print_history.csv")
    except OSError as exc:
        print(f"[ERROR] 檔案寫入失敗：{exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 輸出時發生非預期錯誤：{exc}")
        return 1

    return 0


# --- import ---

def cmd_import(args: argparse.Namespace) -> int:
    from .db import get_db_path, init_db
    from .ingestion import IngestionError, run_ingestion_from_cloud, run_ingestion_from_file

    try:
        config = load_config()
    except ConfigError as exc:
        print(exc)
        return 1

    config.output_dir.mkdir(parents=True, exist_ok=True)
    db_path = get_db_path(config.output_dir)
    init_db(db_path)

    try:
        if args.from_file:
            raw_file = config.output_dir / "raw_tasks.json"
            print(f"[INFO] 從檔案匯入：{raw_file}")
            stats = run_ingestion_from_file(raw_file, db_path)
        else:
            print("[INFO] 從 Bambu Cloud 抓取資料...")
            stats = run_ingestion_from_cloud(config, db_path)
    except IngestionError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except (AuthError, NetworkError, RateLimitError, EmptyResultError) as exc:
        print(exc)
        return 1

    print(
        f"[OK] 匯入完成：新增 {stats['inserted']} 筆，"
        f"更新 {stats['updated']} 筆，"
        f"略過 {stats['skipped']} 筆，"
        f"filament 記錄 {stats['filaments']} 筆"
    )
    return 0


# --- unmapped ---

def cmd_unmapped(args: argparse.Namespace) -> int:
    from .db import get_db_path, init_db
    from .filament import list_unmapped

    try:
        config = load_config()
    except ConfigError as exc:
        print(exc)
        return 1

    db_path = get_db_path(config.output_dir)
    init_db(db_path)
    rows = list_unmapped(db_path)

    if not rows:
        print("[OK] 沒有未 mapping 的耗材記錄。")
        return 0

    print(f"未 mapping 耗材記錄共 {len(rows)} 筆：\n")
    for r in rows:
        date = (r["started_at"] or "")[:10]
        print(
            f"  ptf_id={r['id']:<6} "
            f"任務={r['print_name'] or '(未命名)':<30} "
            f"材料={r['material'] or '-':<8} "
            f"顏色={r['color_hex'] or '-':<10} "
            f"用量={r['used_weight_g'] or 0:.1f}g  "
            f"日期={date}"
        )
    return 0


# --- map ---

def cmd_map(args: argparse.Namespace) -> int:
    from .db import get_db_path, init_db
    from .filament import SpoolNotFoundError, do_map, list_spools, list_unmapped

    try:
        config = load_config()
    except ConfigError as exc:
        print(exc)
        return 1

    db_path = get_db_path(config.output_dir)
    init_db(db_path)

    unmapped = list_unmapped(db_path)
    if not unmapped:
        print("[OK] 沒有需要 mapping 的記錄。")
        return 0

    spools = list_spools(db_path)
    if not spools:
        print("[WARN] 目前沒有任何 spool 記錄，請先透過 Web UI 或 API 新增 spool。")
        return 1

    print("可用 Spool 清單：")
    for s in spools:
        label = s.get("color_name") or s.get("color_hex") or "-"
        print(
            f"  [{s['id']}] {label} {s['material'] or '-'} "
            f"{s['initial_weight_g']}g "
            f"（剩餘 {s['remaining_weight_g']:.1f}g，{s['status']}）"
        )

    print(f"\n共 {len(unmapped)} 筆未 mapping 記錄，逐筆處理（Enter=跳過，q=結束）：\n")
    for r in unmapped:
        date = (r["started_at"] or "")[:10]
        print(
            f"--- ptf_id={r['id']} | {r['print_name'] or '(未命名)'} | "
            f"{r['material'] or '-'} {r['color_hex'] or '-'} "
            f"{r['used_weight_g'] or 0:.1f}g | {date} ---"
        )
        try:
            ans = input("輸入 spool id：").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[ABORT] 使用者中斷。")
            return 130

        if ans.lower() == "q":
            break
        if not ans:
            continue

        try:
            do_map(db_path, r["id"], int(ans))
            print(f"[OK] 已關聯 ptf_id={r['id']} → spool_id={ans}\n")
        except (ValueError, SpoolNotFoundError) as e:
            print(f"[ERR] {e}\n")

    return 0


# --- filament status ---

def cmd_filament_status(args: argparse.Namespace) -> int:
    from .db import get_db_path, init_db
    from .filament import list_spools

    try:
        config = load_config()
    except ConfigError as exc:
        print(exc)
        return 1

    db_path = get_db_path(config.output_dir)
    init_db(db_path)
    spools = list_spools(db_path)

    if not spools:
        print("目前沒有任何 spool 記錄。")
        return 0

    header = f"{'ID':<4} {'Material':<10} {'Color':<10} {'Init(g)':>8} {'Used(g)':>8} {'Left(g)':>8} {'Status':<8}"
    print(header)
    print("-" * len(header))
    for s in spools:
        print(
            f"{s['id']:<4} "
            f"{(s['material'] or '-'):<10} "
            f"{(s['color_hex'] or '-'):<10} "
            f"{s['initial_weight_g']:>7.1f}g "
            f"{s['used_weight_g']:>7.1f}g "
            f"{s['remaining_weight_g']:>7.1f}g "
            f"{s['status']:<8}"
        )
    return 0


# --- web ---

def cmd_web(args: argparse.Namespace) -> int:
    try:
        from web.app import create_app
    except ImportError as exc:
        print(f"[ERROR] 無法載入 Web UI：{exc}")
        print("[HINT] 請確認已安裝 flask：.venv/Scripts/python.exe -m pip install flask>=3.0.0")
        return 1

    try:
        app = create_app()
    except OSError as exc:
        print(f"[ERROR] 無法建立應用目錄（請確認使用者資料目錄可寫入）：{exc}")
        return 1
    print(f"[INFO] 啟動 Web UI：http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


# --- main ---

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "export":
            exit_code = cmd_export(args)
        elif args.command == "import":
            exit_code = cmd_import(args)
        elif args.command == "unmapped":
            exit_code = cmd_unmapped(args)
        elif args.command == "map":
            exit_code = cmd_map(args)
        elif args.command == "filament":
            if args.filament_command == "status":
                exit_code = cmd_filament_status(args)
            else:
                parser.print_help()
                exit_code = 1
        elif args.command == "web":
            exit_code = cmd_web(args)
        else:
            parser.print_help()
            exit_code = 1
    except KeyboardInterrupt:
        print("\n[ABORT] 使用者中斷操作。")
        exit_code = 130

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

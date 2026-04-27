from datetime import datetime
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from web.i18n import t

from src.db import (
    delete_manual_task,
    get_all_printers,
    get_all_spools,
    get_connection,
    get_task_with_filaments,
    get_tasks_page,
    insert_manual_task,
    insert_print_task_filament,
    replace_task_filaments,
    update_manual_task,
    update_task_cover_url,
)

_ALLOWED_COVER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

bp = Blueprint("tasks", __name__)


def _is_valid_image(header: bytes) -> bool:
    if header[:8] == b'\x89PNG\r\n\x1a\n':
        return True
    if header[:3] == b'\xff\xd8\xff':
        return True
    if header[:4] in (b'GIF8',) and header[4:5] in (b'7', b'9'):
        return True
    if header[:4] == b'RIFF' and len(header) >= 12 and header[8:12] == b'WEBP':
        return True
    return False

PER_PAGE = 20


# ── list & detail ─────────────────────────────────────────────────────────────

@bp.route("/")
def list_view():
    db_path = current_app.config["DB_PATH"]
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()

    with get_connection(db_path) as conn:
        tasks, total = get_tasks_page(conn, page, PER_PAGE, search)

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    return render_template(
        "tasks/list.html",
        tasks=tasks,
        page=page,
        total_pages=total_pages,
        total=total,
        search=search,
    )


@bp.route("/<int:task_id>")
def detail_view(task_id: int):
    db_path = current_app.config["DB_PATH"]
    with get_connection(db_path) as conn:
        task = get_task_with_filaments(conn, task_id)

    if task is None:
        return render_template("tasks/list.html", tasks=[], page=1, total_pages=1, total=0, search=""), 404

    return render_template("tasks/detail.html", task=task)


# ── manual task form helpers ──────────────────────────────────────────────────

def _parse_task_form(form) -> dict:
    name = form.get("print_name", "").strip() or None
    started_at = form.get("started_at", "").strip() or None
    ended_at = form.get("ended_at", "").strip() or None

    # Duration: prefer auto-calc from times; fall back to manual h/m inputs
    duration_seconds = None
    if started_at and ended_at:
        try:
            dt_start = datetime.fromisoformat(started_at)
            dt_end = datetime.fromisoformat(ended_at)
            diff = int((dt_end - dt_start).total_seconds())
            if diff > 0:
                duration_seconds = diff
        except ValueError:
            pass

    if duration_seconds is None:
        try:
            h = int(form.get("duration_h", 0) or 0)
            m = int(form.get("duration_m", 0) or 0)
            total = h * 3600 + m * 60
            if total > 0:
                duration_seconds = total
        except (ValueError, TypeError):
            pass

    printer_id = None
    raw_pid = form.get("printer_id", "").strip()
    if raw_pid:
        try:
            printer_id = int(raw_pid)
        except ValueError:
            pass

    total_weight_g = None
    raw_w = form.get("total_weight_g", "").strip()
    if raw_w:
        try:
            val = float(raw_w)
            if 0 <= val <= 100_000:
                total_weight_g = val
        except ValueError:
            pass

    return {
        "print_name": name,
        "printer_id": printer_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration_seconds,
        "total_weight_g": total_weight_g,
    }


def _parse_filament_form(form) -> list[dict]:
    materials = form.getlist("filament_material")
    colors    = form.getlist("filament_color")
    weights   = form.getlist("filament_weight")
    slots     = form.getlist("filament_slot")
    spool_ids = form.getlist("filament_spool")

    result = []
    for i in range(len(materials)):
        material   = materials[i].strip()   if i < len(materials)   else ""
        color      = colors[i].strip()      if i < len(colors)      else ""
        weight_raw = weights[i].strip()     if i < len(weights)     else ""
        slot_raw   = slots[i].strip()       if i < len(slots)       else ""
        spool_raw  = spool_ids[i].strip()   if i < len(spool_ids)   else ""

        # Skip rows with no substantive content.
        # Color is excluded from this check because the color picker always
        # emits a value (#ffffff by default), so a row with only a color
        # and nothing else is considered empty.
        if not material and not weight_raw:
            continue

        weight = None
        if weight_raw:
            try:
                val = float(weight_raw)
                if 0 <= val <= 100_000:
                    weight = val
            except ValueError:
                pass

        slot = None
        if slot_raw:
            try:
                val = int(slot_raw)
                if 0 <= val <= 255:
                    slot = val
            except ValueError:
                pass

        spool_id = None
        if spool_raw:
            try:
                spool_id = int(spool_raw)
            except ValueError:
                pass

        result.append({
            "filament_spool_id": spool_id,
            "slot_id": slot,
            "used_weight_g": weight,
            "color_hex": color or None,
            "material": material or None,
        })

    return result


def _save_manual_cover(covers_dir: Path, task_id: int, file) -> str | None:
    """Save an uploaded image as the manual task cover; return cover_url or None."""
    if not file or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_COVER_EXTS:
        return None
    header = file.read(12)
    file.stream.seek(0)
    if not _is_valid_image(header):
        return None
    covers_dir.mkdir(parents=True, exist_ok=True)
    filename = f"m{task_id}{ext}"
    file.save(covers_dir / filename)
    return f"/covers/{filename}"


def _remove_manual_cover(covers_dir: Path, task_id: int) -> None:
    """Delete any existing manual cover file for this task (all extensions)."""
    for ext in _ALLOWED_COVER_EXTS:
        p = covers_dir / f"m{task_id}{ext}"
        if p.exists():
            p.unlink()


def _load_form_choices(db_path):
    with get_connection(db_path) as conn:
        printers = [dict(r) for r in get_all_printers(conn)]
        spools   = [dict(r) for r in get_all_spools(conn)]
    return printers, spools


# ── new manual task ───────────────────────────────────────────────────────────

@bp.route("/new", methods=["GET", "POST"])
def new_manual():
    db_path = current_app.config["DB_PATH"]

    if request.method == "GET":
        printers, spools = _load_form_choices(db_path)
        return render_template("tasks/manual_form.html",
                               task=None, printers=printers, spools=spools)

    task_data  = _parse_task_form(request.form)
    filaments  = _parse_filament_form(request.form)

    if not task_data["print_name"]:
        printers, spools = _load_form_choices(db_path)
        flash(t("flash.tasks.name_required"), "error")
        task_data["started_at_input"] = (task_data.get("started_at") or "")[:16]
        task_data["ended_at_input"]   = (task_data.get("ended_at")   or "")[:16]
        ds = task_data.get("duration_seconds") or 0
        task_data["duration_h_input"] = ds // 3600
        task_data["duration_m_input"] = (ds % 3600) // 60
        task_data["filaments"] = filaments
        return render_template("tasks/manual_form.html",
                               task=task_data, printers=printers, spools=spools)

    covers_dir = current_app.config["COVERS_DIR"]
    cover_file  = request.files.get("cover")

    with get_connection(db_path) as conn:
        task_id   = insert_manual_task(conn, task_data)
        cover_url = _save_manual_cover(covers_dir, task_id, cover_file)
        if cover_url:
            update_task_cover_url(conn, task_id, cover_url)
        for f in filaments:
            f["print_task_id"] = task_id
            insert_print_task_filament(conn, f)

    flash(t("flash.tasks.added"), "success")
    return redirect(url_for("tasks.detail_view", task_id=task_id))


# ── edit manual task ──────────────────────────────────────────────────────────

@bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
def edit_manual(task_id: int):
    db_path = current_app.config["DB_PATH"]

    with get_connection(db_path) as conn:
        task = get_task_with_filaments(conn, task_id)

    if task is None or not task.get("is_manual"):
        abort(404)

    if request.method == "GET":
        printers, spools = _load_form_choices(db_path)
        # Pre-format datetime fields for HTML datetime-local input
        task = dict(task)
        task["started_at_input"] = (task.get("started_at") or "")[:16]
        task["ended_at_input"]   = (task.get("ended_at")   or "")[:16]
        ds = task.get("duration_seconds") or 0
        task["duration_h_input"] = ds // 3600
        task["duration_m_input"] = (ds % 3600) // 60
        return render_template("tasks/manual_form.html",
                               task=task, printers=printers, spools=spools)

    task_data = _parse_task_form(request.form)
    filaments = _parse_filament_form(request.form)

    if not task_data["print_name"]:
        printers, spools = _load_form_choices(db_path)
        flash(t("flash.tasks.name_required"), "error")
        task_data["id"] = task_id
        task_data["filaments"] = filaments
        task_data["started_at_input"] = (task_data.get("started_at") or "")[:16]
        task_data["ended_at_input"]   = (task_data.get("ended_at")   or "")[:16]
        ds = task_data.get("duration_seconds") or 0
        task_data["duration_h_input"] = ds // 3600
        task_data["duration_m_input"] = (ds % 3600) // 60
        return render_template("tasks/manual_form.html",
                               task=task_data, printers=printers, spools=spools)

    covers_dir  = current_app.config["COVERS_DIR"]
    cover_file  = request.files.get("cover")
    clear_cover = request.form.get("clear_cover") == "1"

    # Validate extension first — before any destructive file operation
    new_ext: str | None = None
    if cover_file and cover_file.filename:
        ext = Path(cover_file.filename).suffix.lower()
        if ext not in _ALLOWED_COVER_EXTS:
            flash(t("flash.tasks.invalid_ext", ext=ext), "error")
            cover_file = None
        else:
            new_ext = ext

    # Pre-compute intended cover_url so DB update can be done before file I/O
    if new_ext:
        task_data["cover_url"] = f"/covers/m{task_id}{new_ext}"
    elif clear_cover:
        task_data["cover_url"] = None
    else:
        task_data["cover_url"] = task.get("cover_url")

    # DB update first — if it fails, no file has been touched yet
    with get_connection(db_path) as conn:
        ok = update_manual_task(conn, task_id, task_data)
        if not ok:
            abort(404)
        replace_task_filaments(conn, task_id, filaments)

    # File operations only after successful DB commit
    if new_ext and cover_file:
        _remove_manual_cover(covers_dir, task_id)
        covers_dir.mkdir(parents=True, exist_ok=True)
        cover_file.save(covers_dir / f"m{task_id}{new_ext}")
    elif clear_cover:
        _remove_manual_cover(covers_dir, task_id)

    flash(t("flash.tasks.updated"), "success")
    return redirect(url_for("tasks.detail_view", task_id=task_id))


# ── delete manual task ────────────────────────────────────────────────────────

@bp.route("/<int:task_id>/delete", methods=["POST"])
def delete_manual(task_id: int):
    db_path    = current_app.config["DB_PATH"]
    covers_dir = current_app.config["COVERS_DIR"]

    with get_connection(db_path) as conn:
        ok = delete_manual_task(conn, task_id)

    if not ok:
        abort(404)

    _remove_manual_cover(covers_dir, task_id)
    flash(t("flash.tasks.deleted"), "success")
    return redirect(url_for("tasks.list_view"))

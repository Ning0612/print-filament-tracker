from flask import Blueprint, current_app, render_template, request
from markupsafe import escape

from web.i18n import t

from src.filament import (
    SpoolNotFoundError,
    do_ignore,
    do_map,
    do_unignore,
    do_unmap,
    edit_ptf_material,
    list_ignored,
    list_mapped_by_spool,
    list_spools_for_mapping,
    list_unmapped,
    read_mapped_filament,
    read_ptf_material,
    read_ptf_with_spool,
    read_spool,
)

bp = Blueprint("mapping", __name__)


@bp.route("/")
def list_view():
    db_path = current_app.config["DB_PATH"]
    show = request.args.get("show", "unmapped")
    if show not in ("unmapped", "mapped", "ignored"):
        show = "unmapped"
    unmapped = list_unmapped(db_path)
    mapped_by_spool, mapped_count = list_mapped_by_spool(db_path)
    ignored = list_ignored(db_path)
    spools = list_spools_for_mapping(db_path)
    return render_template(
        "mapping/unmapped.html",
        unmapped=unmapped,
        mapped_by_spool=mapped_by_spool,
        mapped_count=mapped_count,
        ignored=ignored,
        spools=spools,
        show=show,
    )


@bp.route("/<int:ptf_id>/map", methods=["POST"])
def map_view(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    spool_id_str = request.form.get("spool_id", "").strip()

    if not spool_id_str:
        return _row_error(ptf_id, t("flash.mapping.select_spool"))

    if spool_id_str == "__ignore__":
        try:
            do_ignore(db_path, ptf_id)
        except SpoolNotFoundError as exc:
            return _row_error(ptf_id, str(exc))
        return render_template("mapping/ignored_row.html", ptf_id=ptf_id)

    try:
        spool_id = int(spool_id_str)
        do_map(db_path, ptf_id, spool_id)
    except (ValueError, SpoolNotFoundError) as exc:
        return _row_error(ptf_id, str(exc))

    try:
        spool = read_spool(db_path, spool_id)
    except SpoolNotFoundError:
        spool = None
    return render_template("mapping/mapped_row.html", ptf_id=ptf_id, spool=spool)


@bp.route("/<int:ptf_id>/material-edit")
def material_edit_form(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    material = read_ptf_material(db_path, ptf_id)
    return render_template(
        "mapping/_material_edit.html", ptf_id=ptf_id, current=material or ""
    )


@bp.route("/<int:ptf_id>/material", methods=["POST"])
def material_save(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    new_material = request.form.get("material", "").strip() or None
    try:
        edit_ptf_material(db_path, ptf_id, new_material)
        material = new_material
    except SpoolNotFoundError:
        material = read_ptf_material(db_path, ptf_id)
    return render_template(
        "mapping/_material_display.html", ptf_id=ptf_id, material=material
    )


@bp.route("/<int:ptf_id>/material-cancel")
def material_cancel(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    material = read_ptf_material(db_path, ptf_id)
    return render_template(
        "mapping/_material_display.html", ptf_id=ptf_id, material=material
    )


@bp.route("/<int:ptf_id>/remap-form")
def remap_form(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    r = read_mapped_filament(db_path, ptf_id)
    if r is None:
        return _mapped_row_error(ptf_id, t("flash.mapping.not_found"))
    spools = list_spools_for_mapping(db_path)
    return render_template("mapping/_remap_row.html", r=r, spools=spools)


@bp.route("/<int:ptf_id>/remap", methods=["POST"])
def remap_view(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    spool_id_str = request.form.get("spool_id", "").strip()
    if not spool_id_str:
        return _mapped_row_error(ptf_id, t("flash.mapping.select_spool_remap"))
    try:
        spool_id = int(spool_id_str)
        do_map(db_path, ptf_id, spool_id)
    except (ValueError, SpoolNotFoundError) as exc:
        return _mapped_row_error(ptf_id, str(exc))
    r = read_mapped_filament(db_path, ptf_id)
    if r is None:
        return _mapped_row_error(ptf_id, t("flash.mapping.remap_read_failed"))
    return render_template("mapping/_mapped_detail_row.html", r=r)


@bp.route("/<int:ptf_id>/unmap", methods=["POST"])
def unmap_view(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    try:
        do_unmap(db_path, ptf_id)
    except SpoolNotFoundError:
        pass
    return f'<tr id="mapped-row-{ptf_id}" style="display:none;"></tr>'


@bp.route("/<int:ptf_id>/mapped-row")
def mapped_row_view(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    r = read_mapped_filament(db_path, ptf_id)
    if r is None:
        return f'<tr id="mapped-row-{ptf_id}" style="display:none;"></tr>'
    return render_template("mapping/_mapped_detail_row.html", r=r)


@bp.route("/<int:ptf_id>/unignore", methods=["POST"])
def unignore_view(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    try:
        do_unignore(db_path, ptf_id)
    except SpoolNotFoundError:
        pass
    return f'<tr id="ignored-row-{ptf_id}" style="display:none;"></tr>'


@bp.route("/<int:ptf_id>/detail-remap-form")
def detail_remap_form(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    f = read_ptf_with_spool(db_path, ptf_id)
    if f is None:
        return _detail_row_error(ptf_id, t("flash.mapping.not_found"))
    spools = list_spools_for_mapping(db_path)
    return render_template("tasks/_filament_remap_row.html", f=f, spools=spools)


@bp.route("/<int:ptf_id>/detail-remap", methods=["POST"])
def detail_remap_view(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    spool_id_str = request.form.get("spool_id", "").strip()
    if not spool_id_str:
        return _detail_row_error(ptf_id, t("flash.mapping.select_spool_remap"))
    try:
        spool_id = int(spool_id_str)
        do_map(db_path, ptf_id, spool_id)
    except (ValueError, SpoolNotFoundError) as exc:
        return _detail_row_error(ptf_id, str(exc))
    f = read_ptf_with_spool(db_path, ptf_id)
    if f is None:
        return _detail_row_error(ptf_id, t("flash.mapping.remap_read_failed"))
    return render_template("tasks/_filament_row.html", f=f)


@bp.route("/<int:ptf_id>/detail-unmap", methods=["POST"])
def detail_unmap_view(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    try:
        do_unmap(db_path, ptf_id)
    except SpoolNotFoundError:
        pass
    f = read_ptf_with_spool(db_path, ptf_id)
    if f is None:
        return f'<tr id="detail-filament-{ptf_id}" style="display:none;"></tr>'
    return render_template("tasks/_filament_row.html", f=f)


@bp.route("/<int:ptf_id>/detail-row")
def detail_filament_row(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    f = read_ptf_with_spool(db_path, ptf_id)
    if f is None:
        return f'<tr id="detail-filament-{ptf_id}" style="display:none;"></tr>'
    return render_template("tasks/_filament_row.html", f=f)


def _row_error(ptf_id: int, msg: str) -> str:
    return render_template("mapping/error_row.html", ptf_id=ptf_id, msg=msg)


def _mapped_row_error(ptf_id: int, msg: str) -> str:
    safe_msg = escape(msg)
    safe_prefix = escape(t("common.error_prefix"))
    return f'<tr id="mapped-row-{ptf_id}"><td colspan="8" style="color:var(--pico-del-color);">⚠ {safe_prefix}{safe_msg}</td></tr>'


def _detail_row_error(ptf_id: int, msg: str) -> str:
    safe_msg = escape(msg)
    safe_prefix = escape(t("common.error_prefix"))
    return f'<tr id="detail-filament-{ptf_id}"><td colspan="5" style="color:var(--pico-del-color);">⚠ {safe_prefix}{safe_msg}</td></tr>'

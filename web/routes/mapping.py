from flask import Blueprint, current_app, render_template, request

from src.filament import (
    SpoolNotFoundError,
    do_map,
    edit_ptf_material,
    list_mapped,
    list_spools,
    list_unmapped,
    read_ptf_material,
)

bp = Blueprint("mapping", __name__)


@bp.route("/")
def list_view():
    db_path = current_app.config["DB_PATH"]
    show = request.args.get("show", "unmapped")
    if show not in ("unmapped", "mapped"):
        show = "unmapped"
    unmapped = list_unmapped(db_path)
    mapped = list_mapped(db_path)
    spools = list_spools(db_path)
    return render_template(
        "mapping/unmapped.html",
        unmapped=unmapped,
        mapped=mapped,
        spools=spools,
        show=show,
    )


@bp.route("/<int:ptf_id>/map", methods=["POST"])
def map_view(ptf_id: int):
    db_path = current_app.config["DB_PATH"]
    spool_id_str = request.form.get("spool_id", "").strip()

    if not spool_id_str:
        return _row_error(ptf_id, "請選擇一個 spool。")

    try:
        spool_id = int(spool_id_str)
        do_map(db_path, ptf_id, spool_id)
    except (ValueError, SpoolNotFoundError) as exc:
        return _row_error(ptf_id, str(exc))

    spools = list_spools(db_path)
    spool = next((s for s in spools if s["id"] == spool_id), None)
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


def _row_error(ptf_id: int, msg: str) -> str:
    return render_template("mapping/error_row.html", ptf_id=ptf_id, msg=msg)

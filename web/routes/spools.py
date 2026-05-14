from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for

from web.i18n import t

from src.filament import (
    SpoolImportError,
    SpoolNotFoundError,
    SpoolValidationError,
    create_spool,
    delete_spool_data,
    export_spools_csv,
    export_spools_json,
    import_spools_csv,
    import_spools_json,
    list_spools_with_tasks,
    read_spool,
    read_spool_with_tasks,
    update_spool_data,
)

bp = Blueprint("spools", __name__)

# (status_key, display_label, default_sort_field, default_sort_dir)
_SECTION_CONFIG = [
    ("low",    "偏低",  "usage_ratio", "desc"),
    ("active", "使用中", "usage_ratio", "desc"),
    ("sealed", "未開封", "purchased_at", "desc"),
    ("empty",  "用盡",  "purchased_at", "desc"),
]


@bp.route("/")
def list_view():
    db_path = current_app.config["DB_PATH"]
    all_spools, tasks_by_spool = list_spools_with_tasks(db_path)

    # Per-section sort params (s_<status> = field, d_<status> = asc|desc)
    section_sorts: dict[str, dict] = {}
    for status, _, default_field, default_dir in _SECTION_CONFIG:
        field = request.args.get(f"s_{status}", default_field)
        direction = request.args.get(f"d_{status}", default_dir)
        if field not in ("usage_ratio", "purchased_at"):
            field = default_field
        if direction not in ("asc", "desc"):
            direction = default_dir
        section_sorts[status] = {"sort_by": field, "sort_dir": direction}

    # Group spools by status
    grouped: dict[str, list] = {s: [] for s, *_ in _SECTION_CONFIG}
    for spool in all_spools:
        st = spool.get("status", "active")
        if st in grouped:
            grouped[st].append(spool)

    # Sort each group
    for status, _, _, _ in _SECTION_CONFIG:
        grp = grouped[status]
        sb = section_sorts[status]["sort_by"]
        reverse = section_sorts[status]["sort_dir"] == "desc"
        if sb == "usage_ratio":
            grp.sort(key=lambda s: s["usage_ratio"], reverse=reverse)
        else:
            dated = [s for s in grp if s.get("purchased_at")]
            undated = [s for s in grp if not s.get("purchased_at")]
            dated.sort(key=lambda s: s["purchased_at"], reverse=reverse)
            grouped[status] = dated + undated

    sections = [
        {"status": status, "label": label, "spools": grouped[status]}
        for status, label, _, _ in _SECTION_CONFIG
    ]

    return render_template(
        "spools/list.html",
        sections=sections,
        section_sorts=section_sorts,
        tasks_by_spool=tasks_by_spool,
        total_count=len(all_spools),
    )


@bp.route("/<int:spool_id>")
def detail_view(spool_id: int):
    db_path = current_app.config["DB_PATH"]
    try:
        spool, tasks = read_spool_with_tasks(db_path, spool_id)
    except SpoolNotFoundError:
        flash(t("flash.spools.not_found"), "error")
        return redirect(url_for("spools.list_view"))

    cost_consumed = None
    if spool.get("price") and spool.get("initial_weight_g") and spool["initial_weight_g"] > 0:
        try:
            price_val = float(spool["price"])
            ratio = min(spool["used_weight_g"] / spool["initial_weight_g"], 1.0)
            cost_consumed = price_val * ratio
        except (TypeError, ValueError):
            pass

    return render_template(
        "spools/detail.html",
        spool=spool,
        tasks=tasks,
        cost_consumed=cost_consumed,
    )


@bp.route("/new", methods=["GET", "POST"])
def new_view():
    db_path = current_app.config["DB_PATH"]
    if request.method == "POST":
        data = _form_to_spool(request.form)
        try:
            create_spool(db_path, data)
            flash(t("flash.spools.added"), "success")
            return redirect(url_for("spools.list_view"))
        except SpoolValidationError as exc:
            flash(str(exc), "error")
    return render_template("spools/form.html", spool=None, action=url_for("spools.new_view"))


@bp.route("/<int:spool_id>/edit", methods=["GET", "POST"])
def edit_view(spool_id: int):
    db_path = current_app.config["DB_PATH"]
    try:
        spool = read_spool(db_path, spool_id)
    except SpoolNotFoundError:
        flash(t("flash.spools.not_found"), "error")
        return redirect(url_for("spools.list_view"))

    if request.method == "POST":
        data = _form_to_spool(request.form)
        try:
            update_spool_data(db_path, spool_id, data)
            flash(t("flash.spools.updated"), "success")
            return redirect(url_for("spools.list_view"))
        except SpoolValidationError as exc:
            flash(str(exc), "error")

    return render_template(
        "spools/form.html",
        spool=spool,
        action=url_for("spools.edit_view", spool_id=spool_id),
    )


@bp.route("/<int:spool_id>/delete", methods=["POST"])
def delete_view(spool_id: int):
    db_path = current_app.config["DB_PATH"]
    try:
        delete_spool_data(db_path, spool_id)
        flash(t("flash.spools.deleted"), "success")
    except SpoolNotFoundError:
        flash(t("flash.spools.not_found"), "error")
    return redirect(url_for("spools.list_view"))


@bp.route("/export/json")
def export_json_view():
    db_path = current_app.config["DB_PATH"]
    data = export_spools_json(db_path)
    return Response(
        data,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=filament_spools.json"},
    )


@bp.route("/export/csv")
def export_csv_view():
    db_path = current_app.config["DB_PATH"]
    data = export_spools_csv(db_path)
    return Response(
        data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=filament_spools.csv"},
    )


@bp.route("/import", methods=["POST"])
def import_view():
    db_path = current_app.config["DB_PATH"]
    file = request.files.get("file")
    if not file or file.filename == "":
        flash(t("flash.spools.no_file"), "error")
        return redirect(url_for("spools.list_view"))

    filename = file.filename.lower()
    try:
        content = file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash(t("flash.spools.encoding_error"), "error")
        return redirect(url_for("spools.list_view"))

    try:
        if filename.endswith(".json"):
            result = import_spools_json(db_path, content)
        elif filename.endswith(".csv"):
            result = import_spools_csv(db_path, content)
        else:
            flash(t("flash.spools.unsupported_format"), "error")
            return redirect(url_for("spools.list_view"))
    except SpoolImportError as exc:
        flash(str(exc), "error")
        return redirect(url_for("spools.list_view"))

    msg = t("flash.spools.import_done",
            imported=result["imported"], skipped=result["skipped"], failed=result["failed"])
    all_errors = list(result.get("errors", []))
    mr = result.get("mappings")
    if mr is not None:
        msg += t("flash.spools.import_mappings",
                 applied=mr["applied"], m_skipped=mr["skipped"], m_failed=mr["failed"])
        all_errors += mr.get("errors", [])
    if all_errors:
        shown = all_errors[:3]
        msg += t("flash.spools.import_errors", errors="；".join(shown))
        if len(all_errors) > 3:
            msg += t("flash.spools.import_more_errors", n=len(all_errors))
    any_ok = result["imported"] > 0 or result["skipped"] > 0 or (
        mr is not None and (mr["applied"] > 0 or mr["skipped"] > 0)
    )
    category = "success" if any_ok else "error"
    flash(msg, category)
    return redirect(url_for("spools.list_view"))


def _form_to_spool(form) -> dict:
    raw_url = form.get("product_url", "").strip()
    product_url = raw_url if raw_url.lower().startswith(("http://", "https://")) else None
    return {
        "material": form.get("material", "").strip() or None,
        "color_name": form.get("color_name", "").strip() or None,
        "color_hex": form.get("color_hex", "").strip() or None,
        "initial_weight_g": form.get("initial_weight_g", "").strip() or None,
        "price": form.get("price", "").strip() or None,
        "purchased_at": form.get("purchased_at", "").strip() or None,
        "product_url": product_url,
        "note": form.get("note", "").strip() or None,
    }

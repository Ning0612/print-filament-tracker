from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for

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
    list_spools,
    read_spool,
    update_spool_data,
)

bp = Blueprint("spools", __name__)


@bp.route("/")
def list_view():
    db_path = current_app.config["DB_PATH"]
    spools = list_spools(db_path)
    return render_template("spools/list.html", spools=spools)


@bp.route("/new", methods=["GET", "POST"])
def new_view():
    db_path = current_app.config["DB_PATH"]
    if request.method == "POST":
        data = _form_to_spool(request.form)
        try:
            create_spool(db_path, data)
            flash("耗材已新增。", "success")
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
        flash("找不到此耗材。", "error")
        return redirect(url_for("spools.list_view"))

    if request.method == "POST":
        data = _form_to_spool(request.form)
        try:
            update_spool_data(db_path, spool_id, data)
            flash("耗材已更新。", "success")
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
        flash("耗材已刪除。", "success")
    except SpoolNotFoundError:
        flash("找不到此耗材。", "error")
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
        flash("請選擇檔案。", "error")
        return redirect(url_for("spools.list_view"))

    filename = file.filename.lower()
    try:
        content = file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("檔案編碼不支援，請確認檔案為 UTF-8 格式。", "error")
        return redirect(url_for("spools.list_view"))

    try:
        if filename.endswith(".json"):
            result = import_spools_json(db_path, content)
        elif filename.endswith(".csv"):
            result = import_spools_csv(db_path, content)
        else:
            flash("不支援的格式，請上傳 .json 或 .csv 檔案。", "error")
            return redirect(url_for("spools.list_view"))
    except SpoolImportError as exc:
        flash(str(exc), "error")
        return redirect(url_for("spools.list_view"))

    msg = f"匯入完成：成功 {result['imported']} 筆，略過 {result['skipped']} 筆（已存在），失敗 {result['failed']} 筆。"
    if result["errors"]:
        shown = result["errors"][:3]
        msg += " 錯誤：" + "；".join(shown)
        if len(result["errors"]) > 3:
            msg += f"...等共 {len(result['errors'])} 個。"
    category = "success" if result["imported"] > 0 or result["skipped"] > 0 else "error"
    flash(msg, category)
    return redirect(url_for("spools.list_view"))


def _form_to_spool(form) -> dict:
    return {
        "material": form.get("material", "").strip() or None,
        "color_name": form.get("color_name", "").strip() or None,
        "color_hex": form.get("color_hex", "").strip() or None,
        "initial_weight_g": form.get("initial_weight_g", "").strip() or None,
        "price": form.get("price", "").strip() or None,
        "purchased_at": form.get("purchased_at", "").strip() or None,
        "product_url": form.get("product_url", "").strip() or None,
        "note": form.get("note", "").strip() or None,
    }

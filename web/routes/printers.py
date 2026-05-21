from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from web.i18n import t
from web.utils import ALLOWED_IMAGE_EXTS, is_valid_image

from src.printer import (
    PrinterNotFoundError,
    PrinterValidationError,
    create_printer,
    delete_printer_data,
    get_device_id_suggestions,
    list_printers_with_stats,
    read_printer,
    set_printer_image,
    update_printer_data,
)

bp = Blueprint("printers", __name__)


def _save_printer_image(covers_dir: Path, printer_id: int, file) -> "str | None":
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return None
    header = file.read(12)
    file.stream.seek(0)
    if not is_valid_image(header):
        return None
    filename = f"p{printer_id}{ext}"
    file.save(covers_dir / filename)
    return f"/covers/{filename}"


def _remove_printer_image(covers_dir: Path, printer_id: int) -> None:
    for ext in ALLOWED_IMAGE_EXTS:
        p = covers_dir / f"p{printer_id}{ext}"
        if p.exists():
            p.unlink()


def _form_to_printer(form) -> dict:
    return {
        "name":         form.get("name", "").strip(),
        "model":        form.get("model", "").strip() or None,
        "device_id":    form.get("device_id", "").strip() or None,
        "purchased_at": form.get("purchased_at", "").strip() or None,
        "note":         form.get("note", "").strip() or None,
    }


@bp.route("/")
def list_view():
    printers = list_printers_with_stats(current_app.config["DB_PATH"])
    return render_template("printers/list.html", printers=printers)


@bp.route("/new", methods=["GET", "POST"])
def new_view():
    db_path = current_app.config["DB_PATH"]
    covers_dir = current_app.config["COVERS_DIR"]
    if request.method == "POST":
        data = _form_to_printer(request.form)
        try:
            printer_id = create_printer(db_path, data)
        except PrinterValidationError as exc:
            flash(str(exc), "error")
            return render_template(
                "printers/form.html",
                printer=None,
                device_id_suggestions=get_device_id_suggestions(db_path),
                action=url_for("printers.new_view"),
            )
        file = request.files.get("image")
        if file and file.filename:
            covers_dir.mkdir(parents=True, exist_ok=True)
            image_url = _save_printer_image(covers_dir, printer_id, file)
            if image_url:
                set_printer_image(db_path, printer_id, image_url)
            else:
                flash(t("flash.printers.image_skipped"), "error")
        flash(t("flash.printers.added"), "success")
        return redirect(url_for("printers.list_view"))
    return render_template(
        "printers/form.html",
        printer=None,
        device_id_suggestions=get_device_id_suggestions(db_path),
        action=url_for("printers.new_view"),
    )


@bp.route("/<int:printer_id>/edit", methods=["GET", "POST"])
def edit_view(printer_id: int):
    db_path = current_app.config["DB_PATH"]
    covers_dir = current_app.config["COVERS_DIR"]
    try:
        printer = read_printer(db_path, printer_id)
    except PrinterNotFoundError:
        flash(t("flash.printers.not_found"), "error")
        return redirect(url_for("printers.list_view"))
    if request.method == "POST":
        data = _form_to_printer(request.form)
        file = request.files.get("image")
        clear_image = request.form.get("clear_image") == "1"
        if file and file.filename:
            ext = Path(file.filename).suffix.lower()
            if ext not in ALLOWED_IMAGE_EXTS:
                flash(t("flash.printers.image_not_updated"), "error")
                new_image_url = printer.get("image_url")
                file = None
            else:
                header = file.read(12)
                file.stream.seek(0)
                if not is_valid_image(header):
                    flash(t("flash.printers.image_not_updated"), "error")
                    new_image_url = printer.get("image_url")
                    file = None
                else:
                    new_image_url = f"/covers/p{printer_id}{ext}"
        elif clear_image:
            new_image_url = None
        else:
            new_image_url = printer.get("image_url")
        data["image_url"] = new_image_url
        try:
            update_printer_data(db_path, printer_id, data)
        except (PrinterValidationError, PrinterNotFoundError) as exc:
            flash(str(exc), "error")
            return render_template(
                "printers/form.html",
                printer=printer,
                device_id_suggestions=get_device_id_suggestions(db_path),
                action=url_for("printers.edit_view", printer_id=printer_id),
            )
        if file and file.filename and new_image_url:
            covers_dir.mkdir(parents=True, exist_ok=True)
            _remove_printer_image(covers_dir, printer_id)
            file.save(covers_dir / f"p{printer_id}{Path(file.filename).suffix.lower()}")
        elif clear_image:
            _remove_printer_image(covers_dir, printer_id)
        flash(t("flash.printers.updated"), "success")
        return redirect(url_for("printers.list_view"))
    return render_template(
        "printers/form.html",
        printer=printer,
        device_id_suggestions=get_device_id_suggestions(db_path),
        action=url_for("printers.edit_view", printer_id=printer_id),
    )


@bp.route("/<int:printer_id>/delete", methods=["POST"])
def delete_view(printer_id: int):
    db_path = current_app.config["DB_PATH"]
    covers_dir = current_app.config["COVERS_DIR"]
    try:
        delete_printer_data(db_path, printer_id)
        _remove_printer_image(covers_dir, printer_id)
        flash(t("flash.printers.deleted"), "success")
    except PrinterNotFoundError:
        flash(t("flash.printers.not_found"), "error")
    return redirect(url_for("printers.list_view"))

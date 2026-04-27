from flask import Blueprint, make_response, redirect, request, session

from web.i18n import _discover_langs

bp = Blueprint("lang", __name__)


@bp.route("/set-lang", methods=["POST"])
def set_lang():
    lang = request.form.get("lang", "").strip()
    if lang in _discover_langs():
        session["lang"] = lang
    redirect_to = request.form.get("next") or request.referrer or "/"
    if request.headers.get("HX-Request"):
        resp = make_response("")
        resp.headers["HX-Redirect"] = redirect_to
        return resp
    return redirect(redirect_to)

import requests
from flask import current_app, flash, make_response, render_template, request, session, url_for

from web.i18n import t
from . import bp

_GLOBAL_BASE = "https://api.bambulab.com"
_CHINA_BASE = "https://api.bambulab.cn"
_LOGIN_PATH = "/v1/user-service/user/login"
_SEND_CODE_PATH = "/v1/user-service/user/sendemail/code"
_TFA_PATH = "/api/sign-in/tfa"
_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "FilamentLedger/1.0 (community; unofficial Bambu Lab integration)",
}
_TIMEOUT = 20


def _api_post(
    base_url: str, path: str, payload: dict, *, allow_empty_body: bool = False
) -> "tuple[dict | None, str | None]":
    """POST to Bambu API and return (data, error).

    Args:
        allow_empty_body: If True, an HTTP 200 with an empty body is treated as
            success and returns ({}, None).  Use only for endpoints whose contract
            allows a non-JSON 200 response (e.g. /sendemail/code).
    """
    try:
        resp = requests.post(base_url + path, json=payload, headers=_HEADERS, timeout=_TIMEOUT)
    except requests.Timeout:
        return None, f"連線逾時（{_TIMEOUT} 秒），請確認網路連線。"
    except requests.RequestException as exc:
        return None, f"網路錯誤：{exc}"
    if not resp.ok:
        return None, f"伺服器回傳 HTTP {resp.status_code}：{resp.text[:200]}"
    try:
        return resp.json(), None
    except ValueError:
        if allow_empty_body and not resp.content.strip():
            return {}, None
        body_preview = resp.text[:200] if resp.text else "(空)"
        return None, f"伺服器回傳非 JSON 格式：{body_preview}"


def _apply_token(token: str, region: str) -> None:
    from src.db import get_connection, set_app_config
    try:
        with get_connection(current_app.config["DB_PATH"]) as conn:
            set_app_config(conn, "bambu_access_token", token)
            set_app_config(conn, "bambu_region", region)
    except Exception as exc:
        current_app.logger.warning("無法儲存 token 到 DB：%s", exc)
    current_app.config["BAMBU_TOKEN"] = token
    current_app.config["BAMBU_REGION"] = region


def _mask_token(token: str) -> str:
    if not token:
        return "(未設定)"
    if len(token) <= 8:
        return "***"
    return token[:4] + "..." + token[-4:]


@bp.route("/login/form")
def login_form():
    return render_template("settings/_login_form.html")


@bp.route("/login/step1", methods=["POST"])
def login_step1():
    email = request.form.get("email", "").strip()
    # Do NOT strip password — leading/trailing spaces may be intentional
    password = request.form.get("password", "")
    region = request.form.get("region", "global")
    if region not in ("global", "china"):
        region = "global"

    if not email or not password:
        return render_template("settings/_login_error.html", error=t("flash.settings.email_password_required"))

    base_url = _GLOBAL_BASE if region == "global" else _CHINA_BASE
    data, err = _api_post(base_url, _LOGIN_PATH, {
        "account": email, "password": password, "apiError": "",
    })
    if err:
        return render_template("settings/_login_error.html", error=err)

    login_type = data.get("loginType", "")
    token = data.get("accessToken")

    if token and not login_type:
        _apply_token(token, region)
        flash(t("flash.settings.login_success"), "success")
        resp = make_response("")
        resp.headers["HX-Redirect"] = url_for("settings.index")
        return resp

    if login_type == "verifyCode":
        # Bambu Lab's /sendemail/code returns HTTP 200 with an empty body on success;
        # allow_empty_body=True prevents a false-positive "非 JSON 格式" error.
        _, send_err = _api_post(base_url, _SEND_CODE_PATH, {
            "email": email, "type": "codeLogin",
        }, allow_empty_body=True)
        if send_err:
            return render_template("settings/_login_error.html",
                                   error=t("flash.settings.send_code_failed", err=send_err))
        session["bambu_login"] = {
            "email": email, "region": region,
            "base_url": base_url, "type": "verifyCode",
        }
        return render_template("settings/_login_step2.html",
                               login_type="verifyCode", email=email)

    if login_type == "tfa":
        session["bambu_login"] = {
            "email": email, "region": region,
            "base_url": base_url, "type": "tfa",
            "tfa_key": data.get("tfaKey", ""),
        }
        return render_template("settings/_login_step2.html",
                               login_type="tfa", email=email)

    return render_template("settings/_login_error.html",
                           error=t("flash.settings.unexpected_response", data=data))


@bp.route("/login/step2", methods=["POST"])
def login_step2():
    info = session.get("bambu_login")
    if not info:
        return render_template("settings/_login_error.html",
                               error=t("flash.settings.session_expired"))

    code = request.form.get("code", "").strip()
    if not code:
        return render_template("settings/_login_error.html", error=t("flash.settings.code_empty"))

    base_url = info["base_url"]
    region = info["region"]

    if info["type"] == "verifyCode":
        data, err = _api_post(base_url, _LOGIN_PATH, {
            "account": info["email"], "code": code,
        })
    else:
        data, err = _api_post(base_url, _TFA_PATH, {
            "tfaKey": info.get("tfa_key", ""), "tfaCode": code,
        })

    if err:
        return render_template("settings/_login_error.html", error=err)

    token = data.get("accessToken") if data else None
    if not token:
        return render_template("settings/_login_error.html",
                               error=t("flash.settings.login_failed", data=data))

    session.pop("bambu_login", None)
    _apply_token(token, region)
    flash(t("flash.settings.login_success"), "success")
    resp = make_response("")
    resp.headers["HX-Redirect"] = url_for("settings.index")
    return resp

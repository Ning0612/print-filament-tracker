"""
Bambu Lab token 取得工具。
使用使用者自己的帳號登入，取得 access token 並寫入 .env。
"""

import getpass
import json
import os
import sys
from pathlib import Path

import requests

GLOBAL_BASE = "https://api.bambulab.com"
CHINA_BASE = "https://api.bambulab.cn"

LOGIN_PATH = "/v1/user-service/user/login"
SEND_CODE_PATH = "/v1/user-service/user/sendemail/code"
TFA_PATH = "/api/sign-in/tfa"

TIMEOUT = 20

_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "FilamentLedger/1.0 (community; unofficial Bambu Lab integration)",
}


def _post(base_url: str, path: str, payload: dict) -> dict:
    url = base_url + path
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_HEADERS,
            timeout=TIMEOUT,
        )
    except requests.Timeout:
        print(f"[ERROR] 連線逾時（{TIMEOUT} 秒）。請確認網路連線。")
        sys.exit(1)
    except requests.RequestException as exc:
        print(f"[ERROR] 網路錯誤：{exc}")
        sys.exit(1)

    if not resp.ok:
        print(f"[ERROR] 伺服器回傳 HTTP {resp.status_code}：{resp.text[:500]}")
        sys.exit(1)

    body = resp.text.strip()
    if not body:
        return {}

    try:
        data = resp.json()
    except ValueError:
        print(f"[ERROR] 伺服器回傳非 JSON（HTTP {resp.status_code}）：\n{body[:500]}")
        sys.exit(1)

    if not isinstance(data, dict):
        print(f"[ERROR] 伺服器回傳格式非預期（非 JSON 物件）：{str(data)[:200]}")
        sys.exit(1)

    return data


def _initial_login(base_url: str, email: str, password: str) -> dict:
    return _post(base_url, LOGIN_PATH, {
        "account": email,
        "password": password,
        "apiError": "",
    })


def _send_verify_code(base_url: str, email: str) -> None:
    result = _post(base_url, SEND_CODE_PATH, {
        "email": email,
        "type": "codeLogin",
    })
    if not result or result.get("message") == "success":
        print(f"[INFO] 驗證碼已發送至 {email}，請查收信箱。")
    else:
        print(f"[WARN] 驗證碼發送回應：{result}")


def _login_with_code(base_url: str, email: str, code: str) -> dict:
    return _post(base_url, LOGIN_PATH, {
        "account": email,
        "code": code.strip(),
    })


def _login_with_tfa(base_url: str, tfa_key: str, tfa_code: str) -> dict:
    return _post(base_url, TFA_PATH, {
        "tfaKey": tfa_key,
        "tfaCode": tfa_code.strip(),
    })


def _write_env(token: str, region: str, env_path: Path) -> None:
    lines = []
    has_token = False
    has_region = False

    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.lstrip()
            if (
                stripped.startswith("BAMBU_ACCESS_TOKEN=")
                or stripped.startswith("export BAMBU_ACCESS_TOKEN=")
            ):
                lines.append(f"BAMBU_ACCESS_TOKEN={token}")
                has_token = True
            elif (
                stripped.startswith("BAMBU_REGION=")
                or stripped.startswith("export BAMBU_REGION=")
            ):
                lines.append(f"BAMBU_REGION={region}")
                has_region = True
            else:
                lines.append(line)

    if not has_token:
        lines.append(f"BAMBU_ACCESS_TOKEN={token}")
    if not has_region:
        lines.append(f"BAMBU_REGION={region}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] Token 已寫入 {env_path}")


def main() -> None:
    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"

    print("=== Bambu Lab Token 取得工具 ===")
    print("僅讀取您自己帳號的資料，不寫入或修改雲端設定。\n")

    region = input("區域（global / china）[global]: ").strip().lower() or "global"
    if region not in ("global", "china"):
        print("[ERROR] 無效區域，請輸入 'global' 或 'china'。")
        sys.exit(1)

    base_url = GLOBAL_BASE if region == "global" else CHINA_BASE

    email = input("Bambu Lab 帳號（Email）：").strip()
    if not email:
        print("[ERROR] Email 不得為空。")
        sys.exit(1)

    password = getpass.getpass("密碼（輸入時不顯示）：")
    if not password:
        print("[ERROR] 密碼不得為空。")
        sys.exit(1)

    print("\n[INFO] 正在登入...")
    result = _initial_login(base_url, email, password)

    login_type = result.get("loginType", "")
    token = result.get("accessToken")

    if token and not login_type:
        print("[OK] 登入成功。")

    elif login_type == "verifyCode":
        print("[INFO] 帳號需要電子郵件驗證碼。")
        _send_verify_code(base_url, email)
        code = input("請輸入收到的驗證碼：").strip()
        result = _login_with_code(base_url, email, code)
        token = result.get("accessToken")
        if not token:
            print(f"[ERROR] 驗證碼登入失敗：{result}")
            sys.exit(1)
        print("[OK] 驗證碼登入成功。")

    elif login_type == "tfa":
        tfa_key = result.get("tfaKey", "")
        print("[INFO] 帳號已啟用兩步驟驗證（2FA）。")
        tfa_code = input("請輸入驗證器 App 的 6 位數驗證碼：").strip()
        result = _login_with_tfa(base_url, tfa_key, tfa_code)
        token = result.get("accessToken")
        if not token:
            print(f"[ERROR] 2FA 登入失敗：{result}")
            sys.exit(1)
        print("[OK] 2FA 登入成功。")

    else:
        print(f"[ERROR] 未預期的登入回應：{json.dumps(result, ensure_ascii=False)}")
        sys.exit(1)

    print(f"\nToken（前 16 碼預覽）：{token[:16]}...")
    print(f"\n強烈建議：將 token 寫入 {env_path} 而非顯示於終端機。")

    answer = input(f"是否寫入 {env_path}？（Y/n）：").strip().lower()
    if answer != "n":
        _write_env(token, region, env_path)
    else:
        print("\n[WARNING] Token 即將顯示於終端機。")
        print("[WARNING] 請在複製後立即關閉此終端機視窗，以防 token 殘留在螢幕或歷史紀錄中。")
        confirm = input("確認顯示完整 token？（yes/N）：").strip().lower()
        if confirm == "yes":
            print("\n--- TOKEN START ---")
            print(token)
            print("--- TOKEN END ---")
            print("\n請複製上方 token 並手動填入 .env：")
            print("  BAMBU_ACCESS_TOKEN=<貼上 token>")
        else:
            print("已取消。請重新執行腳本並選擇寫入 .env。")


if __name__ == "__main__":
    main()

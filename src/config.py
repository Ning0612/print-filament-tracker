from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os

from src.paths import get_base_dir, resolve_output_dir


_REGION_BASE_URLS = {
    "global": "https://api.bambulab.com",
    "china": "https://api.bambulab.cn",
}


class ConfigError(Exception):
    pass


@dataclass
class AppConfig:
    access_token: str
    region: str
    api_base: str
    output_dir: Path
    request_timeout: int


def load_config(env_path: Path | None = None) -> AppConfig:
    target = env_path or (get_base_dir() / ".env")
    load_dotenv(dotenv_path=target, override=False)

    token = os.getenv("BAMBU_ACCESS_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "[ERROR] BAMBU_ACCESS_TOKEN 未設定。\n"
            "請複製 .env.example 為 .env，填入您的 Bambu Cloud token：\n"
            "  BAMBU_ACCESS_TOKEN=your_token_here"
        )

    region = os.getenv("BAMBU_REGION", "global").strip().lower()
    if region not in _REGION_BASE_URLS:
        raise ConfigError(
            f"[ERROR] BAMBU_REGION 設定無效：'{region}'。"
            " 有效值為 'global' 或 'china'。"
        )

    api_base = (
        os.getenv("BAMBU_API_BASE", "").strip()
        or _REGION_BASE_URLS[region]
    ).rstrip("/")

    # resolve_output_dir 確保相對路徑解析至使用者資料根，而非 process CWD
    output_dir = resolve_output_dir(os.getenv("BAMBU_OUTPUT_DIR", "").strip() or None)

    return AppConfig(
        access_token=token,
        region=region,
        api_base=api_base,
        output_dir=output_dir,
        request_timeout=20,
    )

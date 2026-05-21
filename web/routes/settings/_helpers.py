from flask import current_app


def _save_app_config(key: str, value: str) -> None:
    from src.db import get_connection, set_app_config
    with get_connection(current_app.config["DB_PATH"]) as conn:
        set_app_config(conn, key, value)

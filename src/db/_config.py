import sqlite3


def get_app_config(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_app_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_config (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )

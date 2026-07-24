"""Integration tests for the task detail route (web/routes/tasks.py).

固化兩件事：髒 raw_json 不得讓詳情頁 500，以及手動任務的操作按鈕不因
MakerWorld 外連的條件改寫而消失。單元測試涵蓋 helper 本身，這裡涵蓋
「route 有把 makerworld_url 傳給模板」這條接線——它斷掉時 helper 測試不會失敗。
"""

import json
from pathlib import Path

import pytest

from src.db import get_connection
from web.app import create_app


@pytest.fixture
def client(db_path: Path):
    app = create_app(db_path=db_path)
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app.test_client()


def _insert_task(db_path: Path, *, raw_json: str | None, is_manual: int = 0) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO print_task
              (external_id, print_name, started_at, ended_at, raw_json, is_manual)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                -abs(hash(raw_json or "manual")) % 10**9,
                "測試任務",
                "2026-07-01T00:00:00Z",
                "2026-07-01T01:00:00Z",
                raw_json,
                is_manual,
            ),
        )
        conn.commit()
        return cur.lastrowid


class TestMakerWorldLinkRendering:
    def test_makerworld_task_shows_link(self, client, db_path):
        tid = _insert_task(db_path, raw_json=json.dumps({"designId": 1225459}))
        html = client.get(f"/tasks/{tid}").get_data(as_text=True)
        assert "https://makerworld.com/models/1225459" in html
        assert 'rel="noopener noreferrer"' in html
        assert 'target="_blank"' in html

    def test_self_made_task_has_no_link(self, client, db_path):
        tid = _insert_task(db_path, raw_json=json.dumps({"designId": 0}))
        html = client.get(f"/tasks/{tid}").get_data(as_text=True)
        assert "makerworld.com" not in html


class TestMalformedRawJsonDoesNotCrash:
    @pytest.mark.parametrize(
        "raw",
        [
            "null",
            "[1, 2, 3]",
            '"a string"',
            "123",
            "not json at all",
            '{"designId": Infinity}',
            '{"designId": NaN}',
            '{"designId": 1.9}',
            '{"designId": true}',
            '{"designId": "1225459"}',
        ],
    )
    def test_dirty_raw_json_returns_200_without_link(self, client, db_path, raw):
        tid = _insert_task(db_path, raw_json=raw)
        resp = client.get(f"/tasks/{tid}")
        assert resp.status_code == 200
        assert "makerworld.com" not in resp.get_data(as_text=True)


class TestManualTaskActionsIntact:
    def test_manual_task_keeps_edit_and_delete(self, client, db_path):
        """外連的條件改寫不得讓手動任務的操作區塊消失。"""
        tid = _insert_task(db_path, raw_json=None, is_manual=1)
        html = client.get(f"/tasks/{tid}").get_data(as_text=True)
        assert "page-actions" in html
        assert f"/tasks/{tid}/edit" in html
        assert f"/tasks/{tid}/delete" in html
        assert "makerworld.com" not in html

    def test_manual_task_with_stale_raw_json_shows_no_link(self, client, db_path):
        tid = _insert_task(db_path, raw_json=json.dumps({"designId": 999}), is_manual=1)
        html = client.get(f"/tasks/{tid}").get_data(as_text=True)
        assert "makerworld.com" not in html
        assert f"/tasks/{tid}/edit" in html

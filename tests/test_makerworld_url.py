"""Unit tests for the MakerWorld external link helper (web/routes/tasks.py).

raw_json 原封存放 Bambu Cloud 的回應，內容不受本程式控制，因此這裡的重點是
髒資料不得讓任務詳情頁 500，也不得產生指向錯誤模型的連結。
"""

import json

from web.routes.tasks import _makerworld_url


def _task(raw, **extra):
    """組出 get_task_with_filaments() 形狀的最小 task dict。"""
    return {"is_manual": 0, "raw_json": raw, **extra}


class TestMakerWorldSource:
    def test_positive_design_id(self):
        task = _task(json.dumps({"designId": 1225459}))
        assert _makerworld_url(task) == "https://makerworld.com/models/1225459"

    def test_design_id_zero_is_self_made(self):
        assert _makerworld_url(_task(json.dumps({"designId": 0}))) is None

    def test_negative_design_id(self):
        assert _makerworld_url(_task(json.dumps({"designId": -5}))) is None

    def test_missing_design_id_key(self):
        assert _makerworld_url(_task(json.dumps({"title": "x"}))) is None


class TestManualTask:
    def test_manual_task_without_raw_json(self):
        assert _makerworld_url(_task(None, is_manual=1)) is None

    def test_manual_task_is_never_linked_even_with_raw_json(self):
        """手動任務即使因舊資料帶有 raw_json，也不得顯示連結。"""
        task = _task(json.dumps({"designId": 999}), is_manual=1)
        assert _makerworld_url(task) is None


class TestMalformedRawJson:
    def test_none(self):
        assert _makerworld_url(_task(None)) is None

    def test_empty_string(self):
        assert _makerworld_url(_task("")) is None

    def test_not_json(self):
        assert _makerworld_url(_task("not json at all")) is None

    def test_json_null(self):
        """json.loads('null') 回 None，直接 .get() 會 AttributeError。"""
        assert _makerworld_url(_task("null")) is None

    def test_json_array(self):
        assert _makerworld_url(_task("[1, 2, 3]")) is None

    def test_json_string(self):
        assert _makerworld_url(_task('"just a string"')) is None

    def test_json_number(self):
        assert _makerworld_url(_task("123")) is None

    def test_missing_raw_json_key(self):
        assert _makerworld_url({"is_manual": 0}) is None


class TestNonIntegerDesignId:
    def test_float_is_rejected_not_truncated(self):
        """int(1.9) 會截斷成 1，指向錯誤的模型。"""
        assert _makerworld_url(_task(json.dumps({"designId": 1.9}))) is None

    def test_infinity_does_not_raise(self):
        """int(float('inf')) 會拋 OverflowError，必須先被型別檢查擋下。"""
        assert _makerworld_url(_task('{"designId": Infinity}')) is None

    def test_nan_does_not_raise(self):
        assert _makerworld_url(_task('{"designId": NaN}')) is None

    def test_bool_true_is_not_model_id_one(self):
        """bool 是 int 子類，未排除的話 True 會變成 /models/1。"""
        assert _makerworld_url(_task(json.dumps({"designId": True}))) is None

    def test_numeric_string_is_rejected(self):
        """實測資料 designId 一律為 int；字串形態視為異常，不猜測。"""
        assert _makerworld_url(_task(json.dumps({"designId": "1225459"}))) is None

    def test_null_design_id(self):
        assert _makerworld_url(_task(json.dumps({"designId": None}))) is None

    def test_nested_object_design_id(self):
        assert _makerworld_url(_task(json.dumps({"designId": {"id": 1}}))) is None


class TestLargeDesignId:
    def test_very_large_id_is_allowed(self):
        """MakerWorld ID 會隨時間增長，不設人為上限以免未來誤擋真實 ID。"""
        task = _task(json.dumps({"designId": 999999999999}))
        assert _makerworld_url(task) == "https://makerworld.com/models/999999999999"

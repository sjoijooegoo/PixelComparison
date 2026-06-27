"""筛选框可见画质配置(filter_shading_qualities)的存取与一致性校验。"""


def _put(client, patch):
    r = client.put("/api/settings", json=patch)
    assert r.status_code == 200, r.text
    return r.json()


def test_default_is_all_six(client):
    s = client.get("/api/settings").json()
    assert s["filter_shading_qualities"] == [5, 4, 3, 2, 1, 0]


def test_subset_stored_sorted_desc(client):
    s = _put(client, {"filter_shading_qualities": [3, 5]})
    assert s["filter_shading_qualities"] == [5, 3]


def test_invalid_values_dropped_and_deduped(client):
    # 9 非法被丢、重复去掉、降序
    s = _put(client, {"filter_shading_qualities": [5, 9, 3, 3, -2]})
    assert s["filter_shading_qualities"] == [5, 3]


def test_empty_list_keeps_previous(client):
    _put(client, {"filter_shading_qualities": [5, 3]})
    s = _put(client, {"filter_shading_qualities": []})
    assert s["filter_shading_qualities"] == [5, 3]   # 空集忽略,保留原值


def test_all_invalid_keeps_previous(client):
    _put(client, {"filter_shading_qualities": [5, 1]})
    s = _put(client, {"filter_shading_qualities": [7, 8]})
    assert s["filter_shading_qualities"] == [5, 1]


def test_default_quality_falls_back_when_not_visible(client):
    # 默认画质=4,但可见集合不含 4 -> 默认回退为 -1(全部画质)
    s = _put(client, {"default_shading_quality": 4, "filter_shading_qualities": [5, 3]})
    assert s["default_shading_quality"] == -1
    assert s["filter_shading_qualities"] == [5, 3]


def test_default_quality_kept_when_visible(client):
    s = _put(client, {"default_shading_quality": 5, "filter_shading_qualities": [5, 3]})
    assert s["default_shading_quality"] == 5


def test_default_quality_minus_one_always_ok(client):
    s = _put(client, {"default_shading_quality": -1, "filter_shading_qualities": [5, 3]})
    assert s["default_shading_quality"] == -1

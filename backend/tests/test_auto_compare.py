def _batch(client, bid, captured_at, scene="S", platform="Windows", quality=4):
    r = client.post("/api/batches", json={
        "id": bid, "scene_id": scene, "p4_version": 1, "platform": platform,
        "shading_quality": quality, "captured_at": captured_at,
    })
    assert r.status_code == 201, r.text


def _shot(client, bid, png_bytes):
    return client.post(
        f"/api/batches/{bid}/screenshots",
        data={"scene_name": "shot_01"},
        files={"file": ("shot_01.png", png_bytes(), "image/png")},
    )


def test_auto_compare_no_match(client, png_bytes):
    _batch(client, "solo", "2024-01-01T10:00:00")
    assert _shot(client, "solo", png_bytes).status_code == 201
    r = client.post("/api/batches/solo/auto-compare")
    assert r.status_code == 202
    assert r.json()["matched"] is False


def test_auto_compare_picks_latest_earlier_same_attrs(client, png_bytes):
    _batch(client, "old", "2024-01-01T10:00:00")
    _batch(client, "mid", "2024-02-01T10:00:00")
    _batch(client, "cur", "2024-03-01T10:00:00")
    for bid in ("old", "mid", "cur"):
        assert _shot(client, bid, png_bytes).status_code == 201

    r = client.post("/api/batches/cur/auto-compare")
    assert r.status_code == 202
    body = r.json()
    assert body["matched"] is True
    assert body["ref_batch_id"] == "mid"  # 早于 cur 的最新一个


def test_auto_compare_ignores_other_platform_and_quality(client, png_bytes):
    _batch(client, "base", "2024-01-01T10:00:00", platform="Windows", quality=4)
    assert _shot(client, "base", png_bytes).status_code == 201
    # 平台不同 -> 不匹配
    _batch(client, "cur_ios", "2024-02-01T10:00:00", platform="iOS", quality=4)
    assert _shot(client, "cur_ios", png_bytes).status_code == 201
    assert client.post("/api/batches/cur_ios/auto-compare").json()["matched"] is False
    # 画质不同 -> 不匹配
    _batch(client, "cur_q3", "2024-02-02T10:00:00", platform="Windows", quality=3)
    assert _shot(client, "cur_q3", png_bytes).status_code == 201
    assert client.post("/api/batches/cur_q3/auto-compare").json()["matched"] is False


def test_auto_compare_prefers_earlier_p4_when_time_equal(client, png_bytes):
    """复现真实场景:同场景同画质、created_at 完全相同(--time 固定)、P4 不同。
    应按 P4 版本配对,而不是因时间相同而全部 matched=False。"""
    same = "2026-06-29T09:17:00"
    for bid, p4 in (("p100", 100), ("p200", 200), ("p150", 150)):
        r = client.post("/api/batches", json={
            "id": bid, "scene_id": "S", "platform": "Windows",
            "shading_quality": 4, "p4_version": p4, "captured_at": same})
        assert r.status_code == 201, r.text
        assert _shot(client, bid, png_bytes).status_code == 201

    # p200 → 应匹配最接近的更早版本 p150(而非更老的 p100),尽管三者 created_at 相同
    r = client.post("/api/batches/p200/auto-compare")
    assert r.json()["matched"] is True
    assert r.json()["ref_batch_id"] == "p150"
    # p100 是最早版本 → 无更早 → 跳过
    assert client.post("/api/batches/p100/auto-compare").json()["matched"] is False


def test_auto_compare_treats_null_quality_as_extreme(client, png_bytes):
    # 旧数据无画质 -> 视为 4(极致),应能与显式 quality=4 的批次互相匹配
    client.post("/api/batches", json={
        "id": "legacy", "scene_id": "S", "p4_version": 1, "platform": "Windows",
        "captured_at": "2024-01-01T10:00:00"})  # 不带 shading_quality
    _batch(client, "newq4", "2024-02-01T10:00:00", platform="Windows", quality=4)
    assert _shot(client, "legacy", png_bytes).status_code == 201
    assert _shot(client, "newq4", png_bytes).status_code == 201
    r = client.post("/api/batches/newq4/auto-compare")
    assert r.json()["matched"] is True
    assert r.json()["ref_batch_id"] == "legacy"


def test_running_comparison_does_not_hold_sqlite_write_lock(
    client, png_bytes, monkeypatch,
):
    """像素计算可以很慢，但期间必须允许新的上报批次建档。"""
    import threading

    import app.service as service

    compare_started = threading.Event()
    allow_compare_to_finish = threading.Event()

    def blocked_compare(*_args, **_kwargs):
        compare_started.set()
        assert allow_compare_to_finish.wait(timeout=10)
        return {"diff_pct": 0.0}

    monkeypatch.setattr(service, "compare_images", blocked_compare)
    _batch(client, "lock-old", "2024-01-01T10:00:00")
    _batch(client, "lock-new", "2024-02-01T10:00:00")
    assert _shot(client, "lock-old", png_bytes).status_code == 201
    assert _shot(client, "lock-new", png_bytes).status_code == 201

    started = client.post("/api/comparisons", json={
        "batch_id": "lock-new", "ref_batch_id": "lock-old",
    })
    assert started.status_code == 202
    assert compare_started.wait(timeout=2)
    try:
        created = client.post("/api/batches", json={
            "id": "during-compare", "scene_id": "OtherScene",
            "platform": "Windows", "shading_quality": 4,
        })
        assert created.status_code == 201, created.text
    finally:
        allow_compare_to_finish.set()

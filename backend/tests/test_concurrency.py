"""并发 / 多人同时使用:批次上报、对比发起、混合读写的正确性与稳健性。

用 TestClient + 线程池压出真实并发(FastAPI 同步端点在 anyio 线程池执行)。
断言只盯正确性(无 5xx、数据一致、全部完成),耗时仅打印参考。
"""
import statistics
import time
from concurrent.futures import ThreadPoolExecutor


# ---- 小工具 ----

def _batch(client, bid=None, scene="S", overwrite=False):
    body = {"scene_id": scene, "p4_version": 1, "platform": "Windows", "overwrite": overwrite}
    if bid is not None:
        body["id"] = bid
    return client.post("/api/batches", json=body)


def _upload(client, bid, name, png):
    return client.post(f"/api/batches/{bid}/screenshots",
                       data={"scene_name": name},
                       files={"file": (f"{name}.png", png, "image/png")})


def _await_compare(client, resp_json, tries=150):
    """对比响应 -> 完成后的 comparison id;若任务已被淘汰(404)返回 None。"""
    if resp_json.get("status") == "done":
        return resp_json["comparison"]["id"]
    tid = resp_json["task_id"]
    for _ in range(tries):
        r = client.get(f"/api/comparisons/tasks/{tid}")
        if r.status_code == 404:
            return None   # 该对比在并发淘汰中被清掉(上限压力下可接受)
        t = r.json()
        if t["status"] == "done":
            return t["comparison"]["id"]
        assert t["status"] != "error", t
        time.sleep(0.1)
    raise AssertionError("compare timeout")


def _run(fn, n, workers=None):
    """并发跑 fn(i) i in [0,n);返回结果列表(按完成顺序无关,收集全部)。"""
    with ThreadPoolExecutor(max_workers=workers or n) as ex:
        return [f.result() for f in [ex.submit(fn, i) for i in range(n)]]


def _timed(call):
    """执行一个无参调用,返回 (结果, 毫秒耗时)。"""
    t0 = time.perf_counter()
    r = call()
    return r, (time.perf_counter() - t0) * 1000


def _stats(name, ms):
    ms = sorted(ms)
    p = lambda q: ms[min(len(ms) - 1, int(len(ms) * q))]
    print(f"[{name}] n={len(ms)} p50={p(.5):.0f}ms p95={p(.95):.0f}ms max={ms[-1]:.0f}ms")
    return ms[-1]


def _no_5xx(codes):
    bad = [c for c in codes if c is not None and c >= 500]
    assert not bad, f"出现 5xx: {bad}"


# ---- 1. 并发建批次(自增号):无重复 ----

def test_concurrent_autoid_batches(client):
    N = 12
    res = _run(lambda i: _timed(lambda: _batch(client)), N)
    codes = [r.status_code for r, _ in res]
    _no_5xx(codes)
    assert all(c == 201 for c in codes), codes
    ids = [r.json()["id"] for r, _ in res]
    assert len(set(ids)) == N, f"批次号重复: {sorted(ids)}"
    assert client.get("/api/batches", params={"page_size": 100}).json()["total"] == N
    _stats("autoid_batches", [ms for _, ms in res])


# ---- 2. 并发同号冲突:恰好一个赢 ----

def test_concurrent_same_id_conflict(client):
    N = 8
    codes = _run(lambda i: _batch(client, bid="dup").status_code, N)
    _no_5xx(codes)
    assert codes.count(201) == 1, codes
    assert codes.count(409) == N - 1, codes
    assert client.get("/api/batches", params={"q": "dup"}).json()["total"] == 1


# ---- 3. 并发覆盖同号:最终一致、无 5xx ----

def test_concurrent_overwrite_same_id(client, png_bytes):
    assert _batch(client, bid="x1").status_code == 201
    assert _upload(client, "x1", "shot", png_bytes()).status_code == 201
    codes = _run(lambda i: _batch(client, bid="x1", overwrite=True).status_code, 6)
    _no_5xx(codes)
    # 覆盖串行化:每次都成功重建(201)
    assert all(c == 201 for c in codes), codes
    assert client.get("/api/batches", params={"q": "x1"}).json()["total"] == 1
    assert client.get("/api/batches/x1/screenshots").status_code == 200


# ---- 4. 并发传图(不同检查点):全部入库 ----

def test_concurrent_upload_distinct(client, png_bytes):
    assert _batch(client, bid="b").status_code == 201
    N = 16
    res = _run(lambda i: _timed(lambda: _upload(client, "b", f"shot_{i:02d}", png_bytes())), N)
    codes = [r.status_code for r, _ in res]
    _no_5xx(codes)
    assert all(c == 201 for c in codes), codes
    assert client.get("/api/batches/b/screenshots").json()["total"] == N
    _stats("upload_distinct", [ms for _, ms in res])


# ---- 5. 并发传图(同名):恰好一张 ----

def test_concurrent_upload_same_name(client, png_bytes):
    assert _batch(client, bid="b").status_code == 201
    N = 8
    codes = _run(lambda i: _upload(client, "b", "same", png_bytes()).status_code, N)
    _no_5xx(codes)
    assert codes.count(201) == 1, codes
    assert codes.count(409) == N - 1, codes
    assert client.get("/api/batches/b/screenshots").json()["total"] == 1


# ---- 6. 并发对比·同一对:只算一次 ----

def test_concurrent_same_pair_dedup(client, png_bytes):
    for bid, col in (("A", (10, 10, 10)), ("B", (200, 10, 10))):
        assert _batch(client, bid=bid).status_code == 201
        assert _upload(client, bid, "shot", png_bytes(col)).status_code == 201

    def fire(_):
        r = client.post("/api/comparisons", json={"batch_id": "A", "ref_batch_id": "B"})
        return r.status_code, r.json()

    res = _run(fire, 8)
    _no_5xx([c for c, _ in res])
    cids = {_await_compare(client, body) for _, body in res}
    assert len(cids) == 1, f"同一对产生了多条对比: {cids}"
    assert client.get("/api/comparisons").json()["total"] == 1


# ---- 7. 并发对比·不同对 + 淘汰上限 ----

def test_concurrent_distinct_pairs_cap(client, png_bytes, monkeypatch):
    import app.main
    import app.db
    monkeypatch.setattr(app.main, "_MAX_COMPARISONS", 5)
    ids = [str(i) for i in range(7)]
    for bid in ids:
        assert _batch(client, bid=bid).status_code == 201
        col = (int(bid) * 35 % 255, 20, 20)
        assert _upload(client, bid, "shot", png_bytes(col)).status_code == 201

    def fire(i):
        # 6 对不同的无方向对:(1,0),(2,0)...(6,0)
        r = client.post("/api/comparisons", json={"batch_id": ids[i + 1], "ref_batch_id": ids[0]})
        return r.status_code, r.json()

    res = _run(fire, 6)
    _no_5xx([c for c, _ in res])
    for _, body in res:
        _await_compare(client, body)   # 等全部到达终态(完成或被淘汰)
    # 淘汰发生在任务 finally(DB 删稍早、热力图目录 prune 稍晚,均异步),
    # 轮询等「总数 ≤ 上限 且 热力图目录 ≤ 总数」一起收敛。
    heat_root = app.db.IMAGES_DIR / "heatmaps"
    total = None
    dirs = []
    for _ in range(80):
        total = client.get("/api/comparisons").json()["total"]
        dirs = [d for d in heat_root.iterdir() if d.is_dir()] if heat_root.exists() else []
        if total <= 5 and len(dirs) <= total:
            break
        time.sleep(0.1)
    assert total <= 5, f"上限未收敛: total={total}"
    assert len(dirs) <= total, f"残留热力图目录 {len(dirs)} > 对比 {total}"


# ---- 8. 混合读写负载:读不被压垮 ----

def test_mixed_read_write_load(client, png_bytes):
    for bid in ("s1", "s2", "s3"):
        assert _batch(client, bid=bid).status_code == 201
        assert _upload(client, bid, "shot", png_bytes((int(bid[-1]) * 60, 20, 20))).status_code == 201

    read_paths = ["/api/batches", "/api/meta", "/api/scenes/S/grid", "/api/comparisons"]
    read_ms, read_codes, write_codes = [], [], []

    def worker(i):
        if i % 4 == 0:   # 写:传图 + 偶尔对比
            c = _upload(client, "s1", f"extra_{i}", png_bytes()).status_code
            write_codes.append(c)
            if i % 8 == 0:
                r = client.post("/api/comparisons", json={"batch_id": "s2", "ref_batch_id": "s3"})
                write_codes.append(r.status_code)
        else:            # 读
            path = read_paths[i % len(read_paths)]
            r, ms = _timed(lambda: client.get(path))
            read_codes.append(r.status_code)
            read_ms.append(ms)

    _run(worker, 60, workers=12)
    _no_5xx(read_codes + write_codes)
    assert all(c == 200 for c in read_codes), read_codes
    worst = _stats("mixed_reads", read_ms)
    assert worst < 5000, f"读延迟过高: {worst:.0f}ms"


# ---- 9. 6 人端到端流程并发 ----

def test_six_users_workflow(client, png_bytes):
    ids = [str(i) for i in range(7)]
    for bid in ids:
        assert _batch(client, bid=bid).status_code == 201
        assert _upload(client, bid, "shot", png_bytes((int(bid) * 30 % 255, 40, 40))).status_code == 201

    errors = []

    def user(i):
        try:
            assert client.get("/api/batches", params={"page_size": 100}).status_code == 200
            assert client.get("/api/scenes/S/grid").status_code == 200
            r = client.post("/api/comparisons", json={"batch_id": ids[i + 1], "ref_batch_id": ids[0]})
            assert r.status_code == 202, r.text
            cid = _await_compare(client, r.json())
            assert client.get(f"/api/comparisons/{cid}/scenes").status_code == 200
            assert client.get("/api/comparisons").status_code == 200
        except Exception as e:   # noqa: BLE001
            errors.append(f"user{i}: {e!r}")

    _run(user, 6)
    assert not errors, errors

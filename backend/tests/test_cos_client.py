"""cos_client 单元测试:不连网。

把 `subprocess.run` 换成「假 COS」——一个在本地临时目录里真读真写的伪 cos_helper,
据此验证封装是否达到预期目标:命令拼装正确、原子下载、exists/list 解析、
错误码与超时都转成 CosError、上传前本地文件校验、配置/bucket 解析与回退。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import cos_client
from app.cos_client import CosClient, CosError


# ---- 假 cos_helper:解析我们拼出的 argv,在 cos_root 下模拟对象存储 ----

def _make_fake_run(cos_root: Path, calls: list):
    def objp(cos: str) -> Path:
        return cos_root / cos.lstrip("/")

    def fake_run(cmd, *, text=True, capture_output=True, timeout=None):
        calls.append(cmd)
        # 约定:[helper, -c, <cfg>, --bucket, <bucket>, <op>, ...]
        assert cmd[1] == "-c" and cmd[3] == "--bucket", f"未带 -c/--bucket: {cmd}"
        op, a = cmd[5], cmd[6:]

        def done(rc=0, out="", err=""):
            return subprocess.CompletedProcess(cmd, rc, out, err)

        if op == "put":
            local, cos = a[0], a[1]
            dst = objp(cos)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(Path(local).read_bytes())
            return done()
        if op == "get":
            cos = a[0]
            d = Path(a[a.index("-d") + 1]) if "-d" in a else Path(".")
            src = objp(cos)
            if not src.exists():
                return done(1, err="not found")
            d.mkdir(parents=True, exist_ok=True)
            (d / src.name).write_bytes(src.read_bytes())
            return done()
        if op == "rm":
            p = objp(a[0])
            if p.exists():
                p.unlink()
            return done()
        if op == "ls":
            p = objp(a[0])
            if p.is_file():
                return done(out=p.name + "\n")
            if p.is_dir():
                names = "\n".join(sorted(f.name for f in p.iterdir() if f.is_file()))
                return done(out=names + ("\n" if names else ""))
            return done(1, err="no such path")
        if op == "url":
            return done(out="http://fake-cos.example.com" + a[0] + "\n")
        return done(2, err=f"unknown op {op}")

    return fake_run


@pytest.fixture
def cos(tmp_path, monkeypatch):
    cos_root = tmp_path / "cosroot"
    cos_root.mkdir()
    calls: list = []
    monkeypatch.setattr(cos_client.subprocess, "run", _make_fake_run(cos_root, calls))
    client = CosClient(config=str(tmp_path / "dummy.yaml"), helper="fake_helper",
                       bucket="testbucket", timeout=5)
    return client, cos_root, tmp_path, calls


# ---- 核心目标:put/get 往返一致 ----

def test_put_get_roundtrip(cos):
    client, cos_root, tmp_path, _ = cos
    src = tmp_path / "src.png"
    src.write_bytes(b"\x89PNG\x00pixelcomparison")
    cos_path = "/PixelComparison/images/batches/1/a.png"

    client.put(cos_path, src)
    assert (cos_root / "PixelComparison/images/batches/1/a.png").exists()

    dest = tmp_path / "out" / "a.png"
    returned = client.get(cos_path, dest)
    assert returned == dest
    assert dest.read_bytes() == src.read_bytes()


def test_get_is_atomic_overwrite(cos):
    """目标已存在时 get 应覆盖为新内容(原子 replace)。"""
    client, cos_root, tmp_path, _ = cos
    src = tmp_path / "s.png"
    src.write_bytes(b"new-content")
    client.put("/PixelComparison/x.png", src)

    dest = tmp_path / "d.png"
    dest.write_bytes(b"old-content")
    client.get("/PixelComparison/x.png", dest)
    assert dest.read_bytes() == b"new-content"


# ---- exists / list / delete / url ----

def test_exists_true_then_false_after_delete(cos):
    client, cos_root, tmp_path, _ = cos
    src = tmp_path / "s"
    src.write_bytes(b"x")
    p = "/PixelComparison/images/batches/9/s.png"
    client.put(p, src)
    assert client.exists(p) is True
    client.delete(p)
    assert client.exists(p) is False


def test_exists_false_for_missing(cos):
    client, *_ = cos
    assert client.exists("/PixelComparison/nope/missing.png") is False


def test_list_prefix(cos):
    client, cos_root, tmp_path, _ = cos
    for name in ("a.png", "b.png"):
        f = tmp_path / name
        f.write_bytes(b"x")
        client.put(f"/PixelComparison/images/batches/7/{name}", f)
    listed = client.list("/PixelComparison/images/batches/7/")
    assert sorted(listed) == ["a.png", "b.png"]


def test_url(cos):
    client, *_ = cos
    assert client.url("/PixelComparison/images/batches/1/a.png") == \
        "http://fake-cos.example.com/PixelComparison/images/batches/1/a.png"


# ---- 命令拼装:每次都带 -c / --bucket ----

def test_command_passes_config_and_bucket(cos):
    client, cos_root, tmp_path, calls = cos
    src = tmp_path / "s"
    src.write_bytes(b"x")
    client.put("/PixelComparison/t.png", src)
    cmd = calls[-1]
    assert cmd[0] == "fake_helper"
    assert cmd[1:5] == ["-c", str(tmp_path / "dummy.yaml"), "--bucket", "testbucket"]
    assert cmd[5] == "put"


# ---- 失败/异常都转成 CosError ----

def test_get_missing_raises_coserror(cos):
    client, cos_root, tmp_path, _ = cos
    with pytest.raises(CosError):
        client.get("/PixelComparison/missing.png", tmp_path / "out.png")


def test_put_missing_local_raises_before_subprocess(cos):
    client, cos_root, tmp_path, calls = cos
    with pytest.raises(CosError):
        client.put("/PixelComparison/x.png", tmp_path / "does-not-exist.png")
    assert calls == []   # 不应起子进程


def test_nonzero_returncode_raises(monkeypatch, tmp_path):
    def boom(cmd, *, text=True, capture_output=True, timeout=None):
        return subprocess.CompletedProcess(cmd, 2, "", "boom")
    monkeypatch.setattr(cos_client.subprocess, "run", boom)
    client = CosClient(config="c", helper="h", bucket="b")
    with pytest.raises(CosError):
        client.url("/PixelComparison/x.png")


def test_timeout_raises_coserror(monkeypatch, tmp_path):
    def slow(cmd, *, text=True, capture_output=True, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout or 1)
    monkeypatch.setattr(cos_client.subprocess, "run", slow)
    client = CosClient(config="c", helper="h", bucket="b", timeout=0.01)
    with pytest.raises(CosError):
        client.url("/PixelComparison/x.png")


def test_helper_not_found_raises_coserror(monkeypatch):
    def missing(cmd, *, text=True, capture_output=True, timeout=None):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(cos_client.subprocess, "run", missing)
    client = CosClient(config="c", helper="nonexistent_helper", bucket="b")
    with pytest.raises(CosError):
        client.url("/PixelComparison/x.png")


# ---- 配置 / bucket 解析 ----

def test_resolve_config_missing_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("COS_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)   # 此目录下无 CosConfig.yaml
    with pytest.raises(CosError):
        cos_client.resolve_config()


def test_load_bucket_from_config(tmp_path):
    cfg = tmp_path / "CosConfig.yaml"
    cfg.write_text("cos:\n  bucket: arashimain\n  appid: 70674\n", encoding="utf-8")
    assert cos_client._load_bucket_from_config(str(cfg)) == "arashimain"


def test_bucket_explicit_skips_config(monkeypatch, tmp_path):
    """显式 bucket 时不应读取配置文件(配置可不存在)。"""
    monkeypatch.setattr(cos_client.subprocess, "run",
                        lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "ok\n", ""))
    client = CosClient(config=str(tmp_path / "absent.yaml"), helper="h", bucket="explicit")
    assert client.bucket == "explicit"

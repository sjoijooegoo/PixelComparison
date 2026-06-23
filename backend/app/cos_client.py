"""COS 访问封装:基于 `cos_helper` 命令行(当前环境无 `qcloud_cos` Python SDK)。

设计要点:
- **低层客户端**:只认「完整 COS 路径」(以 `/` 开头、已含项目前缀,如 `/PixelComparison/images/...`)。
  rel_path -> COS key 的映射是上层 storage 的职责,这里不掺和。
- **每次调用都有超时 + returncode 检查**,失败抛 `CosError`(摘要 stderr,不回显文件内容、不打印密钥)。
- **配置来源**:环境变量优先,回落 `CosConfig.yaml`;沿用已验证的 smoke 脚本解析逻辑,且不强依赖 PyYAML。
- COS 永远不在请求热路径上(近期数据恒为本地命中、热力图不上 COS),所以「每次起一个 cos_helper 子进程」可接受;
  批量场景(迁移/对账)用线程池并发调用,冷回源在 storage 层限并发。

cos_helper 命令约定(与项目 smoke 脚本一致):
    cos_helper -c <config> --bucket <bucket> <put|get|rm|ls|url> ...
    put <local> <cos>;  get <cos> -d <localdir>;  rm <cos>;  ls <cos>;  url <cos>
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class CosError(RuntimeError):
    """COS 操作失败(超时、cos_helper 非零退出、配置缺失等)。"""


# ---- 配置 / helper / bucket 解析(与 scripts/cos_pixelcomparison_smoke.py 对齐)----

_CONFIG_CANDIDATES = [Path("CosConfig.yaml"), Path("scripts") / "CosConfig.yaml"]


def resolve_config(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("COS_CONFIG")
    if env:
        return env
    for c in _CONFIG_CANDIDATES:
        if c.exists():
            return str(c)
    raise CosError("未找到 CosConfig.yaml;请设 COS_CONFIG 或放在 ./CosConfig.yaml / scripts/CosConfig.yaml")


def resolve_helper(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("COS_HELPER")
    if env:
        return env
    found = shutil.which("cos_helper") or shutil.which("cos_helper.exe")
    if found:
        return found
    scripts_dir = Path(sys.executable).resolve().parent / "Scripts"
    for name in ("cos_helper.exe", "cos_helper"):
        cand = scripts_dir / name
        if cand.exists():
            return str(cand)
    return str(scripts_dir / "cos_helper")


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1]
    return value


def _load_bucket_from_config(config_path: str) -> str:
    """从 CosConfig.yaml 读 cos.bucket。优先 PyYAML,缺失则用极简缩进解析(只取 cos.bucket)。"""
    try:
        import yaml  # type: ignore[import-not-found]

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        bucket = (data.get("cos") or {}).get("bucket") if isinstance(data, dict) else None
        if bucket:
            return str(bucket)
        raise CosError("CosConfig.yaml 缺少 cos.bucket")
    except ModuleNotFoundError:
        pass

    in_cos = False
    with open(config_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.strip()
            if indent == 0:
                in_cos = stripped.rstrip(":") == "cos" and stripped.endswith(":")
                continue
            if in_cos and ":" in stripped:
                key, val = stripped.split(":", 1)
                if key.strip() == "bucket" and val.strip():
                    return str(_parse_scalar(val))
    raise CosError("CosConfig.yaml 缺少 cos.bucket")


class CosClient:
    """cos_helper 的薄封装。线程安全:无可变共享状态,subprocess 各自独立。"""

    def __init__(
        self,
        config: str | None = None,
        helper: str | None = None,
        bucket: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.config = resolve_config(config)
        self.helper = resolve_helper(helper)
        self.bucket = bucket or os.environ.get("COS_BUCKET") or _load_bucket_from_config(self.config)
        self.timeout = timeout

    # ---- 内部:统一执行 ----

    def _run(self, *args: str, timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess:
        cmd = [self.helper, "-c", self.config, "--bucket", self.bucket, *args]
        try:
            r = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout or self.timeout)
        except FileNotFoundError as e:
            raise CosError(f"找不到 cos_helper:{self.helper}") from e
        except subprocess.TimeoutExpired as e:
            raise CosError(f"cos_helper {args[0] if args else ''} 超时(>{timeout or self.timeout}s)") from e
        if check and r.returncode != 0:
            # 只摘要 stderr,不回显本地文件内容;config 路径无敏感值,但不打印其内容
            raise CosError(
                f"cos_helper {args[0] if args else ''} 失败 rc={r.returncode}: {(r.stderr or '').strip()[:300]}"
            )
        return r

    # ---- 公开 API(cos_path 须为完整路径,如 /PixelComparison/images/...)----

    def put(self, cos_path: str, local_file: str | Path, timeout: float | None = None) -> None:
        """上传本地文件到 COS。"""
        lp = Path(local_file)
        if not lp.exists():
            raise CosError(f"待上传的本地文件不存在:{lp}")
        self._run("put", str(lp), cos_path, timeout=timeout)

    def get(self, cos_path: str, dest: str | Path, timeout: float | None = None) -> Path:
        """下载 COS 对象到 dest(原子):先 get 到目标目录,再 replace 到最终名。返回 dest。"""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._run("get", cos_path, "-d", str(dest.parent), timeout=timeout)
        downloaded = dest.parent / Path(cos_path).name
        if not downloaded.exists():
            raise CosError(f"cos_helper get 未产出文件:{downloaded}")
        if downloaded.resolve() != dest.resolve():
            if dest.exists():
                dest.unlink()
            downloaded.replace(dest)
        return dest

    def delete(self, cos_path: str, timeout: float | None = None) -> None:
        """删除 COS 对象(幂等:对象不存在不应视为错误,由调用方按需忽略)。"""
        self._run("rm", cos_path, timeout=timeout)

    def list(self, cos_prefix: str, timeout: float | None = None) -> list[str]:
        """列出前缀下的对象行(原样返回 cos_helper ls 的非空行)。"""
        r = self._run("ls", cos_prefix, timeout=timeout)
        return [line for line in (r.stdout or "").strip().splitlines() if line.strip()]

    def exists(self, cos_path: str, timeout: float | None = None) -> bool:
        """对象是否存在:ls 精确路径,rc==0 且输出含该 basename 即存在。"""
        r = self._run("ls", cos_path, timeout=timeout, check=False)
        if r.returncode != 0:
            return False
        base = Path(cos_path).name
        return any(base in line for line in (r.stdout or "").splitlines())

    def url(self, cos_path: str, timeout: float | None = None) -> str:
        """对象的访问 URL(当前 public-read 桶返回普通 HTTP 直链)。"""
        r = self._run("url", cos_path, timeout=timeout)
        return (r.stdout or "").strip()

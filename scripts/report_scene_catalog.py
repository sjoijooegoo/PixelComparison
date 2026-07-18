#!/usr/bin/env python3
"""把权威场景目录全量上报到 PixelComparison 后端。

仅依赖 Python 标准库。接口是全量替换语义：JSON 中未包含的已有场景会从
前端筛选框隐藏，但不会删除数据库中的批次。

用法：
    python scripts/report_scene_catalog.py scene-catalog.json
    python scripts/report_scene_catalog.py scene-catalog.json --dry-run
    python scripts/report_scene_catalog.py - --url http://127.0.0.1:8020/api/scene-catalog
    python scripts/report_scene_catalog.py --print-example
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence


DEFAULT_URL = "http://21.130.229.92:5173/api/scene-catalog"
URL_ENV = "PIXELCOMP_SCENE_CATALOG_URL"
EXAMPLE_PAYLOAD = {
    "scene_id_order": [
        "Village_Dimension_Main",
        "RottenVale_WP",
        "OtherScene",
    ]
}


class CatalogFormatError(ValueError):
    """场景目录 JSON 不符合后端约定。"""


def format_guidance() -> str:
    return (
        "数据格式（数组顺序就是前端场景下拉框顺序）：\n"
        + json.dumps(EXAMPLE_PAYLOAD, ensure_ascii=False, indent=2)
        + "\n约束：根节点必须是对象；scene_id_order 必须是数组；场景 ID 必须是"
        "非空字符串、不能有首尾空格或重复，单项最长 255 字符，最多 5000 项。"
        "空数组表示隐藏全部数据库场景。"
    )


def validate_payload(payload: Any) -> dict[str, list[str]]:
    if not isinstance(payload, dict):
        raise CatalogFormatError("JSON 根节点必须是对象")
    if "scene_id_order" not in payload:
        raise CatalogFormatError("缺少必填字段 scene_id_order")

    scene_ids = payload["scene_id_order"]
    if not isinstance(scene_ids, list):
        raise CatalogFormatError("scene_id_order 必须是数组")
    if len(scene_ids) > 5000:
        raise CatalogFormatError("scene_id_order 最多包含 5000 个场景 ID")

    seen: set[str] = set()
    for index, scene_id in enumerate(scene_ids):
        label = f"scene_id_order[{index}]"
        if not isinstance(scene_id, str):
            raise CatalogFormatError(f"{label} 必须是字符串")
        if not scene_id or scene_id != scene_id.strip():
            raise CatalogFormatError(f"{label} 不能为空或包含首尾空格")
        if len(scene_id) > 255:
            raise CatalogFormatError(f"{label} 长度不能超过 255 个字符")
        if scene_id in seen:
            raise CatalogFormatError(f"{label} 与前面的场景 ID 重复：{scene_id}")
        seen.add(scene_id)

    # 只发送接口约定字段，避免输入文件中的注释性扩展字段意外传给后端。
    return {"scene_id_order": list(scene_ids)}


def load_payload(path_value: str) -> dict[str, list[str]]:
    try:
        if path_value == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(path_value).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise CatalogFormatError(f"无法读取 JSON 文件：{exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogFormatError(
            f"JSON 语法错误：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}"
        ) from exc
    return validate_payload(payload)


def upload_catalog(
    url: str,
    payload: dict[str, list[str]],
    timeout: float = 30,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "PixelComparison-scene-catalog-reporter/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"后端返回 HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接后端：{exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"连接后端超时（{timeout:g} 秒）") from exc

    if status != 200:
        raise RuntimeError(f"后端返回非预期状态码 HTTP {status}：{response_body}")
    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("后端成功响应不是有效 JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("后端成功响应的根节点不是对象")
    if result.get("scene_id_order") != payload["scene_id_order"]:
        raise RuntimeError("后端返回的场景目录与上报内容不一致")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="全量上报 PixelComparison 前端场景目录",
        epilog=format_guidance(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "json_file",
        nargs="?",
        help="场景目录 JSON 文件；传 - 表示从标准输入读取",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get(URL_ENV, DEFAULT_URL),
        help=f"上报接口（默认：环境变量 {URL_ENV}，否则 {DEFAULT_URL}）",
    )
    parser.add_argument("--timeout", type=float, default=30, help="请求超时秒数（默认：30）")
    parser.add_argument("--dry-run", action="store_true", help="只校验并预览，不发送请求")
    parser.add_argument("--print-example", action="store_true", help="打印示例 JSON 后退出")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.print_example:
        print(json.dumps(EXAMPLE_PAYLOAD, ensure_ascii=False, indent=2))
        return 0
    if not args.json_file:
        parser.print_help()
        return 2
    if args.timeout <= 0:
        print("错误：--timeout 必须大于 0", file=sys.stderr)
        return 2

    try:
        payload = load_payload(args.json_file)
    except CatalogFormatError as exc:
        print(f"数据格式错误：{exc}", file=sys.stderr)
        print(format_guidance(), file=sys.stderr)
        return 2

    scene_ids = payload["scene_id_order"]
    print(f"数据校验通过：{len(scene_ids)} 个场景")
    print(f"目标接口：{args.url}")
    if args.dry_run:
        print("dry-run：未发送请求")
        return 0

    try:
        result = upload_catalog(args.url, payload, args.timeout)
    except RuntimeError as exc:
        print(f"上报失败：{exc}", file=sys.stderr)
        return 1

    print(
        "上报成功：后端已保存 "
        f"{len(result['scene_id_order'])} 个场景，顺序与输入完全一致"
    )
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

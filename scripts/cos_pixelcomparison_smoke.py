from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


DEFAULT_PREFIX = "PixelComparison"
DEFAULT_CONFIG_CANDIDATES = [
    Path("CosConfig.yaml"),
    Path("scripts") / "CosConfig.yaml",
]


def resolve_config(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_config = os.environ.get("COS_CONFIG")
    if env_config:
        return env_config
    for candidate in DEFAULT_CONFIG_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    raise SystemExit(
        "CosConfig.yaml not found. Pass --config or set COS_CONFIG.\n"
        "Example:\n"
        "  python scripts\\cos_pixelcomparison_smoke.py --config C:\\path\\CosConfig.yaml upload README.md test/README.md"
    )


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.lower() in ("null", "none", "~"):
        return None
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def load_yaml(path: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError("top-level yaml value must be a mapping")
        return data
    except ModuleNotFoundError:
        return load_simple_yaml(path)


def load_simple_yaml(path: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if ":" not in line:
                continue

            key, raw_value = line.strip().split(":", 1)
            while stack and indent <= stack[-1][0]:
                stack.pop()
            current = stack[-1][1]
            raw_value = raw_value.strip()
            if raw_value:
                current[key] = parse_scalar(raw_value)
            else:
                child: dict[str, Any] = {}
                current[key] = child
                stack.append((indent, child))
    return root


def get_config_bucket(config: dict[str, Any]) -> str:
    cos_config = config.get("cos")
    if not isinstance(cos_config, dict):
        raise SystemExit("Invalid CosConfig.yaml: missing 'cos' section.")
    bucket = cos_config.get("bucket")
    if not bucket:
        raise SystemExit("Invalid CosConfig.yaml: missing 'cos.bucket'.")
    return str(bucket)


def resolve_helper(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_helper = os.environ.get("COS_HELPER")
    if env_helper:
        return env_helper
    found = shutil.which("cos_helper") or shutil.which("cos_helper.exe")
    if found:
        return found

    scripts_dir = Path(sys.executable).resolve().parent / "Scripts"
    for name in ("cos_helper.exe", "cos_helper"):
        candidate = scripts_dir / name
        if candidate.exists():
            return str(candidate)
    return str(scripts_dir / "cos_helper")


def normalize_cos_path(name: str, prefix: str) -> str:
    clean_prefix = prefix.strip("/\\")
    parts = [part for part in name.replace("\\", "/").split("/") if part]
    if not parts:
        raise ValueError("remote name cannot be empty")
    if parts[0] != clean_prefix:
        parts.insert(0, clean_prefix)
    return "/" + "/".join(parts)


def run_cos_helper(args: argparse.Namespace, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    full_command = [
        args.helper,
        "-c",
        args.config,
        "--bucket",
        args.bucket,
        *command,
    ]
    print(">", " ".join(full_command))
    result = subprocess.run(full_command, text=True, capture_output=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return result


def upload(args: argparse.Namespace) -> None:
    local_path = Path(args.local_file)
    if not local_path.exists():
        raise SystemExit(f"local file not found: {local_path}")
    remote_name = args.remote_name or local_path.name
    cos_path = normalize_cos_path(remote_name, args.prefix)
    run_cos_helper(args, ["put", str(local_path), cos_path])
    run_cos_helper(args, ["url", cos_path])


def download(args: argparse.Namespace) -> None:
    cos_path = normalize_cos_path(args.remote_name, args.prefix)
    remote_basename = Path(cos_path).name
    if args.output:
        output_path = Path(args.output)
        if output_path.exists() and output_path.is_dir():
            download_dir = output_path
            final_path = output_path / remote_basename
        elif str(args.output).endswith(("/", "\\")):
            download_dir = output_path
            final_path = output_path / remote_basename
        else:
            download_dir = output_path.parent if output_path.parent != Path("") else Path(".")
            final_path = output_path
    else:
        download_dir = Path(".")
        final_path = Path(remote_basename)

    download_dir.mkdir(parents=True, exist_ok=True)
    run_cos_helper(args, ["get", cos_path, "-d", str(download_dir)])

    downloaded_path = download_dir / remote_basename
    if downloaded_path.resolve() != final_path.resolve():
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            final_path.unlink()
        downloaded_path.replace(final_path)


def show_url(args: argparse.Namespace) -> None:
    cos_path = normalize_cos_path(args.remote_name, args.prefix)
    run_cos_helper(args, ["url", cos_path])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minimal COS upload/download smoke script for the PixelComparison prefix."
    )
    parser.add_argument("--bucket", default=os.environ.get("COS_BUCKET"), help="Override cos.bucket from CosConfig.yaml.")
    parser.add_argument("--prefix", default=os.environ.get("COS_PREFIX", DEFAULT_PREFIX))
    parser.add_argument("--config", default=None, help="CosConfig.yaml path. Defaults to COS_CONFIG or ./CosConfig.yaml.")
    parser.add_argument("--helper", default=None, help="cos_helper path. Defaults to COS_HELPER, PATH, or Python Scripts.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    upload_parser = subparsers.add_parser("upload", help="Upload a local file to /PixelComparison/.")
    upload_parser.add_argument("local_file")
    upload_parser.add_argument("remote_name", nargs="?", help="Remote name under /PixelComparison/. Defaults to local filename.")
    upload_parser.set_defaults(func=upload)

    download_parser = subparsers.add_parser("download", help="Download a file from /PixelComparison/.")
    download_parser.add_argument("remote_name")
    download_parser.add_argument("output", nargs="?", help="Local output file or directory. Defaults to remote basename.")
    download_parser.set_defaults(func=download)

    url_parser = subparsers.add_parser("url", help="Print the HTTP URL for a file under /PixelComparison/.")
    url_parser.add_argument("remote_name")
    url_parser.set_defaults(func=show_url)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.config = resolve_config(args.config)
    args.helper = resolve_helper(args.helper)
    config = load_yaml(args.config)
    args.bucket = args.bucket or get_config_bucket(config)
    args.func(args)


if __name__ == "__main__":
    main()

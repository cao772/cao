from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any


COPY_MARKERS = re.compile(r"(?:副本|copy|备份|backup|归档|archive|historical|history)", re.IGNORECASE)
ARCHIVE_SUFFIXES = (".zip", ".7z", ".tar.gz", ".tgz", ".tar", ".gz")
CONTENT_SUPPORTED = {
    ".md", ".txt", ".rst", ".json", ".yaml", ".yml",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go",
    ".rs", ".c", ".h", ".cpp", ".hpp", ".sh", ".sql",
    ".docx", ".xlsx",
}
LEGACY_OR_PENDING = {
    ".doc": "旧版 Word，当前正文解析器未直接支持",
    ".pdf": "PDF 当前只做文件元数据，正文解析待接入",
    ".pptx": "PPTX 当前只做文件元数据，正文解析待接入",
    ".csv": "CSV 当前只做文件元数据，正文解析待接入",
}


def logical_suffix(path: str) -> str:
    lower = path.lower()
    for suffix in ARCHIVE_SUFFIXES:
        if lower.endswith(suffix):
            return suffix
    return PurePosixPath(lower).suffix


def build_workspace_inventory(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the files that the local collector explicitly exposed as metadata.

    This never inspects file bodies. It helps the central platform explain a messy
    project folder: document mix, historical copies, archives and formats that still
    need a parser. Only paths already allowed by project.yaml are considered.
    """
    suffix_counts: Counter[str] = Counter()
    total_bytes = 0
    root_files = 0
    sensitive = 0
    copy_like: list[str] = []
    archives: list[dict[str, Any]] = []
    pending_parsers: list[dict[str, str]] = []
    large_files: list[dict[str, Any]] = []
    content_ready = 0

    normalized_paths: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").replace("\\", "/").strip("/")
        if not path:
            continue
        normalized_paths.append(path)
        if item.get("sensitive"):
            sensitive += 1
            continue

        suffix = logical_suffix(path)
        suffix_counts[suffix or "<none>"] += 1
        size = int(item.get("size") or 0)
        total_bytes += max(0, size)
        if "/" not in path:
            root_files += 1
        if COPY_MARKERS.search(path):
            copy_like.append(path)
        if suffix in CONTENT_SUPPORTED:
            content_ready += 1
        if suffix in LEGACY_OR_PENDING:
            pending_parsers.append({"path": path, "suffix": suffix, "reason": LEGACY_OR_PENDING[suffix]})
        if any(path.lower().endswith(archive_suffix) for archive_suffix in ARCHIVE_SUFFIXES):
            archives.append({"path": path, "size": size})
        if size >= 20 * 1024 * 1024:
            large_files.append({"path": path, "size": size})

    # Detect the common handoff pattern `pack/` plus `pack.zip` without opening archives.
    folder_prefixes = {path.split("/", 1)[0] for path in normalized_paths if "/" in path}
    packaged_duplicates: list[dict[str, str]] = []
    for archive in archives:
        name = PurePosixPath(archive["path"]).name
        stem = name
        for suffix in ARCHIVE_SUFFIXES:
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        if stem in folder_prefixes:
            packaged_duplicates.append({"archive": archive["path"], "folder": stem})

    warnings: list[str] = []
    if pending_parsers:
        warnings.append(f"检测到 {len(pending_parsers)} 个当前未做正文解析的重要格式，已保留元数据。")
    if copy_like:
        warnings.append(f"检测到 {len(copy_like)} 个带副本/备份/归档标记的路径，当前状态融合时应降权。")
    if packaged_duplicates:
        warnings.append(
            f"检测到 {len(packaged_duplicates)} 组目录与压缩包并存，压缩包不应再次作为独立项目证据。"
        )
    if root_files >= 20:
        warnings.append("项目根目录资料较多，建议继续依赖 project.yaml 白名单而不是全目录正文扫描。")
    if large_files:
        warnings.append(f"检测到 {len(large_files)} 个大于等于 20MB 的文件，默认不应周期性重复解析正文。")

    return {
        "file_count": len(normalized_paths),
        "total_bytes": total_bytes,
        "root_file_count": root_files,
        "sensitive_count": sensitive,
        "content_parser_ready_count": content_ready,
        "suffix_counts": dict(suffix_counts.most_common()),
        "copy_like_paths": copy_like[:100],
        "archives": archives[:100],
        "packaged_duplicates": packaged_duplicates[:100],
        "pending_parsers": pending_parsers[:100],
        "large_files": sorted(large_files, key=lambda item: item["size"], reverse=True)[:50],
        "warnings": warnings,
    }

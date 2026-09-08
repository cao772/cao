from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs",
    ".c", ".h", ".cpp", ".hpp", ".sh", ".sql", ".vue", ".css", ".scss",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
}
SENSITIVE_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def run_git(repo: Path, *args: str, timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def endpoint_is_local(base_url: str) -> bool:
    try:
        hostname = urllib.parse.urlparse(base_url).hostname
    except ValueError:
        return False
    return hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def classify_area(path: str) -> str:
    lower = path.lower().replace("\\", "/")
    if any(token in lower for token in ("/test/", "/tests/", "test_", ".spec.", ".test.")):
        return "tests"
    if any(token in lower for token in ("frontend/", "web/", "ui/", "pages/", "components/")):
        return "frontend"
    if any(token in lower for token in ("backend/", "server/", "api/", "app/", "service/")):
        return "backend"
    if any(token in lower for token in ("docker", "compose", "deploy", "k8s", "helm", "nginx")):
        return "deployment"
    if any(token in lower for token in ("migration", "alembic", "schema", "database", "models/")):
        return "database"
    if any(token in lower for token in ("docs/", "readme", ".md")):
        return "documentation"
    if any(token in lower for token in ("config", "settings", ".yaml", ".yml", ".toml")):
        return "configuration"
    return "code"


def _parse_numstat(text: str) -> tuple[int | None, int | None]:
    additions = deletions = 0
    found = False
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        if parts[0].isdigit() and parts[1].isdigit():
            additions += int(parts[0])
            deletions += int(parts[1])
            found = True
    return (additions, deletions) if found else (None, None)


def _extract_hunk_symbols(diff_text: str) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for line in diff_text.splitlines():
        if not line.startswith("@@"):
            continue
        parts = line.split("@@", 2)
        context = parts[2].strip() if len(parts) >= 3 else ""
        context = re.sub(r"\s+", " ", context)[:180]
        if context and context not in seen:
            seen.add(context)
            symbols.append(context)
        if len(symbols) >= 20:
            break
    return symbols


def _risk_flags(path: str, additions: int | None, deletions: int | None, diff_text: str) -> list[str]:
    lower = path.lower()
    flags: list[str] = []
    if any(token in lower for token in ("auth", "security", "password", "secret", "permission")):
        flags.append("security_sensitive_area")
    if any(token in lower for token in ("migration", "alembic", "schema", "database")):
        flags.append("database_change")
    if any(token in lower for token in ("docker", "compose", "deploy", "k8s", "helm", "nginx")):
        flags.append("deployment_change")
    if deletions is not None and additions is not None and deletions >= 100 and deletions > additions * 2:
        flags.append("large_deletion")
    lowered_diff = diff_text.lower()
    if any(token in lowered_diff for token in ("todo", "fixme", "hack")):
        flags.append("contains_todo_or_fixme")
    return flags


def deterministic_change_summary(
    path: str,
    kind: str,
    additions: int | None,
    deletions: int | None,
    symbols: list[str],
    risks: list[str],
) -> dict[str, Any]:
    area = classify_area(path)
    delta = ""
    if additions is not None and deletions is not None:
        delta = f"，+{additions}/-{deletions}"
    symbol_text = f"，涉及 {', '.join(symbols[:3])}" if symbols else ""
    summary = f"{kind} {path}，影响区域 {area}{delta}{symbol_text}"
    return {
        "source": "deterministic",
        "summary": summary[:800],
        "change_area": area,
        "mentioned_symbols": symbols[:20],
        "business_capabilities": [],
        "risks": risks,
    }


def analyze_with_openai_compatible(
    *,
    path: str,
    kind: str,
    additions: int | None,
    deletions: int | None,
    diff_text: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    system = (
        "你是研发代码变更分析器。只根据给定 git diff 判断本次改动，不推测不存在的功能。"
        "输出严格 JSON：summary、change_area、business_capabilities、mentioned_symbols、risks。"
        "summary 用业务可理解的中文说明改了什么；不要输出大段源码。"
    )
    user = (
        f"文件: {path}\n状态: {kind}\n新增行: {additions}\n删除行: {deletions}\n"
        "请分析这次本地未提交改动对应的技术/业务变化。\n\n"
        f"{diff_text}"
    )
    payload = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
    parsed = json.loads(content)
    return {
        "source": "llm",
        "summary": re.sub(r"\s+", " ", str(parsed.get("summary") or "")).strip()[:1000],
        "change_area": str(parsed.get("change_area") or classify_area(path))[:100],
        "business_capabilities": [
            re.sub(r"\s+", " ", str(item)).strip()[:200]
            for item in (parsed.get("business_capabilities") or [])[:20]
            if str(item).strip()
        ],
        "mentioned_symbols": [
            re.sub(r"\s+", " ", str(item)).strip()[:180]
            for item in (parsed.get("mentioned_symbols") or [])[:30]
            if str(item).strip()
        ],
        "risks": [
            re.sub(r"\s+", " ", str(item)).strip()[:200]
            for item in (parsed.get("risks") or [])[:20]
            if str(item).strip()
        ],
    }


def analyze_git_changes(
    repo: Path | None,
    repository_path: str,
    git_state: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    cfg = ((manifest.get("analysis") or {}).get("git_changes") or {})
    enabled = bool(cfg.get("enabled", True))
    if not enabled:
        return {"enabled": False, "reason": "analysis.git_changes.enabled=false"}
    if repo is None or not git_state.get("is_git_repo"):
        return {
            "enabled": False,
            "reason": "canonical git repository unavailable",
            "repository_path": repository_path,
        }

    security_mode = str((manifest.get("security") or {}).get("mode") or "metadata_only")
    use_llm = bool(cfg.get("use_llm", False)) and security_mode == "local_analysis"
    max_files = int(cfg.get("max_files", 80))
    max_diff_chars = int(cfg.get("max_diff_chars_per_file", 12000))

    base_url = os.getenv("LOCAL_LLM_BASE_URL", "").strip()
    model = os.getenv("LOCAL_LLM_MODEL", "").strip()
    api_key = os.getenv("LOCAL_LLM_API_KEY", "")
    timeout = int(os.getenv("LOCAL_LLM_TIMEOUT", "60"))
    allow_remote = os.getenv("ALLOW_REMOTE_ANALYSIS_ENDPOINT", "false").lower() == "true"
    llm_ready = use_llm and bool(base_url and model) and (allow_remote or endpoint_is_local(base_url))

    items: list[dict[str, Any]] = []
    changed_files = list(git_state.get("changed_files") or [])[:max_files]
    for changed in changed_files:
        path = str(changed.get("path") or "")
        kind = str(changed.get("kind") or "other")
        if not path:
            continue
        name = Path(path).name
        suffix = Path(path).suffix.lower()
        sensitive = name in SENSITIVE_NAMES or suffix in SENSITIVE_SUFFIXES
        if sensitive:
            items.append({"path": path, "kind": kind, "status": "sensitive_skipped"})
            continue

        additions: int | None = None
        deletions: int | None = None
        diff_text = ""
        if kind != "untracked":
            _, numstat = run_git(repo, "diff", "HEAD", "--numstat", "--", path)
            additions, deletions = _parse_numstat(numstat)
            if suffix in CODE_SUFFIXES:
                _, raw_diff = run_git(repo, "diff", "HEAD", "--unified=0", "--", path)
                diff_text = raw_diff[:max_diff_chars]

        symbols = _extract_hunk_symbols(diff_text)
        risks = _risk_flags(path, additions, deletions, diff_text)
        result = deterministic_change_summary(path, kind, additions, deletions, symbols, risks)

        if llm_ready and diff_text.strip():
            try:
                result = analyze_with_openai_compatible(
                    path=path,
                    kind=kind,
                    additions=additions,
                    deletions=deletions,
                    diff_text=diff_text,
                    base_url=base_url,
                    model=model,
                    api_key=api_key,
                    timeout=timeout,
                )
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError):
                result["llm_fallback"] = True

        items.append(
            {
                "path": path,
                "kind": kind,
                "status": "analyzed",
                "additions": additions,
                "deletions": deletions,
                "analysis": result,
            }
        )

    return {
        "enabled": True,
        "repository_path": repository_path,
        "llm": {
            "requested": use_llm,
            "ready": llm_ready,
            "model": model or None,
        },
        "changed_file_count": len(git_state.get("changed_files") or []),
        "analyzed_file_count": len(items),
        "truncated": len(git_state.get("changed_files") or []) > max_files,
        "items": items,
    }

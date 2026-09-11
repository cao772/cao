from project_brief import build_project_brief
from project_memory import build_current_project_memory


def _item(path: str, role: str, text: str, fact_type: str):
    return {
        "path": path,
        "role": role,
        "status": "analyzed",
        "analysis": {"summary": text, "facts": [{"type": fact_type, "text": text}]},
    }


def _snapshot(memory):
    return {"payload": {"git": {"dirty": False}, "analysis": {"current_project_memory": memory}}}


def test_brief_uses_new_completion_not_older_pending_statement():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item("工作任务2026-09-01.xlsx", "progress", "资料上传页待开发", "task"),
                _item("项目周报2026-09-10.docx", "report", "资料上传页已经完成", "progress"),
            ],
        },
        reference_year=2026,
    )
    brief = build_project_brief([_snapshot(memory)], {"work_items": []})
    assert any("资料上传页已经完成" in text for text in brief["completed"])
    assert all("资料上传页待开发" not in text for text in brief["next_steps"])


def test_brief_does_not_surface_historical_blocker_as_current_issue():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item("问题反馈2026-07-01.xlsx", "test_result", "历史问题仍需处理", "blocker"),
                _item("项目周报2026-09-10.docx", "report", "当前联调已完成", "progress"),
            ],
        },
        reference_year=2026,
    )
    brief = build_project_brief([_snapshot(memory)], {"work_items": []})
    assert all("历史问题" not in text for text in brief["issues"])
    assert brief["source_status"]["historical_fact_count"] >= 1

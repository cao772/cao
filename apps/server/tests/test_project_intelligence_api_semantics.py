from __future__ import annotations

from project_intelligence_api import _normalize_public_material_semantics


def test_public_contract_semantics_keep_supplement_related():
    intelligence = {
        "materials": [
            {"path": "商务/项目合同.pdf", "material_type": "contract", "version_status": "single"},
            {"path": "商务/合同补充协议2.pdf", "material_type": "contract_supplement", "version_status": "primary"},
            {"path": "商务/合同附件.xlsx", "material_type": "contract_attachment", "version_status": "single"},
        ]
    }
    _normalize_public_material_semantics(intelligence)
    statuses = {item["path"]: item["version_status"] for item in intelligence["materials"]}
    assert statuses["商务/项目合同.pdf"] == "primary"
    assert statuses["商务/合同补充协议2.pdf"] == "active_related"
    assert statuses["商务/合同附件.xlsx"] == "active_related"

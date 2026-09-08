# GitLab repository registry

The first production-oriented registry is based on the real Hyetec GitLab repositories supplied for validation.

## Project mapping

| project_id | logical role | repository URL |
| --- | --- | --- |
| `low-voltage` | frontend | `http://git.hyetec.com/hyetec/rj26nw011/Front-end/voltage-management.git` |
| `low-voltage` | algorithm/backend | `http://git.hyetec.com/hyetec/rj26nw011/algorithm.git` |
| `power-defect-agent` | multimodal defect agent | `http://git.hyetec.com/hyetec/rj26nw025/multimodal-agent.git` |
| `hyclaw-plugins` | HyClaw plugin workspace | `http://git.hyetec.com/hyetec/rrj26rj001/hyclaw/plugins/hyclaw-plugins.git` |

The central platform must treat one project as potentially containing multiple repositories. `low-voltage` is the first real example: frontend and algorithm repositories belong to the same managed project and must be fused at task level instead of shown as two unrelated projects.

## Collection principle

- Local Sentinel inspects each configured local clone separately and reports repository-scoped Git state.
- The central service keeps repository identity (`repository_id`, role, provider and URL) with every Git/remote evidence item.
- GitLab/GitHub remote facts are collected centrally. Developer laptops do not repeatedly poll the same server.
- Private GitLab credentials are never stored in `project.yaml`. Tokens are supplied to the central remote collector through environment variables or a secret store.
- Repository content does not need to be uploaded to the central service. Commit/MR/pipeline metadata and locally generated semantic summaries are sufficient for the first phase.

## GitLab connectivity

These URLs use the private host `git.hyetec.com`, so the CI environment for this repository is not expected to reach them. Real connectivity and authentication validation must be performed from the corporate network or an approved VPN-connected collector host.

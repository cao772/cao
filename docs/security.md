# 安全与隐私边界

## 默认原则

1. Local Sentinel 对项目目录默认只读挂载。
2. 中央默认不接收源码全文、Word/PDF/Excel 原文、`.env`、密钥和凭证。
3. 所有上传都必须带 `project_id`、`user_id`、`device_id`，便于审计和撤销设备权限。
4. 采集与分析权限由 `project.yaml` 控制；中央策略可以进一步收紧，但不能放宽本地声明。

## 默认拒绝正文读取

无论项目配置如何，以下内容默认不进入正文分析：

- `.env*`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`
- `.ssh/`, `.aws/`, `.kube/`
- token、credential、secret 等敏感配置目录
- `.git/` 对象数据库正文

## 三种数据模式

### metadata_only
只上传：
- Git branch/HEAD/ahead/behind；
- modified/added/deleted/untracked 数量与路径；
- diff stat（行数统计，不含 patch 正文）；
- 文件路径/类型/大小/mtime/hash；
- 测试总数/通过/失败；
- 明确的 Agent 结构化上报。

### local_analysis
允许本机分析允许目录中的文本，但中央只获得摘要、标签、风险、阻塞等结构化结果。

### central_analysis
只有项目显式授权后，才允许上传白名单文本片段供中央模型分析；服务端需保留数据来源和审计记录。

## 传输与认证

Phase 1：Collector Token + HTTPS。
后续企业版：设备注册、短期令牌、mTLS/SSO、密钥轮换、组织/项目 RBAC。

## 反绩效化边界

平台首要用途是项目状态、证据链与协作，不默认把代码量、Agent 使用量、Token 数量作为员工绩效指标。

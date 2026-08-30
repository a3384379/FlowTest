# FlowTest V6.0 H1 真实 Key Rotation

## 1. 阶段状态

S54 已由 PR #62 普通 Squash Merge，PR 与 Merge 后 Main Push 七项门禁全部成功。H1 从最新 Main
创建独立分支 `codex/v6-h1-real-key-rotation`；当前实现与定向验证已完成，待 PR 复审和最终门禁。

## 2. 实现

- 密文新增带认证密钥引用的 `FTK1` 包络，保持对旧 AES-256-GCM 密文的读兼容。
- 部署密钥环验证每个引用的格式、长度和 32 字节 URL-safe Base64 密钥，禁止覆盖默认引用。
- 组织活动版本控制新写入；Prepare 验证服务端已配置引用且 fingerprint 匹配。
- Apply/Rollback 对组织范围受管密文加行锁，在单一事务内重加密、解密验证、切换版本并写审计；
  失败时不留下部分迁移状态。
- 轮换注册表覆盖 Secret、本地 Credential、Import Preview、Encrypted Execution Plan、Test Plan Webhook
  和 Notification Webhook。
- Organization Governance 页面按权限和密钥状态展示 Prepare、Apply 或 Rollback，并如实展示真实轮换能力。
- Full/Compact/Standalone 配置传递密钥环；Standalone→Compact 传输 Manifest 明确保留密钥引用，
  但不携带密钥材料。
- Migration `20260830_0049` 把旧版活动初始密钥如实标记为已迁移，并提供可逆 downgrade。

## 3. 已完成的定向验证

- SecretBox 新引用包络与历史密文兼容。
- 内存数据库中六类真实密文完成 v1→v2 和 v2→v1 重加密、解密校验与计数校验。
- Organization API 完整 Prepare→Apply→Rollback 生命周期及审计动作。
- Frontend 轮换动作状态机、TypeScript、Prettier、ESLint 和相关 Vitest。
- Migration `0048→0049→0048→0049` 定向往返已通过。

## 4. H1 Exit Criteria

| 条件 | 当前状态 | 证据 |
| --- | --- | --- |
| Create New Key Version | Pass | Prepare 校验引用与 fingerprint |
| Re-encrypt / Verify / Activate | Pass | 六类密文事务性回归 |
| Rollback | Pass | v2→v1 真实重加密回归 |
| Audit | Pass | Applied/Rolled-back 计数与摘要 |
| Full/Compact/Standalone 配置与迁移边界 | Pass | Compose/Standalone/Transfer 配置与文档 |
| PR Review P0/P1 为 0 | Pending | 待 GitHub Codex 复审 |
| 最终一次完整门禁 | Pending | P0/P1 清零后执行 |

## 5. 边界

- V6.0 Core 使用原子事务，不宣称分批或无停机轮换。
- Vault Credential 没有本地密文，其外部引用保持不变。
- H2 公司环境备份/恢复、长时运行和人工签署仍是 GA 门槛，不由本 PR 代替。

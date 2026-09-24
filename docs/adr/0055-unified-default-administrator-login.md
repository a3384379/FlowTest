# ADR 0055：统一默认管理员登录

状态：Accepted
日期：2026-09-24

## 决策

Full、Compact 和 Standalone 新安装统一使用登录别名 `admin` 和初始密码
`admin123456`。别名继续映射到 `FLOWTEST_BOOTSTRAP_ADMIN_EMAIL`（默认
`admin@flowtest.dev`）；通过 `FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD` 可以在部署前覆盖密码。
新建的 bootstrap 管理员不设置首次改密标记，其他用户的首次改密规则不变。

此决策替代 [ADR 0026](0026-explicit-runtime-profiles-and-compact-deployment.md) 第 7 项中的
Compact 随机管理员密码。Compact 的 JWT、数据加密、数据库和对象存储密钥继续随机生成；
配置生成器拒绝覆盖已有 `.env`。启动 bootstrap 对已有用户保持幂等，不重置密码或改密标记。
此默认账号密码适用于所有运行环境；其他生产配置校验保持不变。

## 影响

只影响新建部署和新建数据库中的 bootstrap 管理员。已有部署维持原账号密码；
管理员如需统一旧环境凭据，应通过正常改密流程分别处理。

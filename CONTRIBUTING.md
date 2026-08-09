# 参与开发

## 分支与提交

- 功能分支：`feat/<short-name>`
- 修复分支：`fix/<short-name>`
- 提交信息采用 Conventional Commits，例如 `feat(api): add project endpoint`
- 一个 Pull Request 聚焦一个可验证目标

## 提交前检查

```bash
make check
```

涉及数据库模型的变更必须包含 Alembic 迁移；涉及 API 契约的变更必须更新测试和 OpenAPI 示例。

## 完成定义

- 验收标准通过
- 单元/集成测试通过
- 静态检查通过
- 无明文 Secret 或未脱敏的敏感日志
- 文档与变更保持一致

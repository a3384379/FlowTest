# S60A — 自包含 Skill Evaluation

## 范围

从 S59D 合并后全绿 main 开始。先收口 S56 遗留的 Skill Evaluation Assets 技术债：
旗舰 Skill 可独立复制安装并聚合既有 Golden 标注，不依赖 FlowTest 后端包或源码路径。
本阶段不改变评分标准、MCP 权限、Preview 边界、数据库或产品生命周期。

S60 后续再补齐实际工具适配和四个 Skill：Project Onboarding、Complete Coverage、Change-aware
Regression、Triage and Repair。当前 MCP 没有 Repair/Maintenance 专用工具，不在文档中虚构工具。
Provider Marketplace、MCP Federation、额外语言、Property Testing、流量录制仍是后续评估。

## 包结构与维护源

旗舰包版本升级 rc.2；原 rc.1 Manifest 仍可解析。Evaluation 新增可选的强类型 Runtime 声明，标明
Python 版本、CLI、依赖、来源清单与 `committed_annotations_only` 范围。

- `evals/evaluate.py`：独立 CLI；输出指标，或核对 Baseline。
- `evals/v6_evaluation.py`：从后端唯一源生成，禁止手工维护第二套评分逻辑。
- `evals/annotations.json` / `baseline.json`：原模型无关 Golden 标注与基线。
- `evals/fixtures/`：静态 Golden 资产，不执行 Java 或 SQL。
- `evals/source-map.json`：生成文件的仓库来源清单；运行时不解析这些仓库路径。
- `evals/requirements.txt`：显式 Python 库依赖；首次安装需要包源或缓存。

`scripts/build_skill_evaluation.py --check` 与自动测试逐文件比较内容，阻止生成副本漂移，不重复计算 SHA。
Manifest 路径必须是规范包内相对路径，拒绝绝对路径、URL 和目录穿越。

## 成功与失败语义

- 成功只表示既有标注集的聚合/硬门禁通过，不声称重新运行 Pytest、真实服务或 LLM 前向测试。
- `--check` 额外要求与已提交 Baseline 一致；改变信息性指标也会检测出 Baseline 漂移。
- 没有 `--check` 时，硬门禁失败仍退出非零；不能通过重新生成失败 Baseline 消除失败状态。
- 空证据、重复 Case、非法 Label、重复 JSON Key、超限或无效输入均失败关闭。
- 错误输出不回显输入值或 ValidationError 详情；保留原始分子/分母硬门禁。
- 逻辑证据 URI 保留原测试/契约来源，不假装这些引用是本次独立执行的结果。

## 验证与退出条件

- 复制 Skill 到临时目录，在无 FlowTest 安装的独立 Python 环境中安装声明依赖并运行。
- 自动测试禁止导入 `app`、禁止网络连接；与后端标准聚合结果逐项比较。
- 失败、空证据、重复/无效输入、错误基线、CLI 输出和旧 Manifest 兼容回归。
- 稳定后一次集中 Backend / Frontend 检查；正常 PR 复审及路径选定 Required Gate。
- 本 PR 无产品 HTTP/UI 行为变化，不为评测包重建本地 Compose；远程 Compose 若被 Required Gate
  选中，沿用现有自动化，不修改门禁控制器。无公司 Windows 实机或其他实机验收要求。

当前尚未完成 PR 复审与远程门禁，不能标记 S60 或 S60A 已全部闭环。

## 本地集中验收

- Backend：Format / Ruff / mypy 全绿；1154 passed / 4 skipped，覆盖率 91.07%。
- Frontend：Format / ESLint / TypeScript / Build 全绿；238 passed，分支覆盖率 80.30%。
- 新增 22 项 S60A 用例；与旧 S56 兼容用例同批通过。
- Skill 格式校验、生成源一致性校验通过；仓库脚本单独 Ruff / mypy 通过。
- 独立 Python 3.13.15 环境仅安装 Pydantic 2.13.5 及其依赖，确认 `app` 不可导入；
  复制后的最终包 `evals/evaluate.py --check` 通过。首次安装下载依赖，运行不需要网络或服务凭据。

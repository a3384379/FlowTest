# 独立 Golden 评测

本 Skill 包携带 `evals/annotations.json`、`baseline.json`、Golden Fixtures、评分模型和 CLI；
复制整个 Skill 目录后即可运行，不需要 FlowTest 源码、数据库、服务凭据或后端安装。
运行时需要 Python 3.13 与 `evals/requirements.txt` 声明的 Pydantic 2；首次安装需要包源或本地 wheel
缓存。依赖就绪后，评测不访问网络。

## 独立运行

在复制后的 Skill 目录中，为评测创建独立虚拟环境（不要复用生产环境）：

```bash
uv venv --python 3.13 .eval-venv
uv pip install --python .eval-venv/bin/python -r evals/requirements.txt
.eval-venv/bin/python evals/evaluate.py --check
.eval-venv/bin/python evals/evaluate.py
```

Windows 的 Python 路径使用 `.eval-venv/Scripts/python.exe`。可用 `--annotations`、`--baseline`
显式指定另一组输入；`--output` 输出指标 JSON，不能与 `--check` 混用。无参数输出指标；硬门禁失败仍
返回非零。`--check` 还要求指标与提交的 Baseline 完全一致。

## 结果的含义与限制

这是对**既有标注**的确定性聚合，不是 LLM 前向测试，也不会执行后端 Pytest、Java 源码或 SQL。
PASS 仅表示标注有效、Baseline 一致、标注集的硬门禁通过，不表示当前部署已经通过安全或发布验收。
Fixtures 仅作为静态输入交付，不自动编译或执行。

`source-map.json` 记录包内副本对应的仓库来源，来源路径不参与独立运行。
标注中的 `pytest://`、`contract://`、`operation://` 等引用是逻辑证据标识，不是本地文件路径；
它们保留原标注的来源与版本，不能当作本次重跑测试的证据。需要重新验证原结论时，应在授权仓库运行
对应测试并审核标注，不能只修改标签使门禁变绿。

只报告该集合的分子、分母。展示值可舍入，硬门禁直接比较原始分子/分母；空分母为
`insufficient_evidence`，绝不转为成功。Operation/Binding Precision、Manual Edit Rate 和 Conflict Rate
是信息性指标，不是凭此可宣称的生产准确率。不得外推为“95% 准确率”。

## 仓库维护

评分模型的唯一维护源是 `backend/app/domain/v6_evaluation.py`。包内模型、标注、Baseline 与 Fixtures
由仓库构建脚本同步，不直接修改生成副本：

```bash
python3 scripts/build_skill_evaluation.py
python3 scripts/build_skill_evaluation.py --check
uv run --project backend python scripts/evaluate_v6_core.py --check
```

构建检查比较文件内容，不重复计算 SHA。更改源后再生成并审核差异；独立运行不需要以上构建脚本。

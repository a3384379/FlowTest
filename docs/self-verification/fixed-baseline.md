# 固定基准 core-v1

`selftest/packs/core-v1` 是独立的固定基准包，批次类型为 `fixed_baseline`。它不调用 MCP 生成器，也不计入 MCP 生成闭环完成率。`manifest.json` 固定其余三个 JSON 文档的规范 SHA-256；加载时检查文件集合、场景顺序、摘要和预算。黄金期望单独存放于 `expectations.json`，不得从本次执行结果生成或修改。

## 场景与黄金结果

| 场景                     | 原始执行 | 独立请求期望                                                                          |
| ------------------------ | -------- | ------------------------------------------------------------------------------------- |
| ST-CORE-echo-boundaries  | passed   | 依次回显整数 0、布尔 false、null、空串、中文；五次请求均具有合成 Authorization header |
| ST-CORE-business-failure | failed   | HTTP 200；`assert_business` / main / `WORKFLOW_ASSERTION_FAILED`；期望 2、实际 1      |
| ST-CORE-timeout          | failed   | `request` / main / `NODE_TIMEOUT`；节点 1 秒、Mock 延迟 2 秒；一次请求                |
| ST-CORE-if               | passed   | 原生 4.0 if 只执行 true 区域；一次请求，branch=true                                   |
| ST-CORE-foreach          | passed   | 原生 4.0 foreach，依次发送 0、false、中文；三个完整迭代记录                           |
| ST-CORE-repeat           | passed   | 原生 4.0 repeat 两次；两个完整迭代记录                                                |
| ST-CORE-retry            | passed   | API 节点遇到 503 后重试一次取得 200；响应 request_count=2                             |
| ST-CORE-poll             | passed   | API 节点轮询三次后 request_count=3 满足条件                                           |

总计 18 个 Mock 请求。每图固定 10 个请求上限、30 秒运行上限；整包准入上限为 500 个请求、600 秒。整轮运行另有异步硬截止；清理在退出路径执行，清理失败或证据过期不能通过核验。测试计划层 `max_retries=0`，API 内的受控 retry 与 poll 不会被计划重跑掩盖。

## 完整入口

先由现有 bootstrap 提供隔离项目、环境、Service、普通编辑者身份、`read:execution` 只读证据身份及独立 Observer 凭据，再调用：

```python
from scripts.selftest.contracts import Builds
from scripts.selftest.fixed_baseline import execute_fixed_baseline

fixture_digest = binding.fixture_image_digest.removeprefix("sha256:")
result = await execute_fixed_baseline(
    api, reader, observer,
    project_id=str(installation.project_id),
    environment_id=str(installation.fixture_environment_id),
    service_id=str(installation.fixture_service_id),
    batch_key=batch_key, nonce=nonce,
    fixture_digest=fixture_digest,
    builds=Builds(
        runner=binding.candidate_image_digest,
        target=binding.candidate_image_digest,
        fixture=fixture_digest,
        verifier=verifier_identity,
    ),
    output_dir=output_dir,
)
```

`api` 是普通产品 REST 客户端；`reader` 是独立 `read:execution` 客户端；`observer` 的 `api_prefix=""`，连接隔离 Observer 监听器。入口自行注册各场景的响应序列与延迟，执行前从空 journal 冻结进程 epoch；自行安装、执行、采集、清理与核验，返回 `FixedResult(manifest, evidence, report, installation)`。中途失败时 installation 可以为空，report 为 blocked，不伪造成功回执。

`install_fixed_baseline` 可单独用于受信初始化，必须提供同一组 project/environment/service/batch/nonce。每次写入先保存 pending 意图；成功后保存结果。已确认结果可继续读取，不确定结果必须停止处理，不能重复创建或更换幂等键掩盖问题。输出目录和批次身份不符时拒绝续用。

## 安装协议

1. 使用公开 API 创建接口，记录实际 API ID、版本号、契约指纹；只替换固定图预先声明的逻辑接口引用。
2. 保存本地固定包预览，以公开 `workflows/native-import` 创建 draft，原生导出逐项读回，再发布并校验完整图、版本 ID、版本号和规范指纹。
3. 以真实已发布 Workflow 和环境为依赖，提交 Case/Suite 包 preview，冻结 preview fingerprint 后 apply。
4. 根据 apply 返回的 source→target ID 和版本映射读取真实已发布 Case/Suite，逐项校验引用。包里的 source UUID 是包内逻辑身份，不是对未来资源 ID 的预测。
5. 创建固定 Suite 计划，明确 `max_retries=0` 后正式运行。

现有 native-import 直接创建 draft，没有服务端 preview/review/apply 接口。本模块明确记录 `approval_kind=trusted_fixed_pack_initialization`、`server_review=false`，本地预览不会冒充人工审批或 ChangeSet。MCP 路线继续使用其现有真实提案和审批链。

## 独立观察与产物

执行前冻结的期望与绑定用于核对发布版本、Case、环境、运行项来源、API 绑定、全部执行尝试及具体失败位置。独立 Mock journal 逐项核对请求与响应值、类型、分支、迭代键、状态、认证 header 是否存在和请求总数；不扩大任意 header 或真实敏感值采集。foreach/repeat 还核对完整分页及迭代数量、状态。

输出包括 `manifest.json`、`installation.json`、`plan-run.json`、各场景原生预览与观测、写入回执、`cleanup.json`、`evidence.json`、`verification.json`，以及两个分别呈现原始执行和独立核验的 `execution.junit.xml`、`verification.junit.xml`。符合预期的负例保持原始 failed，不能被改写为 passed。

本地定向测试使用真实公开 REST、数据库、原生发布、资产包安装、计划执行器和独立 Mock ASGI app。隔离 Docker 验收另通过主运行器执行，实际命令、镜像和结果见[验证记录](validation.md)。本地产物仍为 local_untrusted，不授予 GitHub Required Gate。

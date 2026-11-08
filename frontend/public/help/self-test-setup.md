# FlowTest 自测环境接入与使用

适用于提供“质量中心 → 系统自测”的版本。环境接入由部署管理员完成，项目用户在接入后初始化模板并运行。

## 第一次使用

1. 打开“系统自测 → 配置自测环境”，复制当前项目接入清单。
2. 部署管理员准备隔离目标并完成下方登记，启动执行代理 H 和独立核验代理 O。
3. 在页面点击“重新检查接入”，选择出现的自测绑定。
4. 点击“初始化自测”，选择模板，检查预检结果并确认安装。
5. 安装就绪后，固定基准模式选择“运行固定基准”；MCP 模式先创建生成任务，再按已有审核流程审核并发布 Workflow 与 Case，最后执行已发布产物。
6. 从真实批次中的执行链接查看报告。原始执行结果、独立核验和生成来源分别保留。

绑定已登记并不等于任务已运行或核验通过。真实宿主/LLM 需要额外的宿主、模型和预算授权；确定性 MCP 不调用模型。

## 绑定在哪里登记

登记位置是 **运行 FlowTest API 的部署环境**：

- Docker Compose / Full / Compact：向 API 服务的 `environment` 显式传入配置，再按该安装实际使用的 Compose 参数重建 API 服务。宿主机 `.env` 只负责 Compose 变量替换，新增变量不会自动进入容器。
- 源码 / Standalone：在启动脚本或服务管理器中配置 API 进程的环境变量，再重启 API。自测配置读取进程环境；使用环境文件时，需要启动器显式加载并导出变量，不能只依赖普通应用配置对 `.env` 的读取。
- 页面中的系统管理员账号与服务器部署权限是两回事；网页提供接入清单和状态检查，绑定和代理信任由部署配置决定。

最少需要：

| 配置                                      | 内容                                                  |
| ----------------------------------------- | ----------------------------------------------------- |
| `FLOWTEST_SELFTEST_BINDINGS`              | 已核实的目标与隔离信息组成的 JSON 数组                |
| `FLOWTEST_SELFTEST_PRINCIPALS`            | H/O 的公钥、身份、项目/绑定范围和能力组成的 JSON 数组 |
| `FLOWTEST_FEATURE_QUALITY_CENTER_ENABLED` | `true`，启用质量中心                                  |

Compose 传入方式示例如下。**先准备实际的两个 JSON 数组**，该片段只负责传入配置，不创建目标或代理。服务名和其它文件、环境参数沿用当前安装。

```yaml
services:
  backend:
    environment:
      FLOWTEST_FEATURE_QUALITY_CENTER_ENABLED: 'true'
      FLOWTEST_SELFTEST_BINDINGS: '${FLOWTEST_SELFTEST_BINDINGS:?请配置绑定 JSON 数组}'
      FLOWTEST_SELFTEST_PRINCIPALS: '${FLOWTEST_SELFTEST_PRINCIPALS:?请配置代理公钥 JSON 数组}'
```

### 绑定内容

每条绑定需要独立 UUID 和名称，`allowed_project_ids` 必须包含页面显示的当前项目 ID。目标实例的项目、组织、用户 ID 使用目标实例中的实际值。

其余必需字段：

- `runner_instance_id`、`target_instance_id`：执行实例与被测实例身份。
- `target_display`、`fixture_display`、`target_base_url`、`fixture_base_url`：已核实的目标与 Mock 地址。
- `target_project_id`、`target_organization_id`、`target_user_id`：目标侧的合成资源范围。
- `builds`：`runner`、`target`、`fixture`、`verifier` 的实际构建身份。
- `environment_fingerprint`、`isolation_fingerprint`：管理员核实后的 SHA-256 身份摘要。
- `non_production`、`isolated`、`outbound_authorized`：按实际检查结果配置，勾选或填写字段本身不能证明隔离成立。
- `runtime_profile`：当前部署形态；`agent_id`、`observer_id` 对应登记的代理 principal ID。

完整严格模型在源码 `backend/app/core/self_tests.py` 的 `SelfTestBinding`；额外字段会被拒绝。重新构建后需重新核实身份，不覆盖旧批次的冻结证据。

### 代理内容

H/O 使用不同密钥与身份。每个 principal 包含 `id`、`issuer`、`subject`、`audience`、`public_key`、`allowed_project_ids`、`allowed_binding_ids` 和 `capabilities`。

- H（执行代理）：确定性接入需要 `install` 与 `deterministic_mcp` 能力，负责安装及生成。
- O（独立核验代理）：能力仅为 `verify`，不能同时兼任安装或生成身份。
- 私钥、令牌和密码由部署端保管，不放入绑定配置、项目接入清单或浏览器。
- 本地配置使用 `trusted_verifier=false`，不填写 CI run/attempt，不通过网页或本地结果声明正式门禁通过。

登记公钥后还需启动对应代理进程；`available` 来自代理的实际登记与续租。登记过期时检查进程、授权范围和签名身份，再刷新页面。

## 源码环境中的隔离试用

仓库已有隔离启动器，可创建独立的 A/B/Mock 和 H/O。它会建立新的合成项目，**不会向当前日常项目自动添加绑定**。请使用该环境输出的项目和页面地址；生产或日常安装应由部署管理员按实际身份登记。

从对应版本的仓库根目录执行，先将三个变量替换为本轮全新目录及已存在的本地 FlowTest runtime 镜像。目录不得复用失败批次；私有状态目录应位于受保护的本地位置。

```sh
STACK='/absolute/path/to/new-selftest-stack'
STATE='/absolute/path/to/new-selftest-agent-state'
RUNTIME_IMAGE='your-local-flowtest-runtime:tag'

PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.local_stack start \
  --directory "$STACK" --runtime-image "$RUNTIME_IMAGE"
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.product_setup \
  --directory "$STACK" --state-directory "$STATE"
```

`product_setup` 只配置经 ownership 核实的隔离 runner；它生成 `public-settings.json`、`agent-config.json` 和 H/O 的私有运行时文件，不启动模型宿主。

在两个独立终端中启动代理，二者使用同一份配置和任务目录：

```sh
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.product_agent \
  --directory "$STACK" --state-directory "$STATE/tasks" \
  --config "$STATE/agent-config.json" --role harness --review-mode human \
  --timeout-seconds 1800
```

```sh
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.product_agent \
  --directory "$STACK" --state-directory "$STATE/tasks" \
  --config "$STATE/agent-config.json" --role observer --timeout-seconds 1800
```

代理命令有界运行，超时后按原配置重新连接并核对状态。MCP 提案通过现有页面人工审核，核验由独立 O 完成。

## 常见阻断

- **当前项目无绑定**：核对配置是否进入 API 进程、是否已重启、`allowed_project_ids` 是否包含当前项目。其它项目的绑定不会自动出现。
- **已登记但没选中**：返回页面，在“自测绑定”下拉框选择后再初始化。
- **H/O 未登记或已过期**：检查对应代理进程、公钥、issuer/subject/audience、项目和 binding 范围。
- **初始化或执行不可用**：核对项目编辑/执行权限、安装是否就绪及服务端原因码。接入指南可阅读，但不会授予写入权限。
- **读取失败**：保留页面上的错误与 Trace ID；读取失败不能当作“没有配置”。
- **没有生成进度或报告**：先创建真实批次，MCP 审核、发布、执行和核验分别完成后才会出现相应结果。

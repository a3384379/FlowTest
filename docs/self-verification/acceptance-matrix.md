# 自测验收实施与证据账本

本账本保留六份 v2 附件的全部 94 个父 ID, 拆为独立变体。实施、本地检查、部署 profile 验收分别记录; 单元/ASGI 通过不能升级为真实部署验收。完整机器记录及六附件 SHA-256 见 [acceptance-matrix.json](acceptance-matrix.json)。

每批最多 500 次目标请求、600 秒、递归深度 1。F/C/S 分别验收; 真实 Host 缺席时为 NOT_RUN / WAITING_FOR_HOST。历史子集证据不用于当前构建放行。

| 正式 ID | 阶段 | 优先级 | 实施 | 独立变体 |
| --- | --- | --- | --- | --- |
| ST-INIT-001 | S1 | P0 | implemented | clean_install (not_run) |
| ST-INIT-002 | S1 | P0 | implemented | same_key_reinstall (not_run)、new_run (not_run) |
| ST-INIT-003 | S4 | P1 | implemented | concurrent_install (product_acceptance_pass)、partial_resume (product_acceptance_pass)、unknown_mutation (product_acceptance_pass) |
| ST-INIT-004 | S1 | P0 | implemented | wrong_target (not_run)、drift (not_run)、unauthorized_binding (not_run) |
| ST-API-001 | S1 | P0 | implemented | login (product_acceptance_pass)、refresh (product_acceptance_pass)、logout (product_acceptance_pass)、expired (product_acceptance_pass)、invalid (product_acceptance_pass) |
| ST-API-002 | S2 | P0 | implemented | viewer_write (product_acceptance_pass)、nonmember (product_acceptance_pass)、cross_organization (product_acceptance_pass) |
| ST-API-003 | S1 | P0 | implemented | project_create_read_update (product_acceptance_pass)、folder_create_read_update (product_acceptance_pass)、environment_create_read_update_delete (product_acceptance_pass) |
| ST-API-004 | S1 | P0 | implemented | api_create_edit_publish (product_acceptance_pass)、historical_version (product_acceptance_pass)、current_drift (product_acceptance_pass) |
| ST-API-005 | S1 | P0 | implemented | extract_to_request (product_acceptance_pass)、per_batch_marker (product_acceptance_pass) |
| ST-API-006 | S1 | P0 | implemented | header_precedence (product_acceptance_pass)、case_insensitive (product_acceptance_pass)、auth_suppression (product_acceptance_pass) |
| ST-API-007 | S1 | P0 | implemented | zero (product_acceptance_pass)、false (product_acceptance_pass)、empty (product_acceptance_pass)、null (product_acceptance_pass)、chinese (product_acceptance_pass)、nested (product_acceptance_pass)、omitted (product_acceptance_pass) |
| ST-API-008 | S5 | P1 | implemented | upload (incomplete)、download_hash (incomplete)、cleanup (incomplete) |
| ST-API-009 | S1 | P0 | implemented | workflow_publish (product_acceptance_pass)、historical_version (product_acceptance_pass)、draft_conflict (product_acceptance_pass) |
| ST-API-010 | S1 | P0 | implemented | case_suite_plan (product_acceptance_pass)、exact_nonempty_expansion (product_acceptance_pass) |
| ST-API-011 | S1 | P0 | implemented | unauthorized_401 (product_acceptance_pass)、forbidden_403 (product_acceptance_pass)、validation_422 (product_acceptance_pass) |
| ST-API-012 | S1 | P0 | implemented | business_failure_http200 (product_acceptance_pass) |
| ST-ENG-001 | S1 | P0 | implemented | comparison (product_acceptance_pass)、schema (product_acceptance_pass)、header (product_acceptance_pass)、json (product_acceptance_pass)、file (product_acceptance_pass) |
| ST-ENG-002 | S1 | P0 | implemented | wrong_assertion (product_acceptance_pass)、correct_assertion (product_acceptance_pass) |
| ST-ENG-003 | S1 | P0 | implemented | if_hit (product_acceptance_pass)、if_miss (product_acceptance_pass)、switch_case (product_acceptance_pass)、switch_default (product_acceptance_pass) |
| ST-ENG-004 | S1 | P0 | implemented | foreach (product_acceptance_pass)、repeat (product_acceptance_pass)、while (product_acceptance_pass)、empty (product_acceptance_pass)、min_items (product_acceptance_pass) |
| ST-ENG-005 | S5 | P1 | implemented | break (product_acceptance_pass)、continue (product_acceptance_pass)、return (product_acceptance_pass)、nested_scope (product_acceptance_pass) |
| ST-ENG-006 | S2 | P0 | implemented | input_not_array (product_acceptance_pass)、min_items (product_acceptance_pass)、max_loops (product_acceptance_pass) |
| ST-ENG-007 | S1 | P0 | implemented | retry_503_503_200 (product_acceptance_pass) |
| ST-ENG-008 | S2 | P0 | implemented | retry_exhausted (product_acceptance_pass)、default_5xx (product_acceptance_pass)、explicit_status (product_acceptance_pass) |
| ST-ENG-009 | S1 | P0 | implemented | submit_once (product_acceptance_pass)、poll_twice (product_acceptance_pass) |
| ST-ENG-010 | S2 | P0 | implemented | poll_terminal_failure (product_acceptance_pass) |
| ST-ENG-011 | S2 | P0 | implemented | poll_attempt_budget (product_acceptance_pass)、poll_time_budget (product_acceptance_pass) |
| ST-ENG-012 | S1 | P0 | implemented | node_timeout (product_acceptance_pass) |
| ST-ENG-013 | S5 | P1 | implemented | try_catch (product_acceptance_pass)、try_unmatched (product_acceptance_pass)、finally_failure (product_acceptance_pass) |
| ST-ENG-014 | S2 | P0 | implemented | main_and_cleanup_failure (product_acceptance_pass) |
| ST-ENG-015 | S5 | P1 | implemented | parallel_vars (product_acceptance_pass)、parallel_cookies (incomplete)、concurrency_bound (product_acceptance_pass) |
| ST-ENG-016 | S5 | P1 | implemented | subflow_pin (product_acceptance_pass)、data_rows (product_acceptance_pass) |
| ST-RUN-001 | S2 | P0 | implemented | manual (incomplete)、ci (incomplete) |
| ST-RUN-002 | S2 | P0 | implemented | same_key (incomplete)、same_key_changed (incomplete)、pending_conflict (incomplete)、recovery_query (incomplete) |
| ST-RUN-003 | S2 | P0 | implemented | queued_cancel (incomplete)、running_cancel (incomplete)、force_cancel (incomplete)、cleanup_policy (incomplete) |
| ST-RUN-004 | S5 | P1 | implemented | double_claim (incomplete)、duplicate_delivery (incomplete)、worker_death (incomplete)、recovery (incomplete) |
| ST-RUN-005 | S2 | P0 | implemented | observer_deadline (incomplete)、observer_crash (incomplete)、watchdog_cleanup (incomplete) |
| ST-RUN-006 | S2 | P0 | implemented | environment_drift (incomplete)、unpinned_api_drift (incomplete)、pinned_api (incomplete) |
| ST-SEC-001 | S2 | P0 | implemented | readonly_scope (not_run)、cross_project (not_run)、cross_run (not_run)、revoked (not_run)、expired (not_run)、denied_mutations (not_run)、pagination (not_run) |
| ST-SEC-002 | S4 | P0 | implemented | owner_self_signed (incomplete)、editor_self_signed (incomplete) |
| ST-SEC-003 | S2 | P0 | implemented | credential_separation (product_acceptance_pass)、secret_writeonly (product_acceptance_pass)、no_export (product_acceptance_pass)、default_redaction_policy (product_acceptance_pass) |
| ST-SEC-004 | S2 | P0 | implemented | a_b_isolation (not_run)、two_batch_isolation (not_run)、recursive_target (not_run)、wrong_target (not_run) |
| ST-CAN-001 | S1 | P0 | implemented | missing (not_run)、duplicate (not_run)、zero (not_run)、required_subset (not_run) |
| ST-CAN-002 | S1 | P0 | implemented | quarantined (not_run)、skipped (not_run)、parent_passed_child_running (not_run)、junit_zero (not_run) |
| ST-CAN-003 | S2 | P0 | implemented | missing_page (not_run)、truncated (not_run)、missing_receipt (not_run)、missing_attempt (not_run)、digest_mismatch (not_run) |
| ST-CAN-004 | S2 | P0 | implemented | build (not_run)、manifest (not_run)、ci_attempt (not_run)、nonce_expiry (not_run)、replay (not_run)、seal_idempotent (not_run)、seal_conflict (not_run)、cancelled_revival (not_run) |
| ST-CAN-005 | S1 | P0 | implemented | wrong_code (not_run)、wrong_node (not_run)、wrong_phase (not_run)、timeout (not_run)、unexecuted (not_run) |
| ST-GUI-001 | S4 | P1 | implemented | setup_preview (not_run)、conflict (not_run)、confirmation (not_run)、duplicate_buttons (not_run) |
| ST-GUI-002 | S4 | P1 | implemented | native_navigation (incomplete)、review (incomplete)、publish (incomplete)、run (incomplete) |
| ST-GUI-003 | S4 | P1 | implemented | raw_failed_matched (not_run)、missing_observer (not_run)、source_scope (not_run)、host_not_run (not_run)、expiry (not_run) |
| ST-CI-001 | S1 | P0 | implemented | dual_junit (not_run)、local_artifacts (not_run)、remote_artifacts (not_run) |
| ST-CI-002 | S3 | P0 | implemented | exact_sha (not_run)、trusted_publisher (not_run)、untrusted_no_gate (not_run) |
| ST-CI-003 | S3 | P1 | implemented | risk_profiles (not_run)、coverage_floor (not_run) |
| ST-RET-001 | S4 | P1 | implemented | success_cleanup (not_run)、failure_cleanup (not_run)、cancel_cleanup (not_run)、retention (not_run)、expiry (not_run)、foreign_key (not_run) |
| ST-MCP-001 | S1 | P0 | implemented | stdio_child (product_acceptance_pass)、discovery (product_acceptance_pass)、call (product_acceptance_pass)、close (product_acceptance_pass) |
| ST-MCP-002 | S1 | P0 | implemented | http_socket (product_acceptance_pass)、stateful (not_run)、stateless (not_run) |
| ST-MCP-003 | S1 | P0 | implemented | full_catalog (product_acceptance_pass)、schema (product_acceptance_pass)、pagination (product_acceptance_pass)、unsafe_tool_absent (not_run) |
| ST-MCP-004 | S1 | P0 | implemented | unknown_tool (product_acceptance_pass)、bad_jsonrpc (product_acceptance_pass)、bad_params (product_acceptance_pass)、oversized (product_acceptance_pass) |
| ST-MCP-005 | S1 | P0 | implemented | business_error_under_http200 (product_acceptance_pass)、diagnostics (product_acceptance_pass) |
| ST-MCP-006 | S1 | P0 | implemented | two_principals (product_acceptance_pass)、no_token (product_acceptance_pass)、concurrent_http (product_acceptance_pass) |
| ST-MCP-007 | S2 | P0 | implemented | missing_scope (product_acceptance_pass)、cross_org (product_acceptance_pass)、revoked (product_acceptance_pass)、expired (product_acceptance_pass)、inactive (product_acceptance_pass)、token_kind (product_acceptance_pass) |
| ST-MCP-008 | S2 | P0 | implemented | timeout (product_acceptance_pass)、pipe_break (product_acceptance_pass)、socket_break (product_acceptance_pass)、server_crash (product_acceptance_pass)、unknown_mutation (product_acceptance_pass) |
| ST-MCP-009 | S1 | P0 | implemented | locked_sdk (product_acceptance_pass)、modern_protocol (product_acceptance_pass)、legacy_protocol (product_acceptance_pass)、unsupported_protocol (product_acceptance_pass) |
| ST-MCP-010 | S2 | P0 | implemented | resources (product_acceptance_pass)、prompts (product_acceptance_pass)、inspect_readonly (product_acceptance_pass)、untrusted_strings (product_acceptance_pass) |
| ST-MCP-011 | S1 | P0 | implemented | frozen_contract (product_acceptance_pass)、fresh_design (product_acceptance_pass) |
| ST-MCP-012 | S2 | P0 | implemented | contract_delta (product_acceptance_pass)、regenerate_delta (product_acceptance_pass)、preview_freeze (product_acceptance_pass) |
| ST-MCP-013 | S2 | P0 | implemented | empty_design (product_acceptance_pass)、empty_cases (product_acceptance_pass)、needs_review (product_acceptance_pass)、truncated (product_acceptance_pass)、coverage_missing (product_acceptance_pass) |
| ST-MCP-014 | S1 | P0 | implemented | missing_assertion (product_acceptance_pass)、wrong_field (product_acceptance_pass)、wrong_operator (product_acceptance_pass)、expected_from_actual (product_acceptance_pass) |
| ST-MCP-015 | S1 | P0 | implemented | dependency (product_acceptance_pass)、zero (not_run)、false (not_run)、empty (not_run)、null (not_run)、auth (product_acceptance_pass)、negative_status (not_run) |
| ST-MCP-016 | S2 | P0 | implemented | prompt_injection (product_acceptance_pass)、scope (product_acceptance_pass)、target (product_acceptance_pass)、secret (product_acceptance_pass)、approval (product_acceptance_pass) |
| ST-MCP-017 | S1 | P0 | implemented | dry_run (product_acceptance_pass)、pending (product_acceptance_pass)、persist (product_acceptance_pass)、idempotent_replay (product_acceptance_pass) |
| ST-MCP-018 | S1 | P0 | implemented | machine_cannot_approve (product_acceptance_pass)、separate_reviewer (product_acceptance_pass) |
| ST-MCP-019 | S1 | P0 | implemented | low_risk_accept (product_acceptance_pass)、high_risk_approval (product_acceptance_pass) |
| ST-MCP-020 | S1 | P0 | implemented | quick_review_apply (not_run)、flowspec_review_apply (not_run)、draft_only (not_run) |
| ST-MCP-021 | S2 | P0 | implemented | stale_proposal (product_acceptance_pass)、stale_approval (product_acceptance_pass)、concurrent_accept (product_acceptance_pass)、partial_resume (product_acceptance_pass)、unknown_publish (product_acceptance_pass) |
| ST-MCP-022 | S2 | P0 | implemented | preview_authorized (product_acceptance_pass)、one_use (product_acceptance_pass)、budget (product_acceptance_pass)、cancel (product_acceptance_pass)、cleanup (product_acceptance_pass)、no_formal_run (product_acceptance_pass) |
| ST-MCP-023 | S1 | P0 | implemented | lifecycle (product_acceptance_pass)、suite_chain (product_acceptance_pass)、native_control_chain (product_acceptance_pass) |
| ST-MCP-024 | S1 | P0 | implemented | exact_source_chain (product_acceptance_pass)、suite_snapshot (product_acceptance_pass)、all_oracles (product_acceptance_pass) |
| ST-MCP-025 | S1 | P0 | implemented | business_fault (product_acceptance_pass)、dependency_fault (product_acceptance_pass)、auth_fault (product_acceptance_pass)、exact_canary (product_acceptance_pass) |
| ST-MCP-026 | S1 | P0 | implemented | delete_assertion (not_run)、delete_case (not_run)、delete_receipt (not_run)、delete_attempt (not_run)、delete_page (not_run)、old_run (not_run) |
| ST-MCP-027 | S2 | P0 | implemented | readonly_projection (not_run)、credential_ref (product_acceptance_pass)、export_secret_boundary (product_acceptance_pass) |
| ST-MCP-028 | S3 | P0 | implemented | trusted_ci_route (not_run)、subset_policy (not_run)、live_not_run (not_run) |
| ST-MCP-029 | S3 | P0 | implemented | live_host_new_design (not_run)、real_model (not_run)、skill_version (not_run)、all_calls (not_run) |
| ST-MCP-030 | S3 | P0 | implemented | missing_host (not_run)、missing_model (not_run)、missing_budget (not_run)、no_replay_substitution (not_run) |
| ST-MCP-031 | S3 | P0 | implemented | frozen_tasks (not_run)、all_attempts (not_run)、quality_rubric (not_run)、no_best_of_n (not_run) |
| ST-MCP-032 | S3 | P0 | implemented | call_budget (not_run)、time_budget (not_run)、cost_budget (not_run)、interruption (not_run)、unknown_cost (not_run) |
| ST-MCP-033 | S3 | P0 | implemented | live_injection (not_run)、server_scope (not_run)、target_allowlist (not_run) |
| ST-MCP-034 | S3 | P0 | implemented | known_fault (not_run)、diagnosis (not_run)、reviewed_repair (not_run)、retain_failure (not_run) |
| ST-MCP-035 | S3 | P0 | implemented | human_edit_diff (not_run)、first_pass (not_run)、assisted (not_run) |
| ST-MCP-036 | S3 | P0 | implemented | contract_change (not_run)、skill_change (not_run)、catalog_change (not_run)、new_revision (not_run) |
| ST-MCP-037 | S2 | P0 | implemented | dual_scope (not_run)、four_scope_combinations (not_run)、organization (not_run)、version (not_run)、extra_fields (not_run)、fixture_auth (not_run) |
| ST-MCP-038 | S2 | P0 | implemented | pure_compile (not_run)、no_assets (not_run)、no_execution (not_run)、reproducible (not_run) |
| ST-MCP-039 | S2 | P0 | implemented | all_oracles (not_run)、mutations (not_run)、expected_statuses (not_run)、version_pin (not_run)、null_omit (not_run)、regions4 (product_acceptance_pass)、unsupported (not_run) |
| ST-MCP-040 | S2 | P0 | implemented | slot_real_published (incomplete)、foreign (incomplete)、unpublished (incomplete)、drift (incomplete)、schema_skill_sync (not_run) |

本地检查(不代表部署 profile 已通过):

- `targeted-expansion-203`: asgi_integration / passed; 203项本地单元及ASGI集成通过；不是Full/Compact/Standalone或模型Host验收。。日志: `/tmp/flowtest-selftest-expansion-final.log`。
- `typed-harness-eight-files`: static / passed; 8个H/O文件静态类型检查通过，不证明实际部署或远端Required Gate。。日志: `/tmp/flowtest-selftest-expansion-mypy.log`。
- `engine-additional-public-api-4`: asgi_integration / passed; 4项真实公开API→Case/Suite/Plan→engine本地ASGI通过；并发峰值来自独立ASGI目标计数器，不是部署M receipt或F/C/S完整验收。。日志: `/tmp/flowtest-engine-additional-final-v2.log`。
- `s4-core-actual-cli-counterexamples-16-readonly`: static / passed; 只读复核已有实际CLI基线exit0及16项副本变造的非零报告/具体finding；核对原始两SHA保持不变且无BATCH_EXPIRED遮掩。源为真实Standalone产品core8；这次检查没有重跑已过期CLI，不计Full/Compact/CI完整验收。。日志: `/private/tmp/flowtest-selftest-s4-core-negative-proof/check_readonly.log`。
- `mcp-negative-valid-write-22`: unit / passed; 22项具名测试, 包括真实SDK输入回执的独立O反证及被拒写请求符合实际ControlledWrite schema；此单元检查不替代部署profile。真正本地SDK34另存/tmp/flowtest-mcp-negative-valid-write-20261023/public，旧输入及失败产物均保留。。日志: `/tmp/flowtest-mcp-negative-valid-write-targeted.log`。
- `native-api-security-asgi-14`: asgi_integration / passed; 14项独立ASGI行为；生产bootstrap后仅公开API创建身份/组织/资产，原生协调器执行+RESpx wire复核；access过期仅推进JWT校验时钟，service token自然过期。无部署driver/native frozen pack交付，不提升F/C/S/CI验收。。日志: `/tmp/flowtest-selftest-native-api-security-regressions-final.log`。
- `s4-task-scoped-observer-asgi-86`: asgi_integration / passed; 86项组合；O先认领、部署principal+nonce+lease约束批次/Run/attempt/子执行；跨域/失效/取消拒绝；ST-MCP-023仅两项声明body.name投影。O无A广域reader/capture/writer/MCP凭据，poll不读private.env；不是profile负向部署验收。。日志: `/tmp/flowtest-selftest-task-scope-final-tests.log`。
- `s4-frontend-full-before-final-increments`: unit / passed; 已执行的前端整库1513 tests/193 files及格式/lint/build记录，发生于最后dispatch恢复/retention文案增量前。S4具名Vitest/MSW包括 keeps failed raw execution red alongside matched verification and verified report IDs；blocks conflicting previews and clears confirmation when choosing another pack；ignores a late generation receipt after the organization epoch changes；does not download a late artifact into another batch or keep its controls busy。此本地记录不等同当前HEAD最终gate或GUI部署验收。。日志: `/tmp/flowtest-s4-frontend-final-full.log`。
- `s4-retention-availability-asgi-61`: asgi_integration / passed; 61项本地/ASGI通过；公开上传真实artifact→真实native Plan→O封存后仅删除受控Local对象，Artifact行仍在时当前blocked/expired、sealed_verdict保持passed；暂不可用/总5秒或100次探测耗尽为unknown blocked。仅HEAD/open+fstat，不下载正文、不宣称重算SHA；S3分类为适配器单元测试，不提升F/C/S部署验收。。日志: `/tmp/flowtest-selftest-retention-targeted-final.log`。
- `sec-ci-implementation-221`: unit / passed; 221个既有单元/受控协议/Mock回归，复核实现映射，不新增纯镜像测试。隔离inventory、精确checkout、Required Gate旧SHA/attempt/受信publisher、风险路由和固定双JUnit已有代码；不代表远端GitHub或全profile验收。。日志: `/tmp/flowtest-selftest-sec-ci-implementation-checks.log`。
- `mcp-negative-strict-30`: unit / passed; 30项具名/参数化测试通过；先保留8个实际假绿表征，再修O必需字段、8类资产观察不得默认0、rejection counters必需、actual RPC全集精确计数和跨场景唯一性。真实锁定SDK34再次O0:/tmp/flowtest-mcp-negative-strict-20261023/public；baseline0+29个真正CLI篡改均指定finding/exit非零、未过期、原始SHA不变、双JUnit:/tmp/flowtest-mcp-negative-strict-proof-20261023/proof.json。loopback/private SQLite结果只属local_untrusted，不提升部署验收。。日志: `/tmp/flowtest-mcp-negative-strict-final-targeted.log`。
- `sec004-recursion-implementation-4`: asgi_integration / passed; 本轮 4 项具名/参数化检查通过；已有 root 90 项组合日志另见 /tmp/flowtest-s4-recursion-depth-targeted.log。ASGI 已有 ready installation 与合法 actor 仍拒绝嵌套自测且零 batch；受控容器 inventory 验证缺失/错误 B depth 被拒绝。不提升 F/C/S 部署或 CI 验收。。日志: `/tmp/flowtest-selftest-recursion-implementation-check.log`。
- `negative-governance-global-junit-64`: unit / passed; 64具名/参数化测试通过；6个global nonce/expiry/cleanup表征先失败后修，保证JSON非零时batch-global JUnit也失败。新实际loopback34/42均O0（/tmp/flowtest-mcp-{negative,governance}-global-junit-actual-20261023/public）；8个真正CLI writer副本baseline0/nonce1/expiry2/cleanup2，只有显式expiry过期，原5个artifactSHA不变，rawfailed保留:/tmp/flowtest-negative-global-junit-proof-20261023/proof.json。治理原baseline+34真正CLI严格反证另见/tmp/flowtest-mcp-governance-proof-20261023/proof.json。仍非部署profile证明。。日志: `/tmp/flowtest-selftest-negative-global-junit-targeted.log`。
- `mcp-deployment-adapter-47`: asgi_integration / passed; 47项本地检查：公开ASGI创建两组织/项目与限定机器身份、独立负向O分页、保留wire上的安全投影与重新封签反证；尚未运行部署34/42，不更新F/C/S验收。日志: `/tmp/flowtest-mcp-probe-integrated-targeted.log`。
- `mcp-source-mapping-206`: asgi_integration / passed; 206项既有编译/提案/Preview/生成/O/CI本地表征重跑，逐项映射实现能力；不等于新部署pack或94/341验收通过。日志: `/tmp/flowtest-selftest-mcp-source-mapping-targeted.log`。
- `host-adapter-assistance-history-106`: asgi_integration / passed; 106项Host具名/参数化行为通过：SDK2.2/合成CLI、真实公开提案审核发布与after Suite/Plan/Run、合成归档O修订核验、全任务分母、跨新grant连续attempt及O签名checkpoint。无模型调用；before seal fixture和真实模型/人工验收分开。。日志: `/tmp/flowtest-host-final-union.log`。
- `host-adapter-typed-30`: static / passed; 30个Host/入口文件mypy通过；Ruff format/check同时通过，7份Host JSONSchema已按当前typed合同重新导出并Draft2020校验。不是部署验收。。日志: `/tmp/flowtest-host-assisted-mypy-final.log`。
- `host-ci-complete-136`: asgi_integration / passed; 136项联合通过（123 Host含17独立诊断+13 CI probe包装），真实SDK/ASGI与合成进程、归档O/quality/history、sealed来源与预算反证。Model调用0；before seal/归档fixture不代表真实宿主或人工验收；CI包装归档时钟仅本地测试。。日志: `/tmp/flowtest-host-ci-complete-targeted.log`。
- `host-ci-typed-34`: static / passed; 34源码mypy通过，47源/测试Ruff format/check通过；11份Host/Diagnosis JSONSchema已按最终DTO导出并Draft2020校验，2文档格式和本地链接有效。非部署profile证据。。日志: `/tmp/flowtest-host-ci-final-mypy.log`。
- `engine-golden-native-asgi-9`: asgi_integration / passed; 9项：5场景真实公开API原生Case→Suite→Plan→Run、5目标请求，3raw passed+2raw failed均O matched；文件SHA/长度/JSON伪装及7错误下载/黄金反证。仅ASGI，所有新增部署profile仍NOT_RUN。。日志: `/tmp/flowtest-engine-golden-final-targeted.log`。
- `engine-golden-mock-40`: asgi_integration / passed; 全Mock40项2.34s；固定17bytes下载真实HTTP与独立二进制日志、预算/过期/JSON兼容；修前2例404日志另存。不等价部署profile。。日志: `/tmp/flowtest-engine-golden-mock-union.log`。
- `supplemental-native-asgi-7`: asgi_integration / passed; 7项7.20s，15冻结场景真实双ASGI公开Case/Suite/Plan/Run；同次证据5篡改均拒绝；ownedDockerabsence仅finalizer单测模拟，真实清理仍待profile。Expired明确unsupported，不同义invalid。。日志: `/tmp/flowtest-supplemental-targeted-final2.log`。
- `supplemental-native-o-compat-104`: asgi_integration / passed; 104项11.45s，旧native12与O兼容；未提升Full/Compact/Standalone验收。。日志: `/tmp/flowtest-supplemental-native-oracle-regression.log`。

原始执行、独立核验、完整性、来源信任及清理分开。完整父 ID 只有全部适用变体和 profile 的真实证据齐全才能关闭; 源矩阵的共同 profile 要求不能由局部列表缩减。`validation.md` 保持实际命令和发布门槛的独立记录。

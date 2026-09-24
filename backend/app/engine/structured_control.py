"""Bounded, scoped execution of versioned inline control regions."""

import asyncio
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import Protocol, cast, runtime_checkable

from pydantic import JsonValue

from app.engine.contracts import (
    ConditionLoopConfig,
    ControlSignalConfig,
    FailControlConfig,
    ForEachControlConfig,
    IfControlConfig,
    InlineControlBody,
    NodeStatus,
    ParallelBranch,
    ParallelControlConfig,
    RepeatControlConfig,
    ReturnControlConfig,
    StateUpdate,
    StepGroupControlConfig,
    SwitchControlConfig,
    TryCatch,
    TryControlConfig,
    ValueSource,
    VariableValueSource,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowPhase,
    WorkflowRegion,
    WorkflowRunStatus,
    parse_control_config,
)
from app.engine.control_conditions import evaluate_condition, strict_equal
from app.engine.results import NodeResult
from app.engine.scheduler import (
    NESTED_CHECKPOINT_PREFIX,
    CancellationToken,
    ExecutionContext,
    NodeExecutionError,
    NodeExecutor,
    NodeRunRecord,
    NodeStatusUpdate,
    WorkflowRunResult,
    WorkflowScheduler,
)
from app.engine.structured_values import resolve_value


def _instance_id(scope: tuple[str, ...], node_id: str) -> str:
    serialized = json.dumps((*scope, node_id), ensure_ascii=False, separators=(",", ":"))
    return f"{NESTED_CHECKPOINT_PREFIX}{hashlib.sha256(serialized.encode()).hexdigest()}"


def control_placeholder(node_id: str, variable: str) -> str:
    encoded = json.dumps((node_id, variable), ensure_ascii=False, separators=(",", ":"))
    return f"__FLOWTEST_CONTROL_{hashlib.sha256(encoded.encode()).hexdigest()[:24]}__"


class BranchScopedExecutor(NodeExecutor, Protocol):
    async def close(self) -> None: ...


@runtime_checkable
class BranchForkableExecutor(Protocol):
    def fork_branch(self) -> BranchScopedExecutor: ...


class StructuredControlRunner:
    def __init__(self, definition: WorkflowDefinition, executor: NodeExecutor) -> None:
        self._definition = definition
        self._executor = executor
        self._regions = {region.id: region for region in definition.regions}

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> NodeResult:
        config = parse_control_config(node)
        if isinstance(config, ControlSignalConfig):
            signal = "break" if node.capability_id == "flow.control.break" else "continue"
            return NodeResult(status=NodeStatus.PASSED, control_signal=signal)
        if isinstance(config, FailControlConfig):
            return NodeResult.failed(code=config.code, message=config.message)
        if isinstance(config, ReturnControlConfig):
            return self._return_result(config, context)
        if isinstance(config, TryControlConfig):
            return await self._execute_try(node, config, context)
        if isinstance(config, StepGroupControlConfig):
            return await self._run_selected(
                node, config.body, "body", config.inputs, context, {"kind": "group"}
            )
        if isinstance(config, ConditionLoopConfig):
            return await self._run_condition_loop(node, config, context)
        if isinstance(config, IfControlConfig):
            return await self._execute_if(node, config, context)
        if isinstance(config, SwitchControlConfig):
            return await self._execute_switch(node, config, context)
        if isinstance(config, ParallelControlConfig):
            return await self._execute_parallel(node, config, context)
        return await self._execute_fixed_loop(node, config, context)

    @staticmethod
    def _return_result(config: ReturnControlConfig, context: ExecutionContext) -> NodeResult:
        if not context.allow_return:
            raise NodeExecutionError(
                code="RETURN_OUTSIDE_CALL", message="Return 仅能结束当前子流程调用"
            )
        outputs = {name: resolve_value(source, context) for name, source in config.outputs.items()}
        return NodeResult(
            status=NodeStatus.PASSED,
            output={"return": outputs},
            control_signal="return",
            return_output=outputs,
        )

    async def _execute_parallel(
        self, node: WorkflowNode, config: ParallelControlConfig, parent: ExecutionContext
    ) -> NodeResult:
        active: dict[asyncio.Task[dict[str, JsonValue]], CancellationToken] = {}
        results: dict[int, dict[str, JsonValue]] = {}
        stopped = False
        next_index = 0
        root_token = parent.cancellation or CancellationToken()
        frozen_inputs = self._selector_context(config.inputs, parent).input_variables
        try:
            while next_index < len(config.branches) or active:
                next_index = self._start_parallel_branches(
                    config,
                    parent,
                    root_token,
                    frozen_inputs,
                    active,
                    next_index,
                    stopped=stopped,
                )
                if not active:
                    break
                done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    token = active.pop(task)
                    summary = await task
                    index = cast(int, summary["definition_index"])
                    results[index] = summary
                    stopped = (
                        stopped
                        or self._stop_parallel_on_failure(config, summary, active)
                        or (token.cancelled and root_token.cancelled)
                    )
        finally:
            for token in active.values():
                token.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
        branches = [
            results.get(index)
            or {
                "definition_index": index,
                "branch_id": branch.id,
                "status": "not_started",
                "test_verdict": "not_run",
                "outputs": {},
                "nodes": [],
            }
            for index, branch in enumerate(config.branches)
        ]
        failed = sum(item["status"] == "failed" for item in branches)
        cancelled = sum(item["status"] == "cancelled" for item in branches)
        output: dict[str, JsonValue] = {
            "join": "all",
            "started_count": sum(item["status"] != "not_started" for item in branches),
            "failed_count": failed,
            "cancelled_count": cancelled,
            "branches": cast(JsonValue, branches),
            "termination_reason": "cancelled"
            if root_token.cancelled
            else "failed"
            if failed
            else "cancelled"
            if cancelled
            else "completed",
        }
        if root_token.cancelled:
            return NodeResult(status=NodeStatus.CANCELLED, output=output)
        if failed or cancelled:
            return NodeResult.failed(
                code="PARALLEL_BRANCH_FAILED", message="并行分支未全部成功", output=output
            )
        verified = any(item["nodes"] for item in branches)
        return NodeResult(
            status=NodeStatus.PASSED,
            output=output,
            test_verdict="passed" if verified else "not_run",
        )

    def _start_parallel_branches(
        self,
        config: ParallelControlConfig,
        parent: ExecutionContext,
        root_token: CancellationToken,
        frozen_inputs: dict[str, JsonValue],
        active: dict[asyncio.Task[dict[str, JsonValue]], CancellationToken],
        next_index: int,
        *,
        stopped: bool,
    ) -> int:
        while (
            not stopped
            and not root_token.cancelled
            and next_index < len(config.branches)
            and len(active) < config.policy.concurrency
        ):
            branch = config.branches[next_index]
            token = CancellationToken(root_token)
            task = asyncio.create_task(
                self._run_parallel_branch(branch, frozen_inputs, parent, token, next_index)
            )
            active[task] = token
            next_index += 1
        return next_index

    @staticmethod
    def _stop_parallel_on_failure(
        config: ParallelControlConfig,
        summary: dict[str, JsonValue],
        active: dict[asyncio.Task[dict[str, JsonValue]], CancellationToken],
    ) -> bool:
        if summary["status"] != "failed" or config.policy.on_error != "stop_on_error":
            return False
        for token in active.values():
            token.cancel()
        return True

    async def _run_parallel_branch(
        self,
        branch: ParallelBranch,
        frozen_inputs: dict[str, JsonValue],
        parent: ExecutionContext,
        token: CancellationToken,
        index: int,
    ) -> dict[str, JsonValue]:
        body = branch.body
        if not isinstance(body, InlineControlBody):
            raise NodeExecutionError(
                code="CONTROL_BODY_UNAVAILABLE", message="当前执行器不支持该控制体来源"
            )
        region = self._regions[body.region_id]
        scope = (*parent.checkpoint_scope, "region", region.id, "branch", branch.id)
        child = self._child_context(parent, scope)
        child.cancellation = token
        scoped_executor = (
            self._executor.fork_branch()
            if isinstance(self._executor, BranchForkableExecutor)
            else None
        )
        try:
            child.input_variables = self._condition_region_inputs(
                frozen_inputs, region.inputs, parent, child
            )
            result = await self._run_region(
                region, child, token, executor=scoped_executor or self._executor
            )
        except NodeExecutionError as error:
            return {
                "definition_index": index,
                "branch_id": branch.id,
                "status": "failed",
                "test_verdict": "failed",
                "error_code": error.code,
                "outputs": {},
                "nodes": [],
            }
        finally:
            if scoped_executor is not None:
                await scoped_executor.close()
        exports = (
            {name: resolve_value(source, child) for name, source in region.outputs.items()}
            if result.status is WorkflowRunStatus.PASSED
            else {}
        )
        return {
            "definition_index": index,
            "branch_id": branch.id,
            "status": result.status.value,
            "test_verdict": (
                "failed"
                if result.status is WorkflowRunStatus.FAILED
                else "not_run"
                if result.status is WorkflowRunStatus.CANCELLED
                else "passed"
                if result.records
                else "not_run"
            ),
            "outputs": exports,
            "nodes": [
                {
                    "node_id": item.node_id,
                    "instance_id": _instance_id(scope, item.node_id),
                    "status": item.status.value,
                    "error_code": item.error_code,
                }
                for item in result.records
            ],
        }

    async def _execute_fixed_loop(
        self,
        node: WorkflowNode,
        config: ForEachControlConfig | RepeatControlConfig,
        context: ExecutionContext,
    ) -> NodeResult:
        if isinstance(config, ForEachControlConfig):
            collection = resolve_value(config.collection, context)
            if not isinstance(collection, list):
                raise NodeExecutionError(
                    code="LOOP_INPUT_NOT_ARRAY",
                    message=f"循环节点 {node.name} 的集合必须是数组",
                )
            if len(collection) < config.min_items:
                raise NodeExecutionError(
                    code="LOOP_MIN_ITEMS_NOT_MET",
                    message=f"循环节点 {node.name} 的集合未达到最小项数",
                )
            items = deepcopy(collection)
        else:
            items = list(range(config.count))
        if len(items) > config.policy.max_iterations:
            raise NodeExecutionError(
                code="LOOP_LIMIT_EXCEEDED",
                message=f"循环节点 {node.name} 超过最大轮数",
            )
        if not isinstance(config.body, InlineControlBody):
            raise NodeExecutionError(
                code="CONTROL_BODY_UNAVAILABLE",
                message="当前执行器尚不支持该控制体来源",
            )
        region = self._regions[config.body.region_id]
        return await self._run_loop(node, config, items, region, context)

    async def _execute_if(
        self, node: WorkflowNode, config: IfControlConfig, parent: ExecutionContext
    ) -> NodeResult:
        selector = self._selector_context(config.inputs, parent)
        selected, trace = evaluate_condition(config.condition, selector)
        body = config.true_body if selected else config.false_body
        return await self._run_selected(
            node,
            body,
            "true" if selected else "false",
            config.inputs,
            parent,
            {"condition": selected, "condition_trace": cast(JsonValue, trace)},
        )

    async def _execute_switch(
        self, node: WorkflowNode, config: SwitchControlConfig, parent: ExecutionContext
    ) -> NodeResult:
        selector = self._selector_context(config.inputs, parent)
        actual = resolve_value(config.value, selector) if config.value is not None else None
        trace: list[dict[str, JsonValue]] = []
        for branch in config.branches:
            if config.mode == "value":
                if branch.match is None:
                    raise NodeExecutionError(
                        code="INVALID_CONTROL_CONFIG", message="分支缺少匹配值"
                    )
                expected = resolve_value(branch.match, selector)
                matched = strict_equal(actual, expected)
                trace.append(
                    {
                        "branch_id": branch.id,
                        "actual": actual,
                        "expected": expected,
                        "matched": matched,
                    }
                )
            else:
                if branch.condition is None:
                    raise NodeExecutionError(code="INVALID_CONTROL_CONFIG", message="分支缺少条件")
                matched, condition_trace = evaluate_condition(branch.condition, selector)
                trace.append(
                    {
                        "branch_id": branch.id,
                        "matched": matched,
                        "condition_trace": cast(JsonValue, condition_trace),
                    }
                )
            if matched:
                return await self._run_selected(
                    node,
                    branch.body,
                    branch.id,
                    config.inputs,
                    parent,
                    {"mode": config.mode, "actual": actual, "match_trace": cast(JsonValue, trace)},
                )
        default = config.default
        output: dict[str, JsonValue] = {
            "selected_branch_id": "default",
            "mode": config.mode,
            "actual": actual,
            "match_trace": cast(JsonValue, trace),
        }
        if default.behavior == "skip":
            output["reason"] = "no_match"
            return NodeResult(status=NodeStatus.PASSED, output=output, test_verdict="not_run")
        if default.behavior == "fail":
            return NodeResult.failed(
                code="SWITCH_NO_MATCH", message="没有匹配的分支", output=output
            )
        if default.body is None:
            raise NodeExecutionError(code="INVALID_CONTROL_CONFIG", message="默认分支缺少控制体")
        return await self._run_selected(
            node,
            default.body,
            "default",
            config.inputs,
            parent,
            {"mode": config.mode, "actual": actual, "match_trace": cast(JsonValue, trace)},
        )

    async def _run_selected(
        self,
        node: WorkflowNode,
        body: object,
        branch_id: str,
        inputs: dict[str, ValueSource],
        parent: ExecutionContext,
        details: dict[str, JsonValue],
    ) -> NodeResult:
        if not isinstance(body, InlineControlBody):
            raise NodeExecutionError(
                code="CONTROL_BODY_UNAVAILABLE", message="当前执行器不支持该控制体来源"
            )
        region = self._regions[body.region_id]
        scope = (*parent.checkpoint_scope, "region", region.id, "branch", branch_id)
        child = self._child_context(parent, scope)
        selector = self._selector_context(inputs, parent)
        child.input_variables = {
            **selector.input_variables,
            **{name: resolve_value(source, selector) for name, source in region.inputs.items()},
        }
        result = await self._run_region(region, child, parent.cancellation or CancellationToken())
        output: dict[str, JsonValue] = {
            "selected_branch_id": branch_id,
            "region_id": region.id,
            "region_status": result.status.value,
            "outputs": {
                name: resolve_value(source, child) for name, source in region.outputs.items()
            }
            if result.status is WorkflowRunStatus.PASSED
            else {},
            "nodes": [
                {
                    "node_id": record.node_id,
                    "instance_id": _instance_id(scope, record.node_id),
                    "status": record.status.value,
                    "error_code": record.error_code,
                }
                for record in result.records
            ],
            **details,
        }
        if result.status is WorkflowRunStatus.FAILED:
            return NodeResult.failed(
                code="CONTROL_BRANCH_FAILED", message="选中分支执行失败", output=output
            )
        if result.status is WorkflowRunStatus.CANCELLED:
            return NodeResult(status=NodeStatus.CANCELLED, output=output)
        return NodeResult(
            status=NodeStatus.PASSED,
            output=output,
            test_verdict="passed" if result.records else "not_run",
            control_signal=result.control_signal,
            return_output=result.return_output,
        )

    async def _execute_try(
        self, node: WorkflowNode, config: TryControlConfig, parent: ExecutionContext
    ) -> NodeResult:
        frozen_inputs = dict(self._selector_context(config.inputs, parent).input_variables)
        try_result: WorkflowRunResult | None = None
        catch_result: WorkflowRunResult | None = None
        finally_result: WorkflowRunResult | None = None
        original_error: dict[str, JsonValue] | None = None
        catch_error: dict[str, JsonValue] | None = None
        finally_error: dict[str, JsonValue] | None = None
        catch_id: str | None = None
        exports: dict[str, JsonValue] = {}
        try:
            try:
                try_result, exports = await self._run_try_region(
                    config.try_body, "try", frozen_inputs, parent
                )
                original_error = _first_region_error(try_result)
            except NodeExecutionError as error:
                original_error = {"code": error.code, "message": error.message}
            arm = _matching_catch(config.catches, original_error)
            if arm is not None:
                catch_id = arm.id
                try:
                    catch_result, catch_exports = await self._run_try_region(
                        arm.body,
                        f"catch:{arm.id}",
                        {**frozen_inputs, **exports},
                        parent,
                        error_values=original_error,
                    )
                    exports.update(catch_exports)
                    catch_error = _first_region_error(catch_result)
                except NodeExecutionError as error:
                    catch_error = {"code": error.code, "message": error.message}
        finally:
            try:
                finally_result = await self._run_finally_region(
                    config, frozen_inputs, exports, parent
                )
                if finally_result is not None:
                    finally_error = _first_region_error(finally_result)
            except NodeExecutionError as error:
                finally_error = {"code": error.code, "message": error.message}
        return _try_node_result(
            try_result,
            catch_result,
            finally_result,
            original_error,
            catch_error,
            finally_error,
            catch_id,
            config.expected_error_codes,
            exports,
            has_finally=config.finally_body is not None,
        )

    async def _run_try_region(
        self,
        body: object,
        role: str,
        frozen_inputs: dict[str, JsonValue],
        parent: ExecutionContext,
        *,
        error_values: dict[str, JsonValue] | None = None,
        cleanup: bool = False,
    ) -> tuple[WorkflowRunResult, dict[str, JsonValue]]:
        if not isinstance(body, InlineControlBody):
            raise NodeExecutionError(
                code="CONTROL_BODY_UNAVAILABLE", message="当前执行器不支持该控制体来源"
            )
        region = self._regions[body.region_id]
        scope = (*parent.checkpoint_scope, "region", region.id, role)
        child = self._child_context(parent, scope)
        child.error_variables = dict(error_values or {})
        child.input_variables = self._condition_region_inputs(
            frozen_inputs, region.inputs, parent, child
        )
        token = parent.cancellation or CancellationToken()
        if cleanup:
            child.request_budget = parent.cleanup_budget
            child.checkpoint_phase = WorkflowPhase.CLEANUP
            token = CancellationToken()
            child.cancellation = token
        result = await self._run_region(region, child, token)
        exports: dict[str, JsonValue] = {}
        for name, source in region.outputs.items():
            try:
                exports[name] = resolve_value(source, child)
            except NodeExecutionError:
                if result.status is WorkflowRunStatus.PASSED:
                    raise
        return result, exports

    async def _run_finally_region(
        self,
        config: TryControlConfig,
        frozen_inputs: dict[str, JsonValue],
        exports: dict[str, JsonValue],
        parent: ExecutionContext,
    ) -> WorkflowRunResult | None:
        if config.finally_body is None:
            return None
        if (
            parent.cancellation is not None
            and parent.cancellation.force_cancelled
            and self._definition.run_policy.force_cancel_skips_cleanup
        ):
            return None
        result, _ = await self._run_try_region(
            config.finally_body,
            "finally",
            {**frozen_inputs, **exports},
            parent,
            cleanup=True,
        )
        return result

    @staticmethod
    def _child_context(parent: ExecutionContext, scope: tuple[str, ...]) -> ExecutionContext:
        return ExecutionContext(
            workflow_variables=deepcopy(parent.workflow_variables),
            dataset_variables=deepcopy(parent.dataset_variables),
            runtime_variables=deepcopy(parent.runtime_variables),
            input_variables=deepcopy(parent.input_variables),
            loop_variables=deepcopy(parent.loop_variables),
            state_variables=deepcopy(parent.state_variables),
            error_variables=deepcopy(parent.error_variables),
            request_budget=parent.request_budget,
            cleanup_budget=parent.cleanup_budget,
            node_instance_budget=parent.node_instance_budget,
            leaf_semaphore=parent.leaf_semaphore,
            status_callback=parent.status_callback,
            checkpoint_scope=scope,
            checkpoint_phase=parent.checkpoint_phase,
            checkpoint_best_effort=parent.checkpoint_best_effort,
            nested_checkpoint_records=parent.nested_checkpoint_records,
            cancellation=parent.cancellation,
            allow_return=parent.allow_return,
        )

    def _selector_context(
        self, inputs: dict[str, ValueSource], parent: ExecutionContext
    ) -> ExecutionContext:
        selector = self._child_context(parent, parent.checkpoint_scope)
        selector.input_variables = {
            name: resolve_value(source, parent) for name, source in inputs.items()
        }
        outputs = cast(dict[str, JsonValue], parent.snapshot()["node_outputs"])
        for node_id, output in outputs.items():
            selector.record_output(node_id, deepcopy(output))
        return selector

    @staticmethod
    def _loop_inputs(
        inputs: dict[str, ValueSource],
        region_inputs: dict[str, ValueSource],
        parent: ExecutionContext,
        child: ExecutionContext,
    ) -> dict[str, JsonValue]:
        bound = {
            name: resolve_value(source, child if _is_loop_source(source) else parent)
            for name, source in inputs.items()
        }
        child.input_variables = deepcopy(bound)
        return deepcopy(
            {
                **bound,
                **{
                    name: resolve_value(
                        source,
                        child
                        if isinstance(source, VariableValueSource)
                        and source.scope in {"loop", "input"}
                        else parent,
                    )
                    for name, source in region_inputs.items()
                },
            }
        )

    async def _run_condition_loop(
        self, node: WorkflowNode, config: ConditionLoopConfig, parent: ExecutionContext
    ) -> NodeResult:
        if not isinstance(config.body, InlineControlBody):
            raise NodeExecutionError(
                code="CONTROL_BODY_UNAVAILABLE", message="当前执行器不支持该控制体来源"
            )
        region = self._regions[config.body.region_id]
        state = {
            name: deepcopy(resolve_value(source, parent)) for name, source in config.state.items()
        }
        selector = self._selector_context(config.inputs, parent)
        frozen_inputs = deepcopy(selector.input_variables)
        iterations: list[dict[str, JsonValue]] = []
        token = parent.cancellation or CancellationToken()
        for index in range(config.policy.max_iterations + 1):
            if token.cancelled:
                return NodeResult(
                    status=NodeStatus.CANCELLED,
                    output=_condition_loop_output(iterations, state, "cancelled"),
                )
            selector.state_variables = deepcopy(state)
            if node.capability_id == "flow.control.while":
                should_continue, trace = evaluate_condition(config.condition, selector)
                if not should_continue:
                    return _completed_condition_loop(iterations, state, "condition_false")
            else:
                trace = []
            if index >= config.policy.max_iterations:
                return NodeResult.failed(
                    code="LOOP_LIMIT_EXCEEDED",
                    message="条件循环达到最大轮数。退出条件仍未满足",
                    output=_condition_loop_output(iterations, state, "limit_exceeded"),
                )
            scope = (*parent.checkpoint_scope, "region", region.id, "iteration", str(index))
            child = self._child_context(parent, scope)
            child.loop_variables = {"index": index, "iteration": index + 1}
            child.state_variables = deepcopy(state)
            child.input_variables = self._condition_region_inputs(
                frozen_inputs, region.inputs, parent, child
            )
            result = await self._run_region(region, child, token)
            exports = self._collect(
                config,
                region,
                child,
                result.status,
                allow_missing=result.control_signal is not None,
            )
            iterations.append(
                {
                    "input_index": index,
                    "instance_path": list(scope),
                    "status": result.status.value,
                    "control_signal": result.control_signal,
                    "condition_trace": cast(JsonValue, trace),
                    "outputs": exports,
                    "nodes": [
                        {
                            "node_id": record.node_id,
                            "instance_id": _instance_id(scope, record.node_id),
                            "status": record.status.value,
                            "error_code": record.error_code,
                        }
                        for record in result.records
                    ],
                }
            )
            terminal = _condition_round_terminal(result, iterations, state)
            if terminal is not None:
                return terminal
            state = self._updated_state(config.update, state, child)
            exit_reason = _post_condition_exit(node, config, child, state, iterations[-1])
            if exit_reason is not None:
                return _completed_condition_loop(iterations, state, exit_reason)
        raise NodeExecutionError(code="INVALID_CONTROL_CONFIG", message="循环执行状态无效")

    @staticmethod
    def _condition_region_inputs(
        frozen: dict[str, JsonValue],
        region_inputs: dict[str, ValueSource],
        parent: ExecutionContext,
        child: ExecutionContext,
    ) -> dict[str, JsonValue]:
        child.input_variables = deepcopy(frozen)
        return deepcopy(
            {
                **frozen,
                **{
                    name: resolve_value(
                        source,
                        child
                        if isinstance(source, VariableValueSource)
                        and source.scope in {"input", "loop", "state", "error"}
                        else parent,
                    )
                    for name, source in region_inputs.items()
                },
            }
        )

    @staticmethod
    def _updated_state(
        updates: dict[str, StateUpdate],
        current: dict[str, JsonValue],
        context: ExecutionContext,
    ) -> dict[str, JsonValue]:
        pending = {
            name: _state_update_value(current[name], update, context)
            for name, update in updates.items()
        }
        return deepcopy({**current, **pending})

    async def _run_loop(
        self,
        node: WorkflowNode,
        config: ForEachControlConfig | RepeatControlConfig,
        items: list[JsonValue],
        region: WorkflowRegion,
        parent: ExecutionContext,
    ) -> NodeResult:
        if config.policy.concurrency > 1:
            return await self._run_parallel_loop(node, config, items, region, parent)
        iterations: list[dict[str, JsonValue]] = []
        token = parent.cancellation or CancellationToken()
        for index, item in enumerate(items):
            if token.cancelled:
                break
            summary, result = await self._run_iteration(
                node, config, items, region, parent, token, index, item, isolate=False
            )
            iterations.append(summary)
            if result.status is not WorkflowRunStatus.PASSED and config.policy.on_error == "stop":
                break
            if result.control_signal in {"break", "return"}:
                break
        failed = sum(item["test_verdict"] == "failed" for item in iterations)
        terminated = (
            "cancelled"
            if token.cancelled
            else (
                result.control_signal
                if iterations and result.control_signal in {"break", "return"}
                else "failed"
                if failed and len(iterations) < len(items)
                else "completed"
            )
        )
        output: dict[str, JsonValue] = {
            "input_count": len(items),
            "started_count": len(iterations),
            "completed_count": len(iterations),
            "passed_count": len(iterations) - failed,
            "failed_count": failed,
            "not_started_count": len(items) - len(iterations),
            "termination_reason": terminated,
            "items": cast(JsonValue, iterations),
        }
        verdict = "failed" if failed else "not_run" if not items else "passed"
        return NodeResult(
            status=NodeStatus.PASSED,
            output=output,
            test_verdict=verdict,
            control_signal="return" if iterations and result.control_signal == "return" else None,
            return_output=result.return_output
            if iterations and result.control_signal == "return"
            else None,
        )

    async def _run_iteration(
        self,
        node: WorkflowNode,
        config: ForEachControlConfig | RepeatControlConfig,
        items: list[JsonValue],
        region: WorkflowRegion,
        parent: ExecutionContext,
        token: CancellationToken,
        index: int,
        item: JsonValue,
        *,
        isolate: bool,
    ) -> tuple[dict[str, JsonValue], WorkflowRunResult]:
        scope = (*parent.checkpoint_scope, "region", region.id, "iteration", str(index))
        loop_values: dict[str, JsonValue] = {
            "index": index,
            "iteration": index + 1,
            "total": len(items),
        }
        if isinstance(config, ForEachControlConfig):
            loop_values["item"] = item
        child = self._child_context(parent, scope)
        child.cancellation = token
        child.loop_variables = deepcopy(loop_values)
        child.checkpoint_phase = parent.checkpoint_phase or node.phase
        child.input_variables = self._loop_inputs(config.inputs, region.inputs, parent, child)
        scoped_executor = (
            self._executor.fork_branch()
            if isolate and isinstance(self._executor, BranchForkableExecutor)
            else None
        )
        try:
            result = await self._run_region(region, child, token, executor=scoped_executor)
        finally:
            if scoped_executor is not None:
                await scoped_executor.close()
        exports = self._collect(
            config,
            region,
            child,
            result.status,
            allow_missing=result.control_signal is not None,
        )
        summary: dict[str, JsonValue] = {
            "input_index": index,
            "instance_path": list(scope),
            "status": result.status.value,
            "test_verdict": (
                "failed"
                if result.status is WorkflowRunStatus.FAILED
                else "not_run"
                if result.status is WorkflowRunStatus.CANCELLED
                else "passed"
            ),
            "outputs": exports,
            "nodes": [
                {
                    "node_id": record.node_id,
                    "instance_id": _instance_id(scope, record.node_id),
                    "status": record.status.value,
                    "error_code": record.error_code,
                    "error_message": record.error_message,
                }
                for record in result.records
            ],
        }
        return summary, result

    async def _run_parallel_loop(
        self,
        node: WorkflowNode,
        config: ForEachControlConfig | RepeatControlConfig,
        items: list[JsonValue],
        region: WorkflowRegion,
        parent: ExecutionContext,
    ) -> NodeResult:
        root_token = parent.cancellation or CancellationToken()
        active: dict[asyncio.Task[dict[str, JsonValue]], CancellationToken] = {}
        results: dict[int, dict[str, JsonValue]] = {}
        next_index = 0
        stopped = False
        try:
            while next_index < len(items) or active:
                next_index = self._start_parallel_iterations(
                    node,
                    config,
                    items,
                    region,
                    parent,
                    root_token,
                    active,
                    next_index,
                    stopped=stopped,
                )
                if not active:
                    break
                done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    active.pop(task)
                    summary = await task
                    results[cast(int, summary["input_index"])] = summary
                    if summary["status"] == "failed" and config.policy.on_error == "stop":
                        stopped = True
                        for token in active.values():
                            token.cancel()
        finally:
            for token in active.values():
                token.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
        iterations = [results[index] for index in sorted(results)]
        failed = sum(item["status"] == "failed" for item in iterations)
        output: dict[str, JsonValue] = {
            "input_count": len(items),
            "started_count": len(iterations),
            "completed_count": len(iterations),
            "passed_count": len(iterations) - failed,
            "failed_count": failed,
            "not_started_count": len(items) - len(iterations),
            "termination_reason": "cancelled"
            if root_token.cancelled
            else "failed"
            if stopped
            else "completed",
            "items": cast(JsonValue, iterations),
        }
        if root_token.cancelled:
            return NodeResult(status=NodeStatus.CANCELLED, output=output)
        return NodeResult(
            status=NodeStatus.PASSED,
            output=output,
            test_verdict="failed" if failed else "not_run" if not items else "passed",
        )

    def _start_parallel_iterations(
        self,
        node: WorkflowNode,
        config: ForEachControlConfig | RepeatControlConfig,
        items: list[JsonValue],
        region: WorkflowRegion,
        parent: ExecutionContext,
        root_token: CancellationToken,
        active: dict[asyncio.Task[dict[str, JsonValue]], CancellationToken],
        next_index: int,
        *,
        stopped: bool,
    ) -> int:
        while (
            not stopped
            and not root_token.cancelled
            and next_index < len(items)
            and len(active) < config.policy.concurrency
        ):
            token = CancellationToken(root_token)
            task = asyncio.create_task(
                self._parallel_iteration(
                    node,
                    config,
                    items,
                    region,
                    parent,
                    token,
                    next_index,
                )
            )
            active[task] = token
            next_index += 1
        return next_index

    async def _parallel_iteration(
        self,
        node: WorkflowNode,
        config: ForEachControlConfig | RepeatControlConfig,
        items: list[JsonValue],
        region: WorkflowRegion,
        parent: ExecutionContext,
        token: CancellationToken,
        index: int,
    ) -> dict[str, JsonValue]:
        try:
            summary, _ = await self._run_iteration(
                node, config, items, region, parent, token, index, items[index], isolate=True
            )
            return summary
        except NodeExecutionError as error:
            return {
                "input_index": index,
                "status": "failed",
                "test_verdict": "failed",
                "error_code": error.code,
                "outputs": {},
                "nodes": [],
            }

    @staticmethod
    def _collect(
        config: ForEachControlConfig | RepeatControlConfig | ConditionLoopConfig,
        region: WorkflowRegion,
        context: ExecutionContext,
        status: WorkflowRunStatus,
        *,
        allow_missing: bool = False,
    ) -> dict[str, JsonValue]:
        collected: dict[str, JsonValue] = {}
        for name, source in {**region.outputs, **config.collect}.items():
            try:
                collected[name] = resolve_value(source, context)
            except NodeExecutionError:
                if status is WorkflowRunStatus.PASSED and not allow_missing:
                    raise
        return collected

    async def _run_region(
        self,
        region: WorkflowRegion,
        context: ExecutionContext,
        token: CancellationToken,
        *,
        executor: NodeExecutor | None = None,
    ) -> WorkflowRunResult:
        records = tuple(
            replace(record, node_id=node.id)
            for node in region.nodes
            if (
                record := context.nested_checkpoint_records.get(
                    _instance_id(context.checkpoint_scope, node.id)
                )
            )
            is not None
        )

        async def publish(update: NodeStatusUpdate) -> None:
            instance_id = _instance_id(context.checkpoint_scope, update.node_id)
            mapped = replace(
                update,
                node_id=instance_id,
                phase=context.checkpoint_phase or update.phase,
            )
            if update.status.is_terminal:
                context.nested_checkpoint_records[instance_id] = NodeRunRecord(
                    node_id=instance_id,
                    node_type=update.node_type,
                    name=update.name,
                    status=update.status,
                    attempts=update.attempts,
                    output=update.result.output if update.result is not None else None,
                    result=update.result or NodeResult(status=update.status),
                    error_code=update.error_code,
                    error_message=update.error_message,
                    started_at=update.started_at,
                    completed_at=update.occurred_at,
                    input_hash=update.input_hash,
                    phase=mapped.phase,
                    best_effort=update.best_effort,
                )
            if context.status_callback is not None:
                await context.status_callback(mapped)

        return await WorkflowScheduler(executor or self._executor).run_region(
            self._definition,
            region,
            context=context,
            cancellation=token,
            on_node_status=publish,
            resume_records=records,
        )


def _is_loop_source(source: ValueSource) -> bool:
    return isinstance(source, VariableValueSource) and source.scope == "loop"


def _first_region_error(result: WorkflowRunResult) -> dict[str, JsonValue] | None:
    for record in result.records:
        if record.status is NodeStatus.FAILED:
            return {
                "code": record.error_code or "CONTROL_REGION_FAILED",
                "message": record.error_message or "控制区域执行失败",
            }
    return None


def _matching_catch(catches: list[TryCatch], error: dict[str, JsonValue] | None) -> TryCatch | None:
    if error is None:
        return None
    code = error["code"]
    return next((item for item in catches if code in item.error_codes), None)


def _try_node_result(
    try_result: WorkflowRunResult | None,
    catch_result: WorkflowRunResult | None,
    finally_result: WorkflowRunResult | None,
    original_error: dict[str, JsonValue] | None,
    catch_error: dict[str, JsonValue] | None,
    finally_error: dict[str, JsonValue] | None,
    catch_id: str | None,
    expected_codes: list[str],
    exports: dict[str, JsonValue],
    *,
    has_finally: bool,
) -> NodeResult:
    output: dict[str, JsonValue] = {
        "try_status": try_result.status.value if try_result else "failed",
        "catch_id": catch_id,
        "catch_status": catch_result.status.value if catch_result else None,
        "finally_status": (
            finally_result.status.value if finally_result else "skipped" if has_finally else None
        ),
        "original_error": original_error,
        "catch_error": catch_error,
        "finally_error": finally_error,
        "outputs": exports,
    }
    caught = (
        catch_id is not None
        and catch_result is not None
        and (catch_result.status is WorkflowRunStatus.PASSED)
    )
    if original_error is not None and not caught:
        return NodeResult.failed(
            code=cast(str, original_error["code"]),
            message=cast(str, original_error["message"]),
            output=output,
        )
    if catch_error is not None or (
        catch_result and catch_result.status is WorkflowRunStatus.FAILED
    ):
        return NodeResult.failed(code="CATCH_FAILED", message="错误处理区域失败", output=output)
    if finally_error is not None or (
        finally_result and finally_result.status is WorkflowRunStatus.FAILED
    ):
        return NodeResult.failed(code="FINALLY_FAILED", message="清理区域失败", output=output)
    if (try_result and try_result.status is WorkflowRunStatus.CANCELLED) or (
        finally_result and finally_result.status is WorkflowRunStatus.CANCELLED
    ):
        return NodeResult(status=NodeStatus.CANCELLED, output=output)
    signal = (
        catch_result.control_signal
        if catch_result is not None
        else try_result.control_signal
        if try_result is not None
        else None
    )
    return_output = (
        catch_result.return_output
        if catch_result is not None
        else try_result.return_output
        if try_result is not None
        else None
    )
    unexpected = original_error is not None and original_error["code"] not in expected_codes
    verdict_failed = unexpected or (
        try_result is not None
        and try_result.status is WorkflowRunStatus.FAILED
        and original_error is None
    )
    return NodeResult(
        status=NodeStatus.PASSED,
        output=output,
        control_signal=signal,
        return_output=return_output,
        test_verdict="failed" if verdict_failed else "passed",
    )


def _condition_round_terminal(
    result: WorkflowRunResult,
    iterations: list[dict[str, JsonValue]],
    state: dict[str, JsonValue],
) -> NodeResult | None:
    if result.status is WorkflowRunStatus.FAILED:
        return NodeResult.failed(
            code="CONTROL_BODY_FAILED",
            message="条件循环体执行失败",
            output=_condition_loop_output(iterations, state, "failed"),
        )
    if result.status is WorkflowRunStatus.CANCELLED:
        return NodeResult(
            status=NodeStatus.CANCELLED,
            output=_condition_loop_output(iterations, state, "cancelled"),
        )
    if result.control_signal == "break":
        return _completed_condition_loop(iterations, state, "break")
    if result.control_signal == "return":
        return NodeResult(
            status=NodeStatus.PASSED,
            output=_condition_loop_output(iterations, state, "return"),
            control_signal="return",
            return_output=result.return_output,
        )
    return None


def _post_condition_exit(
    node: WorkflowNode,
    config: ConditionLoopConfig,
    context: ExecutionContext,
    state: dict[str, JsonValue],
    iteration: dict[str, JsonValue],
) -> str | None:
    if node.capability_id == "flow.control.while":
        return None
    context.state_variables = dict(state)
    matched, trace = evaluate_condition(config.condition, context)
    iteration["condition_trace"] = cast(JsonValue, trace)
    if node.capability_id == "flow.control.until" and matched:
        return "condition_met"
    if node.capability_id == "flow.control.do_while" and not matched:
        return "condition_false"
    return None


def _state_update_value(
    current: JsonValue, update: StateUpdate, context: ExecutionContext
) -> JsonValue:
    value = resolve_value(update.value, context)
    if update.kind == "set":
        return value
    if update.kind == "add":
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            raise NodeExecutionError(code="STATE_TYPE_MISMATCH", message="状态递增需要数值")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise NodeExecutionError(code="STATE_TYPE_MISMATCH", message="状态递增量需要数值")
        return current + value
    if not isinstance(current, list):
        raise NodeExecutionError(code="STATE_TYPE_MISMATCH", message="状态追加需要数组")
    if len(current) >= 1000:
        raise NodeExecutionError(code="STATE_ARRAY_LIMIT", message="状态数组超过最大长度")
    return [*current, value]


def _condition_loop_output(
    iterations: list[dict[str, JsonValue]], state: dict[str, JsonValue], reason: str
) -> dict[str, JsonValue]:
    failed = sum(item["status"] == "failed" for item in iterations)
    return {
        "started_count": len(iterations),
        "completed_count": len(iterations),
        "passed_count": len(iterations) - failed,
        "failed_count": failed,
        "termination_reason": reason,
        "state": dict(state),
        "items": cast(JsonValue, iterations),
    }


def _completed_condition_loop(
    iterations: list[dict[str, JsonValue]], state: dict[str, JsonValue], reason: str
) -> NodeResult:
    return NodeResult(
        status=NodeStatus.PASSED,
        output=_condition_loop_output(iterations, state, reason),
        test_verdict="passed" if iterations else "not_run",
    )

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.domain.performance import LoadExecutor, PerformanceScenarioDefinition


@dataclass(frozen=True, slots=True)
class CompiledK6Scenario:
    source: str
    sha256: str


class K6ScenarioCompiler:
    """Compile typed platform data into a fixed k6 program; user source is never evaluated."""

    def compile(self, definition: PerformanceScenarioDefinition) -> CompiledK6Scenario:
        steps = [_serialize_step(step.model_dump(mode="json")) for step in definition.steps]
        options = {
            "discardResponseBodies": True,
            "scenarios": {"flowtest": _scenario_options(definition)},
            "thresholds": _threshold_options(definition),
        }
        source = _render_source(options=options, steps=steps)
        return CompiledK6Scenario(
            source=source,
            sha256=hashlib.sha256(source.encode()).hexdigest(),
        )


def _scenario_options(definition: PerformanceScenarioDefinition) -> dict[str, object]:
    base: dict[str, object] = {
        "executor": definition.executor.value.replace("_", "-"),
        "gracefulStop": f"{definition.graceful_stop_seconds}s",
    }
    if definition.executor is LoadExecutor.CONSTANT_VUS:
        return {
            **base,
            "vus": definition.vus,
            "duration": f"{definition.duration_seconds}s",
        }
    return {
        **base,
        "startVUs": definition.start_vus,
        "stages": [
            {"duration": f"{stage.duration_seconds}s", "target": stage.target_vus}
            for stage in definition.stages
        ],
    }


def _threshold_options(definition: PerformanceScenarioDefinition) -> dict[str, list[object]]:
    result: dict[str, list[object]] = {}
    for threshold in definition.thresholds:
        item: dict[str, object] = {
            "threshold": threshold.expression,
            "abortOnFail": threshold.abort_on_fail,
        }
        if threshold.delay_abort_seconds:
            item["delayAbortEval"] = f"{threshold.delay_abort_seconds}s"
        result.setdefault(threshold.metric, []).append(item)
    return result


def _serialize_step(step: dict[str, Any]) -> dict[str, Any]:
    body = step["body"]
    if body is not None and not isinstance(body, str):
        body = json.dumps(body, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        headers = dict(step["headers"])
        headers.setdefault("Content-Type", "application/json")
        step["headers"] = headers
    step["body"] = body
    return step


def _render_source(*, options: dict[str, object], steps: list[dict[str, Any]]) -> str:
    serialized_options = json.dumps(options, ensure_ascii=True, separators=(",", ":"))
    serialized_steps = json.dumps(steps, ensure_ascii=True, separators=(",", ":"))
    return f"""import http from 'k6/http';
import {{ check, sleep }} from 'k6';

export const options = {serialized_options};
const steps = {serialized_steps};

export default function () {{
  for (const step of steps) {{
    const response = http.request(step.method, step.url, step.body, {{
      headers: step.headers,
      redirects: 0,
      tags: {{ flowtest_step: step.name }},
    }});
    check(response, {{
      [`status:${{step.name}}`]: (result) => step.expected_statuses.includes(result.status),
    }});
    if (step.pause_seconds > 0) sleep(step.pause_seconds);
  }}
}}

export function handleSummary(data) {{
  return {{ 'flowtest-summary.json': JSON.stringify(data) }};
}}
"""

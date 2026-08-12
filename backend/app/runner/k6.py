import asyncio
import json
import tempfile
from pathlib import Path

from app.domain.performance import PerformanceExecutionResult
from app.engine.k6_compiler import CompiledK6Scenario


class K6ExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class K6ProcessRunner:
    def __init__(self, executable: str = "k6", *, raw_metrics_limit_bytes: int = 50 * 1024 * 1024):
        self._executable = executable
        self._raw_metrics_limit_bytes = raw_metrics_limit_bytes

    async def run(
        self,
        scenario: CompiledK6Scenario,
        *,
        timeout_seconds: int,
    ) -> PerformanceExecutionResult:
        with tempfile.TemporaryDirectory(prefix="flowtest-k6-") as directory:
            root = Path(directory)
            script_path = root / "scenario.js"
            metrics_path = root / "raw-metrics.json"
            summary_path = root / "flowtest-summary.json"
            script_path.write_text(scenario.source, encoding="utf-8")
            process = await self._start(script_path, metrics_path, root)
            stderr = await self._communicate(process, timeout_seconds)
            summary = _load_summary(summary_path)
            raw_metrics = _load_limited(metrics_path, self._raw_metrics_limit_bytes)
            if process.returncode != 0 and not summary:
                raise K6ExecutionError("K6_EXECUTION_FAILED", _safe_error(stderr))
            return PerformanceExecutionResult(
                exit_code=process.returncode or 0,
                summary=summary,
                raw_metrics=raw_metrics,
                stderr=_safe_error(stderr),
            )

    async def _start(
        self, script_path: Path, metrics_path: Path, working_directory: Path
    ) -> asyncio.subprocess.Process:
        try:
            return await asyncio.create_subprocess_exec(
                self._executable,
                "run",
                "--no-color",
                "--quiet",
                "--out",
                f"json={metrics_path}",
                str(script_path),
                cwd=working_directory,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as error:
            raise K6ExecutionError("K6_UNAVAILABLE", "性能 Runner 未安装 k6") from error

    async def _communicate(self, process: asyncio.subprocess.Process, timeout_seconds: int) -> str:
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise K6ExecutionError("K6_TIMEOUT", "性能场景执行超时") from error
        return (stderr or b"").decode(errors="replace")


def _load_summary(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise K6ExecutionError("K6_SUMMARY_INVALID", "k6 汇总结果无效") from error
    if not isinstance(value, dict):
        raise K6ExecutionError("K6_SUMMARY_INVALID", "k6 汇总结果无效")
    return value


def _load_limited(path: Path, limit_bytes: int) -> bytes:
    if not path.exists():
        return b""
    if path.stat().st_size > limit_bytes:
        raise K6ExecutionError("K6_METRICS_TOO_LARGE", "k6 原始指标超过 50 MB 上限")
    return path.read_bytes()


def _safe_error(value: str) -> str:
    return value.strip()[-2000:]

"""Direct public-API probes keep JUnit distinct from native Workflow execution."""

from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring


def write_boundary_junit(
    directory: Path,
    scenarios: tuple[str, ...],
    reasons: tuple[str, ...],
    *,
    purpose: str,
) -> None:
    verification = Element(
        "testsuite",
        name="独立边界核验",
        tests=str(len(scenarios)),
        failures=str(len(scenarios) if reasons else 0),
    )
    execution = Element(
        "testsuite",
        name="边界探针未声明正式用例执行",
        tests=str(len(scenarios)),
        skipped=str(len(scenarios)),
    )
    for identity in scenarios:
        checked = SubElement(verification, "testcase", name=identity)
        if reasons:
            SubElement(checked, "failure", message=",".join(reasons))
        raw = SubElement(execution, "testcase", name=identity)
        SubElement(raw, "skipped", message=purpose)
    directory.mkdir(parents=True, exist_ok=True)
    for filename, element in (
        ("verification.junit.xml", verification),
        ("execution.junit.xml", execution),
    ):
        (directory / filename).write_bytes(
            tostring(element, encoding="utf-8", xml_declaration=True)
        )

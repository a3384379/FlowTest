from dataclasses import dataclass
from typing import cast
from xml.etree import ElementTree


@dataclass(frozen=True, slots=True)
class JUnitCase:
    name: str
    classname: str
    duration_seconds: float
    status: str
    message: str | None = None


def build_junit_xml(*, suite_name: str, cases: tuple[JUnitCase, ...]) -> bytes:
    failures = sum(case.status == "failed" for case in cases)
    skipped = sum(case.status in {"cancelled", "quarantined"} for case in cases)
    duration = sum(max(case.duration_seconds, 0.0) for case in cases)
    suite = ElementTree.Element(
        "testsuite",
        {
            "name": suite_name,
            "tests": str(len(cases)),
            "failures": str(failures),
            "errors": "0",
            "skipped": str(skipped),
            "time": f"{duration:.3f}",
        },
    )
    for case in cases:
        element = ElementTree.SubElement(
            suite,
            "testcase",
            {
                "name": case.name,
                "classname": case.classname,
                "time": f"{max(case.duration_seconds, 0.0):.3f}",
            },
        )
        if case.status == "failed":
            failure = ElementTree.SubElement(element, "failure", {"message": "FlowTest failure"})
            failure.text = case.message or "执行失败"
        elif case.status in {"cancelled", "quarantined"}:
            ElementTree.SubElement(element, "skipped", {"message": case.status})
    return cast(bytes, ElementTree.tostring(suite, encoding="utf-8", xml_declaration=True))

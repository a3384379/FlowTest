"""Versioned built-in metadata; packs and independent goldens execute outside the API."""

from app.schemas.self_tests import ExpectedResult, TemplateResponse, TemplateScenario


def templates() -> tuple[TemplateResponse, ...]:
    core = tuple(
        TemplateScenario(
            scenario_id=f"ST-CORE-{key}", title=title, category="engine", expected=expected
        )
        for key, title, expected in (
            ("echo-boundaries", "边界值与 Header 回显", ExpectedResult(status="passed")),
            (
                "business-failure",
                "HTTP 200 业务失败检出",
                ExpectedResult(
                    status="failed", error_code="WORKFLOW_ASSERTION_FAILED", phase="main"
                ),
            ),
            (
                "timeout",
                "节点超时分类",
                ExpectedResult(status="failed", error_code="NODE_TIMEOUT", phase="main"),
            ),
            ("if", "条件分支", ExpectedResult(status="passed")),
            ("foreach", "ForEach 迭代", ExpectedResult(status="passed")),
            ("repeat", "Repeat 计数", ExpectedResult(status="passed")),
            ("retry", "受控重试", ExpectedResult(status="passed")),
            ("poll", "有界轮询", ExpectedResult(status="passed")),
        )
    )
    generated = (
        TemplateScenario(
            scenario_id="ST-MCP-023",
            variant_key="environment_lifecycle",
            title="真实 B 环境生命周期",
            category="api",
            expected=ExpectedResult(status="passed"),
        ),
        TemplateScenario(
            scenario_id="ST-MCP-025",
            variant_key="negative_assertion_canary",
            title="错误断言检出",
            category="mcp",
            expected=ExpectedResult(
                status="failed", error_code="WORKFLOW_ASSERTION_FAILED", phase="main"
            ),
        ),
        TemplateScenario(
            scenario_id="ST-MCP-026",
            variant_key="positive_assertion_canary",
            title="正向断言对照",
            category="mcp",
            expected=ExpectedResult(status="passed"),
        ),
    )
    return (
        TemplateResponse(
            id="core-v1",
            title="原生固定基准",
            batch_kind="fixed_baseline",
            pack_digest="93d772af7216b661586dd0f4714b49b295846d192c383d8c4cc2fff21164b9bf",
            task_set_digest="93d772af7216b661586dd0f4714b49b295846d192c383d8c4cc2fff21164b9bf",
            scenarios=core,
        ),
        TemplateResponse(
            id="mcp-core-v1",
            title="MCP 现场生成闭环",
            batch_kind="mcp_generated",
            pack_digest="9e1e156018118c4874f00751684f13b419f6f75188dab47f08b9e7817e09ce67",
            task_set_digest="3167b4cb1639f3f1d0bbf23044db6e4150c756778c564f8b3d6bd67bb9317574",
            scenarios=generated,
            supported_modes=("deterministic_mcp", "host_llm_mcp"),
        ),
    )

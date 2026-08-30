# Golden evaluation

The committed V6 Golden Set is model-independent: annotations refer to fixture outcomes and executable contract/security tests, not to a particular LLM response. Run the evaluator from the repository root:

```bash
uv run --project backend python scripts/evaluate_v6_core.py --check
```

The evaluator validates every annotation, emits each metric in a stable order, compares the result with `backend/tests/fixtures/v6_golden/evaluation-baseline.json`, and fails closed when a release-gated metric has no evidence or violates its threshold.

Interpret exact numerators and denominators only within the committed fixture set. Operation and binding precision and manual-edit rate are baselines, not release thresholds. Static validation, compiler success, preview first-pass, conflict detection, secret leakage, cross-tenant access, stale overwrite, unreviewed Apply, production MCP preview, arbitrary code, write SQL, silent cleanup failure, and product-defect weakening are hard gates as recorded in the baseline.

An empty denominator is `insufficient_evidence`, never 100%. Do not claim “95% accuracy” unless a future, versioned Golden Set establishes and passes that threshold.

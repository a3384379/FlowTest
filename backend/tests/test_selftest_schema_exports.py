"""Saved contracts must match their executable models and validate as Draft 2020-12."""

import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parents[2]))


from scripts.selftest.io import read_json
from scripts.selftest.local_stack import ROOT
from scripts.selftest.schema_exports import SCHEMAS


@pytest.mark.parametrize("name,model", SCHEMAS)
def test_additional_saved_schema_matches_executable_contract(name, model):
    saved = read_json(ROOT / "selftest/schemas" / f"{name}.schema.json")
    Draft202012Validator.check_schema(saved)
    assert saved == {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **model.model_json_schema(),
    }

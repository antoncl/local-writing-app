"""The assistant's lore settings in the default schema (#1900).

`ai_lore_expansion` declares a default, so the rail treats the select as
required (no "(none)" pick) and an untouched assistant reads "One hop" — the
same value the resolver applies to a blank. Both fields explain themselves.
"""

from app.services.ai.lore_budget import DEFAULT_LORE_LIMITS
from app.services.project.default_schema import DEFAULT_METADATA_SCHEMA


def test_lore_reach_defaults_to_one_hop_and_offers_only_the_two_routes() -> None:
    field = DEFAULT_METADATA_SCHEMA["fields"]["ai_lore_expansion"]
    assert field["type"] == "select"
    assert field["default"] == "one_hop"
    assert [option["value"] for option in field["options"]] == ["one_hop", "named"]
    # The visible default and the resolver's blank→default agree.
    assert field["default"] == DEFAULT_LORE_LIMITS.expansion


def test_lore_reach_and_budget_explain_themselves() -> None:
    fields = DEFAULT_METADATA_SCHEMA["fields"]
    for key in ("ai_lore_expansion", "ai_lore_budget_tokens"):
        assert fields[key]["description"].strip(), key

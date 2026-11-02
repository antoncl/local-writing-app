"""Proofreading models (ADR-0102 §4, §6, §7).

What the writer tells the proofreading lens to accept is kept in two optional
files, absent meaning empty: `proofreading.yaml` per layer (dictionary words,
rule switches, dialect; merged down the chain, nearer winning) and
`proofreading.ignored.yaml` per project (ignore-here context hashes by node).
Every write answers with the whole merged setup, so the lens reloads from one
shape.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Dialect = Literal["american", "british", "australian", "canadian", "indian"]

# Harper rule names are CamelCase identifiers (`SpellCheck`, `OxfordComma`).
RULE_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9]{0,99}$"
# A context hash is an unsigned 64-bit integer, sent as a decimal string: as a
# JSON number it would lose precision.
HASH_PATTERN = r"^[0-9]{1,20}$"


class ProofreadingLayer(BaseModel):
    """One layer a word or rule can be read from and written to."""

    id: str
    label: str
    is_machine: bool = False
    # The built-in Library: read-only; it carries the shipped fiction default.
    is_library: bool = False
    is_root: bool = False
    # What this layer's own file says, for the settings view (ADR-0102 slice 3);
    # the merged result is on the setup.
    words: list[str] = Field(default_factory=list)
    rules: dict[str, bool] = Field(default_factory=dict)
    dialect: Dialect | None = None


class ProofreadingSetup(BaseModel):
    """The open project's merged proofreading setup."""

    # The union of every layer's words, sorted.
    words: list[str] = Field(default_factory=list)
    # Which layers list each word (layer ids), for removing it.
    word_layers: dict[str, list[str]] = Field(default_factory=dict)
    # Rule name -> on/off, merged outermost to nearest, nearer winning.
    rules: dict[str, bool] = Field(default_factory=dict)
    # Rule name -> the id of the layer whose setting won.
    rule_layers: dict[str, str] = Field(default_factory=dict)
    dialect: Dialect = "american"
    # Library, machine, then the project chain, outermost first.
    layers: list[ProofreadingLayer] = Field(default_factory=list)
    # Node id -> ignore-here hashes, from every project layer of the chain.
    ignored: dict[str, list[str]] = Field(default_factory=dict)


class ProofreadingWordRequest(BaseModel):
    word: str = Field(min_length=1, max_length=100)
    layer_id: str = Field(min_length=1)


class ProofreadingRuleRequest(BaseModel):
    rule: str = Field(pattern=RULE_NAME_PATTERN)
    # None sets the rule back to "as inherited" (removes the layer's key).
    enabled: bool | None
    layer_id: str = Field(min_length=1)


class ProofreadingDialectRequest(BaseModel):
    # None removes the layer's setting.
    dialect: Dialect | None
    layer_id: str = Field(min_length=1)


class ProofreadingIgnoreRequest(BaseModel):
    node_id: str = Field(min_length=1)
    # Every lint at the spot, not only the one shown: where two rules flag the
    # same words, Harper shows one and hides the other, and ignoring the shown
    # one alone would uncover the hidden one.
    hashes: list[Annotated[str, Field(pattern=HASH_PATTERN)]] = Field(min_length=1, max_length=20)

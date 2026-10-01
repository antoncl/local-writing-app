"""The cl100k_base vocabulary ships with the app (#2404): token counting never
downloads it, and the shipped copy stays exactly tiktoken's own encoding."""

from __future__ import annotations

import tiktoken
from tiktoken_ext import openai_public

from app.services.ai.profiles import base


def test_shipped_cl100k_matches_tiktokens_own_definition(monkeypatch) -> None:
    pinned: dict[str, str | None] = {}

    def no_download(url: str, expected_hash: str | None = None) -> dict:
        pinned["hash"] = expected_hash
        return {}

    monkeypatch.setattr(openai_public, "load_tiktoken_bpe", no_download)
    upstream = openai_public.cl100k_base()
    shipped = base._load_cl100k(tiktoken)

    assert pinned["hash"] == base._CL100K_SHA256
    assert shipped._pat_str == upstream["pat_str"]
    assert shipped._special_tokens == upstream["special_tokens"]


def test_token_count_loads_the_shipped_vocabulary_offline(monkeypatch, tmp_path) -> None:
    # An empty tiktoken cache: were the encoder still fetched via
    # `get_encoding`, it would reach for the network and the socket guard
    # would fail this test — even on a machine that cached it long ago.
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(base, "_TIKTOKEN_TRIED", False)
    monkeypatch.setattr(base, "_TIKTOKEN_ENCODER", None)

    assert base._tiktoken_encoder().encode("hello world") == [15339, 1917]
    assert base.default_token_count("hello world") == 2
    assert not any(tmp_path.iterdir())

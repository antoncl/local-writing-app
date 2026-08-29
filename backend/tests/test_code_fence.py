"""Whole-body code-fence detection/unwrap (#1628)."""
from __future__ import annotations

import pytest

from app.services.project.code_fence import unwrap_whole_body_code_fence


class TestFlaggedAndUnwrapped:
    def test_markdown_info_string_unwraps_to_inner_prose(self) -> None:
        body = "```markdown\n# Shell\n\nA note about the world.\n```"
        assert unwrap_whole_body_code_fence(body) == "# Shell\n\nA note about the world."

    def test_md_info_string_is_treated_the_same(self) -> None:
        assert unwrap_whole_body_code_fence("```md\nhello\n```") == "hello"

    def test_bare_fence_with_no_info_string_unwraps(self) -> None:
        assert unwrap_whole_body_code_fence("```\njust prose\n```") == "just prose"

    def test_tilde_fence_unwraps(self) -> None:
        assert unwrap_whole_body_code_fence("~~~markdown\nprose\n~~~") == "prose"

    def test_blank_edges_are_ignored(self) -> None:
        body = "\n\n```markdown\ninner\n```\n\n"
        assert unwrap_whole_body_code_fence(body) == "inner"

    def test_indented_opening_fence_up_to_three_spaces(self) -> None:
        assert unwrap_whole_body_code_fence("   ```markdown\ninner\n   ```") == "inner"

    def test_info_string_is_case_insensitive(self) -> None:
        assert unwrap_whole_body_code_fence("```Markdown\ninner\n```") == "inner"

    def test_multiline_inner_content_is_preserved_verbatim(self) -> None:
        body = "```markdown\n- one\n- two\n\n> a quote\n```"
        assert unwrap_whole_body_code_fence(body) == "- one\n- two\n\n> a quote"

    def test_longer_outer_fence_survives_shorter_inner_backticks(self) -> None:
        # A four-backtick wrapper whose prose contains an ordinary ``` code
        # sample: the inner triple does not close the longer outer fence.
        body = "````markdown\ntext\n```\nsample\n```\nmore\n````"
        assert unwrap_whole_body_code_fence(body) == "text\n```\nsample\n```\nmore"


class TestNotFlagged:
    def test_a_real_language_fence_is_left_alone(self) -> None:
        assert unwrap_whole_body_code_fence("```python\nprint(1)\n```") is None

    def test_json_fence_is_left_alone(self) -> None:
        assert unwrap_whole_body_code_fence('```json\n{"a": 1}\n```') is None

    def test_plain_prose_is_not_flagged(self) -> None:
        assert unwrap_whole_body_code_fence("# Title\n\nJust some prose.") is None

    def test_prose_that_merely_contains_a_code_block_is_not_flagged(self) -> None:
        body = "Intro paragraph.\n\n```markdown\nsample\n```"
        assert unwrap_whole_body_code_fence(body) is None

    def test_a_fence_that_closes_before_the_end_is_not_flagged(self) -> None:
        body = "```markdown\nsample\n```\n\nA trailing paragraph."
        assert unwrap_whole_body_code_fence(body) is None

    def test_an_unterminated_fence_is_not_flagged(self) -> None:
        assert unwrap_whole_body_code_fence("```markdown\nno closing fence") is None

    def test_empty_body_is_not_flagged(self) -> None:
        assert unwrap_whole_body_code_fence("") is None
        assert unwrap_whole_body_code_fence("\n\n   \n") is None

    def test_two_separate_code_blocks_are_not_flagged(self) -> None:
        body = "```markdown\none\n```\n\n```markdown\ntwo\n```"
        assert unwrap_whole_body_code_fence(body) is None


@pytest.mark.parametrize(
    "info",
    ["", "markdown", "md", "  markdown  ", "MD"],
)
def test_prose_info_strings_flag(info: str) -> None:
    assert unwrap_whole_body_code_fence(f"```{info}\ninner\n```") == "inner"


@pytest.mark.parametrize(
    "info",
    ["python", "js", "ts", "yaml", "text", "sh", "bash"],
)
def test_language_info_strings_do_not_flag(info: str) -> None:
    assert unwrap_whole_body_code_fence(f"```{info}\ninner\n```") is None

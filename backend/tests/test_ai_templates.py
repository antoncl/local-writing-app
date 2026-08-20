from __future__ import annotations

import unittest

from jinja2 import TemplateSyntaxError, UndefinedError

from app.services.ai.templates import (
    ContentBlock,
    render_template,
)


class TemplateEngineTests(unittest.TestCase):
    def test_single_role_block_produces_one_message(self) -> None:
        out = render_template('{% role "system" %}hello{% endrole %}')
        self.assertEqual(len(out.messages), 1)
        self.assertEqual(out.messages[0].role, "system")
        self.assertEqual(out.messages[0].blocks, [ContentBlock(text="hello")])
        self.assertEqual(out.warnings, [])

    def test_multiple_role_blocks_produce_messages_in_order(self) -> None:
        out = render_template(
            '{% role "system" %}sys{% endrole %}'
            '{% role "user" %}usr{% endrole %}'
            '{% role "assistant" %}asn{% endrole %}'
        )
        roles = [m.role for m in out.messages]
        self.assertEqual(roles, ["system", "user", "assistant"])
        self.assertEqual(out.messages[1].text, "usr")

    def test_role_body_is_one_block(self) -> None:
        # ADR-0060 §5 retired intra-message splitting; a role body is one block.
        out = render_template('{% role "system" %}stable then volatile{% endrole %}')
        self.assertEqual(out.messages[0].blocks, [ContentBlock(text="stable then volatile")])

    def test_retired_cache_break_tag_raises(self) -> None:
        # ADR-0060 §5: `{% cache_break %}` is gone — an unknown tag is a syntax
        # error surfaced to the author, not silently rendered.
        with self.assertRaises(TemplateSyntaxError):
            render_template('{% role "system" %}a{% cache_break %}b{% endrole %}')

    def test_do_tag_evaluates_side_effect_and_emits_nothing(self) -> None:
        # ADR-0060 Am.1: `{% do %}` (jinja2.ext.do) is installed, so a
        # side-effecting statement renders instead of raising `unknown tag 'do'`.
        # It emits nothing — the correct construct for helpers like `use()` and
        # `field_contract.store()` that record state and return "".
        sink: list[int] = []
        out = render_template(
            '{% role "system" %}{% do sink.append(1) %}kept{% endrole %}',
            {"sink": sink},
        )
        self.assertEqual(len(out.messages), 1)
        self.assertEqual(out.messages[0].blocks[0].text, "kept")
        self.assertEqual(sink, [1])

    def test_bare_text_outside_role_warns(self) -> None:
        out = render_template(
            'leaked text{% role "system" %}sys{% endrole %}'
        )
        self.assertTrue(
            any("outside any role block" in w for w in out.warnings),
            out.warnings,
        )
        self.assertEqual(out.messages[0].text, "sys")

    def test_whitespace_only_outside_role_is_silent(self) -> None:
        out = render_template(
            '   \n  {% role "system" %}sys{% endrole %}   '
        )
        self.assertEqual(out.warnings, [])

    def test_unknown_role_warns_but_still_emits_message(self) -> None:
        out = render_template('{% role "robot" %}beep{% endrole %}')
        self.assertEqual(len(out.messages), 1)
        self.assertEqual(out.messages[0].role, "robot")
        self.assertTrue(
            any("Unknown role" in w for w in out.warnings),
            out.warnings,
        )

    def test_nested_role_drops_outer_keeps_inner(self) -> None:
        out = render_template(
            '{% role "system" %}'
            'pre {% role "user" %}inner{% endrole %} post'
            '{% endrole %}'
        )
        self.assertEqual(len(out.messages), 1)
        self.assertEqual(out.messages[0].role, "user")
        self.assertEqual(out.messages[0].text, "inner")
        self.assertTrue(
            any("Nested role" in w for w in out.warnings),
            out.warnings,
        )

    def test_undefined_variable_raises(self) -> None:
        with self.assertRaises(UndefinedError):
            render_template(
                '{% role "system" %}hello {{ missing_var }}{% endrole %}'
            )

    def test_context_variables_render(self) -> None:
        out = render_template(
            '{% role "user" %}Write {{ words }} words about {{ subject }}.{% endrole %}',
            context={"words": 300, "subject": "ships"},
        )
        self.assertEqual(out.messages[0].text, "Write 300 words about ships.")

    def test_conditional_and_loop_inside_role(self) -> None:
        out = render_template(
            '{% role "user" %}'
            '{% for item in items %}- {{ item }}\n{% endfor %}'
            '{% if extra %}plus: {{ extra }}{% endif %}'
            '{% endrole %}',
            context={"items": ["a", "b"], "extra": "c"},
        )
        self.assertEqual(out.messages[0].text, "- a\n- b\nplus: c")

    def test_empty_role_block_produces_no_message(self) -> None:
        out = render_template('{% role "system" %}{% endrole %}')
        self.assertEqual(out.messages, [])

    def test_sandbox_blocks_unsafe_attribute_access(self) -> None:
        # SandboxedEnvironment forbids access to dunder attributes; this should
        # raise SecurityError (subclass of TemplateError) when used.
        from jinja2.sandbox import SecurityError

        with self.assertRaises(SecurityError):
            render_template(
                '{% role "system" %}{{ obj.__class__ }}{% endrole %}',
                context={"obj": object()},
            )

    def test_rendered_template_text_property(self) -> None:
        out = render_template('{% role "system" %}{% if x %}one{% endif %}two{% endrole %}',
                              context={"x": True})
        self.assertEqual(out.messages[0].text, "onetwo")


class DefaultRoleHomingTests(unittest.TestCase):
    """ADR-0060 §4: un-roled prose is homed to the base type's `default_role`
    instead of discarded. `default_role=None` keeps the legacy warn-and-drop."""

    def test_prose_only_prompt_homes_to_default_role(self) -> None:
        # Journey D: a plain instruction paragraph, no {% role %} scaffolding.
        out = render_template("Write a tense opening.", default_role="system")
        self.assertEqual(len(out.messages), 1)
        self.assertEqual(out.messages[0].role, "system")
        self.assertEqual(out.messages[0].text, "Write a tense opening.")
        self.assertEqual(out.warnings, [])

    def test_loose_text_homed_before_a_role_block_in_order(self) -> None:
        out = render_template(
            'lead instruction{% role "user" %}u{% endrole %}',
            default_role="system",
        )
        self.assertEqual([(m.role, m.text) for m in out.messages],
                         [("system", "lead instruction"), ("user", "u")])
        self.assertEqual(out.warnings, [])

    def test_loose_text_between_role_blocks_homed(self) -> None:
        out = render_template(
            '{% role "system" %}s{% endrole %}mid text{% role "user" %}u{% endrole %}',
            default_role="system",
        )
        self.assertEqual([(m.role, m.text) for m in out.messages],
                         [("system", "s"), ("system", "mid text"), ("user", "u")])

    def test_none_default_role_keeps_legacy_ignore(self) -> None:
        # No declared envelope → loose text is still ignored with a warning.
        out = render_template('leaked{% role "system" %}s{% endrole %}', default_role=None)
        self.assertEqual([m.role for m in out.messages], ["system"])
        self.assertTrue(any("outside any role block" in w for w in out.warnings), out.warnings)

    def test_whitespace_only_loose_text_not_homed(self) -> None:
        out = render_template(
            '  \n  {% role "system" %}s{% endrole %}  \n  ',
            default_role="system",
        )
        self.assertEqual([(m.role, m.text) for m in out.messages], [("system", "s")])
        self.assertEqual(out.warnings, [])

    def test_default_role_can_be_user(self) -> None:
        out = render_template("play the scene", default_role="user")
        self.assertEqual(out.messages[0].role, "user")


if __name__ == "__main__":
    unittest.main()

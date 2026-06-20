from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from tests.test_summary_selection import _config  # noqa: E402
from backend.routes.history import _resolve_regenerate_summary_preset  # noqa: E402


def test_regenerate_custom_summary_preset_keeps_custom_identity() -> None:
    resolved = _resolve_regenerate_summary_preset(
        config=_config(),
        summary_preset="__user_custom__",
        summary_prompt_template="Custom summary: {content}",
    )

    assert resolved == "__user_custom__"


def test_regenerate_custom_summary_preset_requires_template() -> None:
    try:
        _resolve_regenerate_summary_preset(
            config=_config(),
            summary_preset="__user_custom__",
            summary_prompt_template=None,
        )
    except ValueError as exc:
        assert "用户自定义总结模板不能为空" in str(exc)
    else:
        raise AssertionError("expected custom preset without template to fail")

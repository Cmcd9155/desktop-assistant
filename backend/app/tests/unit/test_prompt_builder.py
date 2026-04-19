from app.main import _build_image_prompt
from app.models import CompanionState


def test_prompt_builder_includes_fixed_base_anchor_every_turn() -> None:
    prompt_a = _build_image_prompt(
        user_text="Turn one",
        assistant_text="Reply one",
        emotion=CompanionState.idle,
        base_image_path="/tmp/base.png",
    )
    prompt_b = _build_image_prompt(
        user_text="Turn two",
        assistant_text="Reply two",
        emotion=CompanionState.smiling,
        base_image_path="/tmp/base.png",
    )

    assert "Base image anchor path: /tmp/base.png" in prompt_a
    assert "Base image anchor path: /tmp/base.png" in prompt_b
    assert "turn one" not in prompt_b.lower()


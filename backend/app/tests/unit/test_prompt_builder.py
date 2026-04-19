from app.main import _build_image_prompt
from app.models import CompanionState


def test_prompt_builder_includes_fixed_base_anchor_every_turn() -> None:
    prompt_a = _build_image_prompt(
        user_text="Turn one",
        image_action="leans forward and smiles",
        emotion=CompanionState.idle,
    )
    prompt_b = _build_image_prompt(
        user_text="Turn two",
        image_action="writes notes quickly",
        emotion=CompanionState.smiling,
    )

    assert "Action directive: leans forward and smiles" in prompt_a
    assert "Action directive: writes notes quickly" in prompt_b
    assert "Companion expression target: smiling" in prompt_b
    assert "turn one" not in prompt_b.lower()

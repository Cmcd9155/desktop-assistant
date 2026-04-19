from app.models import CompanionState
from app.services.emotion import map_emotion


def test_positive_emotion_maps_to_smiling() -> None:
    assert map_emotion("Great work. Perfect result.") == CompanionState.smiling


def test_negative_emotion_maps_to_frowning() -> None:
    assert map_emotion("Sorry, I cannot complete that request.") == CompanionState.frowning


def test_neutral_emotion_maps_to_idle() -> None:
    assert map_emotion("Here is the requested status update.") == CompanionState.idle


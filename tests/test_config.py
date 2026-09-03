import pytest
from pydantic import ValidationError

from src.config import DEFAULT_VISION_IDENTITY_ENABLED, Settings


def test_identity_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("VISION_IDENTITY_ENABLED", raising=False)
    settings = Settings(_env_file=None)
    assert settings.vision_identity_enabled is DEFAULT_VISION_IDENTITY_ENABLED is True


def test_vision_num_poses_defaults_to_single_person():
    settings = Settings(_env_file=None)
    assert settings.vision_num_poses == 1
    assert (settings.vision_input_width, settings.vision_input_height) == (1280, 720)


def test_vision_input_size_reads_environment(monkeypatch):
    monkeypatch.setenv("VISION_INPUT_WIDTH", "960")
    monkeypatch.setenv("VISION_INPUT_HEIGHT", "540")
    settings = Settings(_env_file=None)
    assert (settings.vision_input_width, settings.vision_input_height) == (960, 540)


@pytest.mark.parametrize("value", [0, 6])
def test_vision_num_poses_is_bounded(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, vision_num_poses=value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("vision_input_width", 319),
        ("vision_input_width", 3841),
        ("vision_input_height", 239),
        ("vision_input_height", 2161),
    ],
)
def test_vision_input_size_is_bounded(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_fall_escalation_has_safe_product_defaults():
    settings = Settings(_env_file=None)
    assert settings.fall_escalation_enabled is True
    assert settings.fall_call_after_seconds == 30
    assert settings.fall_escalation_poll_seconds == 2
    assert settings.fall_call_max_attempts == 3
    assert settings.fall_call_retry_seconds == 10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fall_call_after_seconds", 0),
        ("fall_escalation_poll_seconds", 0.1),
        ("fall_call_max_attempts", 0),
        ("fall_call_retry_seconds", 0),
    ],
)
def test_fall_escalation_rejects_unsafe_timing_values(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})

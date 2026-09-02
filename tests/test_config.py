import pytest
from pydantic import ValidationError

from src.config import Settings


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


@pytest.mark.parametrize("field,value", [("vision_input_width", 319), ("vision_input_width", 3841),
                                          ("vision_input_height", 239), ("vision_input_height", 2161)])
def test_vision_input_size_is_bounded(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})

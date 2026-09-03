import logging

from src.logging_filters import SuccessfulVisionLatestFilter


def access_record(method: str, path: str, status: int) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", method, path, "1.1", status),
        None,
    )


def test_successful_vision_latest_access_log_is_suppressed():
    assert SuccessfulVisionLatestFilter().filter(
        access_record("GET", "/api/v1/cameras/camera-1/vision/latest", 200)
    ) is False


def test_vision_latest_error_and_unrelated_api_access_logs_remain():
    filter_ = SuccessfulVisionLatestFilter()
    assert filter_.filter(access_record("GET", "/api/v1/cameras/camera-1/vision/latest", 500)) is True
    assert filter_.filter(access_record("GET", "/api/v1/cameras/camera-1", 200)) is True

import logging
import re

_VISION_LATEST_PATH = re.compile(r"^/api/v1/cameras/[^/?]+/vision/latest(?:\?.*)?$")


class SuccessfulVisionLatestFilter(logging.Filter):
    """Drop only successful high-frequency GET access records for vision/latest."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        method, path, status = args[1], args[2], args[4]
        try:
            successful = 200 <= int(status) < 300
        except (TypeError, ValueError):
            return True
        return not (
            method == "GET"
            and isinstance(path, str)
            and _VISION_LATEST_PATH.fullmatch(path) is not None
            and successful
        )


def install_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, SuccessfulVisionLatestFilter) for item in logger.filters):
        logger.addFilter(SuccessfulVisionLatestFilter())

"""OpenCV window and Flask MJPEG presentation for standalone sessions."""
from __future__ import annotations

import logging
import threading
import time

import cv2


class PreviewAdapter:
    def __init__(self, mode: str):
        self.mode = mode
        self.latest_frame = None
        self._lock = threading.Lock()
        self.stop_callback = None
        self._thread = None

    def start(self):
        if self.mode == "web":
            self._thread = threading.Thread(target=self._run_web, name="vision-web-preview", daemon=True)
            self._thread.start()

    def on_preview(self, frame, _result):
        if self.mode == "window":
            cv2.imshow("SDA-GCN Vision", frame)
            if cv2.waitKey(1) & 0xFF == ord("q") and self.stop_callback:
                self.stop_callback()
        elif self.mode == "web":
            with self._lock:
                self.latest_frame = frame.copy()

    def _generate_frames(self):
        while True:
            with self._lock:
                frame = self.latest_frame
            if frame is None:
                time.sleep(0.1)
                continue
            ok, encoded = cv2.imencode(".jpg", frame)
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + encoded.tobytes() + b"\r\n")
            time.sleep(0.03)

    def _run_web(self):
        from flask import Flask, Response
        app = Flask("sda_vision_preview")
        app.add_url_rule("/video_feed", "video_feed", lambda: Response(
            self._generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame"))
        app.add_url_rule("/", "index", lambda: (
            '<!doctype html><title>Vision Preview</title><img src="/video_feed" '
            'style="max-width:100%;height:auto">'))
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        app.run(host="127.0.0.1", port=8001, debug=False, use_reloader=False)

    def close(self):
        cv2.destroyAllWindows()


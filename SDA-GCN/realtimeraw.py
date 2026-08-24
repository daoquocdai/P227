"""Standalone raw-classifier CLI for the reusable sda_vision package."""
from sda_vision.cli import run_cli


if __name__ == "__main__":
    run_cli(raw_classifier=True)

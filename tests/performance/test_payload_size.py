import json
from uuid import uuid4

import pytest

from tests.performance.event_factory import make_event


def test_contract_payload_sizes_are_measurable_without_fake_uploads():
    run_id = str(uuid4())
    plain = json.dumps(make_event(run_id), separators=(",", ":")).encode()
    with_path = json.dumps(make_event(run_id, snapshot_path="perf/snapshot.jpg"), separators=(",", ":")).encode()
    assert len(with_path) > len(plain)


@pytest.mark.parametrize("size_kb", [100, 500, 1024])
def test_binary_snapshot_upload_not_supported_by_contract(size_kb):
    pytest.skip(f"NOT MEASURED: API accepts snapshot_path only; no binary upload endpoint for {size_kb} KB")

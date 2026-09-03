from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_card_uses_cover_but_detail_modal_uses_contain():
    css = (ROOT / "frontend/src/features/alerts/snapshot.css").read_text(encoding="utf-8")
    card = (ROOT / "frontend/src/features/alerts/SnapshotCard.tsx").read_text(encoding="utf-8")
    modal = (ROOT / "frontend/src/features/alerts/SnapshotModal.tsx").read_text(encoding="utf-8")

    assert ".snapshot-scene > img" in css
    assert "object-fit: cover" in css
    assert ".snapshot-scene.large > img" in css
    assert "object-fit: contain" in css
    assert 'className="snapshot-scene"' in card
    assert 'className="snapshot-scene large"' in modal


def test_modal_contain_preserves_landscape_portrait_and_square_aspect_ratios():
    container = (960, 540)
    for source in ((1920, 1080), (1080, 1920), (1080, 1080)):
        scale = min(container[0] / source[0], container[1] / source[1])
        rendered = (source[0] * scale, source[1] * scale)
        assert rendered[0] <= container[0]
        assert rendered[1] <= container[1]
        assert rendered[0] / rendered[1] == source[0] / source[1]


def test_fall_alert_renders_need_help_and_persisted_escalation_state():
    conversation = (ROOT / "frontend/src/features/alerts/AlertConversation.tsx").read_text(encoding="utf-8")
    service = (ROOT / "frontend/src/features/alerts/alertService.ts").read_text(encoding="utf-8")

    assert 'onStatus("need_help"' in conversation
    assert "Chưa xác nhận an toàn" in conversation
    assert "Đang liên hệ người thân" in conversation
    assert "Đã liên hệ người thân" in conversation
    assert "escalation_status" in service
    assert "escalation_due_at" in service

from pathlib import Path

from pixelle_video.device_farm.verification.profiles import (
    load_capture_profile,
    load_verification_profile,
)


def test_load_capture_profile(tmp_path: Path):
    path = tmp_path / "capture.yaml"
    path.write_text(
        """
schema_version: 1
device:
  id: vivo_v2199a_001
  logical_screen:
    width: 1080
    height: 2400
observation:
  provider: ms2130_opencv
  ms2130:
    camera_index: 1
    name_hint: MS2130
    expected_raw_size:
      width: 1920
      height: 1080
projection:
  rotation: 0
  normalized_size:
    width: 1080
    height: 2400
ch9329:
  port: COM5
  baudrate: 9600
""".strip(),
        encoding="utf-8",
    )

    profile = load_capture_profile(path)

    assert profile.device_id == "vivo_v2199a_001"
    assert profile.camera_index == 1
    assert profile.projection.raw_size == (1920, 1080)
    assert profile.projection.logical_size == (1080, 2400)
    assert profile.ch9329_port == "COM5"


def test_load_verification_profile(tmp_path: Path):
    path = tmp_path / "verification.yaml"
    path.write_text(
        """
schema_version: 1
flow:
  id: xhs_publish_note_v1
defaults:
  timeout_ms: 3000
rules:
  tap_feedback_near_target:
    layer: coordinate_closed_loop
    type: touch_feedback
    radius: 80
    threshold:
      min_changed_ratio: 0.015
    on_fail: manual_required
bindings:
  xhs.home.tap_publish:
    action:
      type: tap
      point: xhs.home.publish_button
      risk: reversible
    verify:
      - tap_feedback_near_target
""".strip(),
        encoding="utf-8",
    )

    profile = load_verification_profile(path)

    assert profile.flow_id == "xhs_publish_note_v1"
    assert profile.rules["tap_feedback_near_target"]["type"] == "touch_feedback"
    assert profile.bindings["xhs.home.tap_publish"]["action"]["point"] == "xhs.home.publish_button"

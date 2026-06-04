from __future__ import annotations

from content_factory.domain.automation.ch9329.executor import CH9329Executor
from content_factory.domain.automation.vision.screen_vision import VisionOutcome


class _StubController:
    def __init__(self):
        self.clicks = []
        self.screen_width = 1080
        self.screen_height = 2400

    def connect(self):
        return True

    def disconnect(self):
        return None

    def click(self, x_ratio, y_ratio):
        self.clicks.append((x_ratio, y_ratio))
        return True


class _FakeVision:
    def __init__(self, outcome, available=True):
        self._outcome = outcome
        self.available = available
        self.released = False

    def wait_for(self, template_ref, timeout=10.0, interval=0.5, threshold=0.8):
        return self._outcome

    def verify(self, template_ref, threshold=0.8):
        return self._outcome

    def release(self):
        self.released = True


def _executor(vision, simulate=False):
    return CH9329Executor(controller=_StubController(), simulate=simulate, vision=vision)


def test_wait_for_element_match_succeeds():
    ex = _executor(_FakeVision(VisionOutcome(matched=True, confidence=0.9)))
    res = ex.execute_flow([{"type": "wait_for_element", "template": "xhs/x"}], {})
    assert res[0].status == "succeeded"
    assert res[0].detail["matched"] is True


def test_wait_for_element_timeout_fails():
    ex = _executor(_FakeVision(VisionOutcome(matched=False, reason="timeout")))
    res = ex.execute_flow([{"type": "wait_for_element", "template": "xhs/x"}], {})
    assert res[0].status == "failed"


def test_vision_unavailable_degrades_to_pass():
    ex = _executor(_FakeVision(VisionOutcome(matched=False), available=False))
    res = ex.execute_flow([{"type": "verify_screen", "template": "xhs/x"}], {})
    assert res[0].status == "succeeded"
    assert res[0].detail["simulated"] is True


def test_simulate_degrades_to_pass_without_vision():
    ex = CH9329Executor(controller=_StubController(), simulate=True, vision=None)
    res = ex.execute_flow([{"type": "wait_for_element", "template": "xhs/x"}], {})
    assert res[0].status == "succeeded"
    assert res[0].detail["simulated"] is True


def test_click_on_match_clicks_center_ratio():
    ctrl = _StubController()
    vision = _FakeVision(VisionOutcome(matched=True, confidence=0.9, x_ratio=0.5, y_ratio=0.25))
    ex = CH9329Executor(controller=ctrl, simulate=False, vision=vision)
    res = ex.execute_flow([{"type": "click_on_match", "template": "xhs/btn"}], {})
    assert res[0].status == "succeeded"
    assert ctrl.clicks == [(0.5, 0.25)]


def test_default_flow_with_vision_steps_passes_in_simulate():
    from content_factory.workers.publish_worker import DEFAULT_FLOW_STEPS

    types = [s["type"] for s in DEFAULT_FLOW_STEPS]
    assert "wait_for_element" in types  # reference vision step present

    ex = CH9329Executor(simulate=True, vision=None)  # real simulate controller
    res = ex.execute_flow(DEFAULT_FLOW_STEPS, {})
    assert all(r.status in ("succeeded", "skipped") for r in res)

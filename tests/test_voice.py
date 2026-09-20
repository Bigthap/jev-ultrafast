"""Offline contracts for Desktop Voice Assistant and Controller. No paid APIs in tests."""

import json
import threading
from unittest.mock import Mock, patch

import numpy as np

from jev_ultrafast import voice
from jev_ultrafast.browser import Browser
from jev_ultrafast.voice_controller import ControllerState, TurnContext, VoiceController


def test_audio_recorder_empty():
    recorder = voice.AudioRecorder()
    assert recorder.sample_rate == 16000
    assert not recorder._recording


def test_transcribe_audio_empty():
    empty = np.zeros(0, dtype=np.int16)
    assert voice.transcribe_audio(empty) == ""


def test_pcm_to_wav_bytes():
    pcm = np.zeros(1600, dtype=np.int16)
    wav = voice.pcm_to_wav_bytes(pcm, sample_rate=16000)
    assert isinstance(wav, bytes)
    assert wav.startswith(b"RIFF")
    assert b"WAVE" in wav


def test_audio_recorder_stop_and_cancel_events():
    recorder = voice.AudioRecorder()
    stop_ev = threading.Event()
    cancel_ev = threading.Event()

    # Cancel immediately
    cancel_ev.set()
    with patch.object(recorder, "start"), patch.object(recorder, "stop", return_value=np.zeros(0, dtype=np.int16)):
        res = recorder.record_with_vad(max_seconds=1.0, cancel_event=cancel_ev)
        assert len(res) == 0

    # Stop immediately (Finish)
    stop_ev.set()
    fake_chunk = np.ones(160, dtype=np.int16)
    with patch.object(recorder, "start"):
        recorder._q.put(fake_chunk)
        res = recorder.record_with_vad(max_seconds=1.0, stop_event=stop_ev)
        assert len(res) > 0


def test_transcribe_openrouter_mocked(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "mock-openrouter-key")
    monkeypatch.setenv("VOICE_STT_MODEL", "meta/muse-voice-transcribe-1.0")

    pcm = np.zeros(1600, dtype=np.int16)

    class MockResponse:
        is_success = True

        def json(self):
            return {"text": "เปิด Facebook"}

    with patch("httpx.post", return_value=MockResponse()) as mock_post:
        result = voice.transcribe_openrouter(pcm)
        assert result == "เปิด Facebook"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["data"]["model"] == "meta/muse-voice-transcribe-1.0"
        assert "Bearer mock-openrouter-key" in call_kwargs["headers"]["Authorization"]


def test_transcribe_audio_prefers_openrouter(monkeypatch):
    pcm = np.zeros(1600, dtype=np.int16)
    with patch("jev_ultrafast.voice.transcribe_openrouter", return_value="เปิด Profile"):
        with patch("jev_ultrafast.voice.transcribe_google") as mock_google:
            res = voice.transcribe_audio(pcm)
            assert res == "เปิด Profile"
            mock_google.assert_not_called()


def test_parse_voice_intent_with_mocked_llm(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "mock-key")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://mock.api/v1")
    monkeypatch.setenv("TEXT_MODEL", "mock-model")

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "url": "https://www.youtube.com",
                            "goal": "Search for music",
                            "action_type": "navigate",
                        }
                    )
                }
            }
        ]
    }

    with patch("jev_ultrafast.voice.post_json", return_value=mock_response):
        res = voice.parse_voice_intent("เปิดเพลงใน YouTube")
        assert res["url"] == "https://www.youtube.com"
        assert "music" in res["goal"]


def test_parse_voice_intent_fallback_without_key(monkeypatch):
    monkeypatch.setattr(voice, "load_environment", lambda: None)
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)

    res_general = voice.parse_voice_intent("search for weather")
    assert res_general["url"] == "https://www.google.com"
    assert res_general["action_type"] == "navigate"
    assert res_general["goal"] == "search for weather"

    res_in_page = voice.parse_voice_intent("click next", current_url="https://example.com/items")
    assert res_in_page["action_type"] == "in_page"
    assert res_in_page["url"] is None


def test_parse_voice_intent_error_preserves_page_context(monkeypatch):
    """R05: Intent model failure must preserve current context and never navigate to Google/Flights."""
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "mock-key")
    with patch("jev_ultrafast.voice.post_json", side_effect=RuntimeError("Intent timeout")):
        res = voice.parse_voice_intent(
            "เลื่อนลง",
            current_url="https://mybank.com/transfer",
            current_title="Transfer Funds",
        )
        assert res["action_type"] == "in_page"
        assert res["url"] is None
        assert res["goal"] == "เลื่อนลง"


def test_parse_voice_intent_in_page_intent(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "mock-key")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://mock.api/v1")
    monkeypatch.setenv("TEXT_MODEL", "mock-model")

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "action_type": "in_page",
                            "url": None,
                            "goal": "Click on user Profile",
                        }
                    )
                }
            }
        ]
    }

    with patch("jev_ultrafast.voice.post_json", return_value=mock_response):
        res = voice.parse_voice_intent(
            "เข้าหน้า Profile",
            current_url="https://www.facebook.com",
            current_title="Facebook",
        )
        assert res["action_type"] == "in_page"
        assert res["url"] is None
        assert res["goal"] == "Click on user Profile"


def test_parse_voice_intent_same_domain_normalization(monkeypatch):
    """R09: Root same-domain normalizes to in_page; distinct path preserved as navigate."""
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "mock-key")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://mock.api/v1")
    monkeypatch.setenv("TEXT_MODEL", "mock-model")

    # 1. Root / same path navigation normalizes to in_page
    mock_same_path = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "action_type": "navigate",
                            "url": "https://www.facebook.com/home",
                            "goal": "Refresh home",
                        }
                    )
                }
            }
        ]
    }
    with patch("jev_ultrafast.voice.post_json", return_value=mock_same_path):
        res = voice.parse_voice_intent(
            "รีเฟรชหน้าแรก",
            current_url="https://www.facebook.com/home",
            current_title="Facebook",
        )
        assert res["action_type"] == "in_page"
        assert res["url"] is None

    # 2. Explicit new path navigation preserves navigate
    mock_new_path = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "action_type": "navigate",
                            "url": "https://www.facebook.com/settings",
                            "goal": "Open settings",
                        }
                    )
                }
            }
        ]
    }
    with patch("jev_ultrafast.voice.post_json", return_value=mock_new_path):
        res = voice.parse_voice_intent(
            "เปิดการตั้งค่า",
            current_url="https://www.facebook.com/home",
            current_title="Facebook",
        )
        assert res["action_type"] == "navigate"
        assert res["url"] == "https://www.facebook.com/settings"


def test_continuous_voice_session_in_page():
    session = voice.ContinuousVoiceSession()
    mock_agent = Mock()
    mock_agent.state = {"status": "done", "history": []}
    mock_agent.browser = Mock()
    session.agent = mock_agent

    with patch.object(
        session,
        "get_current_info",
        return_value={"url": "https://www.facebook.com", "title": "Facebook", "target_id": "tab-1"},
    ):
        with patch(
            "jev_ultrafast.voice.parse_voice_intent",
            return_value={"action_type": "in_page", "url": None, "goal": "Click Profile"},
        ):
            intent_called = []

            def on_intent(intent, curr_url, curr_title):
                intent_called.append(intent)

            res = session.process_command("เข้าหน้า Profile", on_intent=on_intent)
            assert res["action_type"] == "in_page"
            assert len(intent_called) == 1
            session.agent.set_goal.assert_called_once_with("Click Profile")
            session.agent.browser.activate_tab.assert_called_once()


def test_continuous_voice_session_honest_outcomes():
    """R11 & R13: Honest outcomes (budget_exceeded, unverified) and step deduplication."""
    session = voice.ContinuousVoiceSession()
    mock_agent = Mock()
    step1 = {"action": "Click Search", "kind": "click", "step": 1}
    step2 = {"action": "Type query", "kind": "fill", "step": 2}
    mock_agent.state = {"status": "ready", "history": [step1, step2]}
    session.agent = mock_agent

    emitted_steps = []

    def on_step(s, state):
        emitted_steps.append(s)

    with patch.object(session, "get_current_info", return_value=None):
        with patch(
            "jev_ultrafast.voice.parse_voice_intent",
            return_value={"action_type": "in_page", "url": None, "goal": "Search"},
        ):
            # 1. Step budget exceeded returns budget_exceeded (never Done)
            res = session.process_command("Search", max_steps=2, on_step=on_step)
            assert res["status"] == "budget_exceeded"
            assert len(emitted_steps) == 2

            # 2. Model choosing DONE returns unverified (since no independent verifier)
            mock_agent.state["status"] = "done"
            res_done = session.process_command("Search", max_steps=10)
            assert res_done["status"] == "unverified"


def test_browser_hostname_matching_query_params():
    """R03: URL with target domain inside query string must not match hostname."""
    fake_targets = [
        {"targetId": "tab-google", "type": "page", "url": "https://www.google.com/search?q=facebook.com"},
        {"targetId": "tab-fb", "type": "page", "url": "https://www.facebook.com/feed"},
    ]

    with patch("jev_ultrafast.browser.ensure_daemon"), patch(
        "jev_ultrafast.browser.cdp",
        side_effect=lambda method, **kwargs: (
            {"targetInfos": fake_targets}
            if method == "Target.getTargets"
            else {"sessionId": "s1"}
            if method == "Target.attachToTarget"
            else {"result": {"value": "complete"}}
            if method == "Runtime.evaluate"
            else {}
        ),
    ):
        # Searching for facebook.com should match tab-fb, NOT tab-google
        browser = Browser("https://facebook.com", reuse_tab=True)
        assert browser.target == "tab-fb"
        assert browser.owns_target is False


def test_browser_close_borrowed_tab_only_detaches():
    """R06: Borrowed tab close only detaches, never closes the user's tab."""
    cdp_calls = []

    def mock_cdp(method, **kwargs):
        cdp_calls.append((method, kwargs))
        if method == "Target.getTargets":
            return {"targetInfos": [{"targetId": "user-tab-1", "type": "page", "url": "https://example.com"}]}
        if method == "Target.attachToTarget":
            return {"sessionId": "session-1"}
        if method == "Runtime.evaluate":
            return {"result": {"value": "complete"}}
        return {}

    with patch("jev_ultrafast.browser.ensure_daemon"), patch("jev_ultrafast.browser.cdp", side_effect=mock_cdp):
        browser = Browser("https://example.com", reuse_tab=True)
        assert browser.owns_target is False

        browser.close()
        methods = [m[0] for m in cdp_calls]
        assert "Target.detachFromTarget" in methods
        assert "Target.closeTarget" not in methods


def test_agent_set_goal_resets_per_turn_metrics():
    """R12: Agent.set_goal resets text_calls and elapsed_ms while updating session counters."""
    with patch("jev_ultrafast.agent.Browser") as mock_browser_cls:
        mock_browser = Mock()
        mock_browser.observe.return_value = {
            "actions": [],
            "fingerprint": "fp1",
            "url": "https://example.com",
            "screenshot": "",
        }
        mock_browser_cls.return_value = mock_browser

        from jev_ultrafast.agent import Agent

        agent = Agent("https://example.com", "Goal 1")
        agent.state["text_calls"] = [{"model": "m1", "value": "text1"}]
        agent.state["elapsed_ms"] = 1200

        # Change goal for Turn 2
        agent.set_goal("Goal 2")

        # Per-turn state must be reset
        assert agent.state["text_calls"] == []
        assert agent.state["elapsed_ms"] == 0
        # Session metrics must be preserved
        assert len(agent.session_text_calls) == 1
        assert agent.session_elapsed_ms == 1200


def test_voice_controller_lifecycle_and_cancellation():
    """R01, R02: VoiceController state machine, atomic turns, and cancellation token."""
    mock_session = Mock()
    mock_recorder = Mock()
    mock_recorder.record_with_vad.return_value = np.zeros(0, dtype=np.int16)

    controller = VoiceController(session=mock_session, recorder=mock_recorder)
    states = []
    controller.add_state_listener(lambda s, d: states.append(s))

    assert controller.state == ControllerState.IDLE

    # Start recording
    started = controller.start_recording()
    assert started is True
    assert controller.state == ControllerState.RECORDING

    # Double start is rejected
    double_started = controller.start_recording()
    assert double_started is False

    # Cancel task immediately halts
    cancelled = controller.cancel_task()
    assert cancelled is True
    assert controller.state == ControllerState.CANCELLED

    # Finish recording
    controller.state = ControllerState.RECORDING
    controller.current_turn = TurnContext(turn_id=99)
    finished = controller.finish_recording()
    assert finished is True
    assert controller.current_turn.stop_event.is_set()

    controller.shutdown(timeout=1.0)

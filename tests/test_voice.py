"""Offline contracts for Desktop Voice Assistant. No paid APIs in tests."""

import json
from unittest.mock import patch

import numpy as np

from jev_ultrafast import voice


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
                            "url": "https://www.google.com/travel/flights?hl=en",
                            "goal": "Find flights from Bangkok to Tokyo in October 2026.",
                        }
                    )
                }
            }
        ]
    }

    with patch("jev_ultrafast.voice.post_json", return_value=mock_response):
        res = voice.parse_voice_intent("หาตั๋วเครื่องบินไปโตเกียว")
        assert res["url"] == "https://www.google.com/travel/flights?hl=en"
        assert "Tokyo" in res["goal"]


def test_parse_voice_intent_fallback_without_key(monkeypatch):
    monkeypatch.setattr(voice, "load_environment", lambda: None)
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    res = voice.parse_voice_intent("flight to London")
    assert res["url"] == "https://www.google.com/travel/flights?hl=en"
    assert res["goal"] == "flight to London"

    res_general = voice.parse_voice_intent("search for weather")
    assert res_general["url"] == "https://www.google.com"
    assert res_general["goal"] == "search for weather"


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
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "mock-key")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://mock.api/v1")
    monkeypatch.setenv("TEXT_MODEL", "mock-model")

    # If the model returns navigate with a URL on the same domain, it should be normalized to in_page
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "action_type": "navigate",
                            "url": "https://www.facebook.com/profile.php",
                            "goal": "Open profile",
                        }
                    )
                }
            }
        ]
    }

    with patch("jev_ultrafast.voice.post_json", return_value=mock_response):
        res = voice.parse_voice_intent(
            "เข้าหน้าโปรไฟล์",
            current_url="https://www.facebook.com/home",
            current_title="Facebook",
        )
        assert res["action_type"] == "in_page"
        assert res["url"] is None


def test_continuous_voice_session_in_page():
    session = voice.ContinuousVoiceSession()
    mock_agent = patch("jev_ultrafast.agent.Agent").start()
    session.agent = mock_agent
    session.agent.state = {"status": "done", "history": []}
    session.agent.browser = patch("jev_ultrafast.browser.Browser").start()

    with patch.object(
        session,
        "get_current_info",
        return_value={"url": "https://www.facebook.com", "title": "Facebook"},
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


def test_continuous_voice_session_navigate():
    session = voice.ContinuousVoiceSession()
    mock_agent = patch("jev_ultrafast.agent.Agent").start()
    session.agent = mock_agent
    session.agent.state = {"status": "done", "history": []}

    with patch.object(session, "get_current_info", return_value=None):
        with patch(
            "jev_ultrafast.voice.parse_voice_intent",
            return_value={"action_type": "navigate", "url": "https://www.youtube.com", "goal": "Open YouTube"},
        ):
            res = session.process_command("เปิด YouTube")
            assert res["action_type"] == "navigate"
            session.agent.navigate_to.assert_called_once_with("https://www.youtube.com", goal="Open YouTube")


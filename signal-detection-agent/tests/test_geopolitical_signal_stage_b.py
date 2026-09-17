"""Unit tests for Stage B (HIGH/WEAK model call + validation) of the
geopolitical_signal pipeline."""
import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pipeline.geopolitical_signal_stage_b import classify_geopolitical_signal_headline


def _mock_response(content: str):
    payload = {"choices": [{"message": {"content": content}}]}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


def _classify(content_or_exception):
    with patch("pipeline.geopolitical_signal_stage_b.urlopen") as mock_urlopen:
        if isinstance(content_or_exception, Exception):
            mock_urlopen.side_effect = content_or_exception
        else:
            mock_urlopen.return_value = _mock_response(content_or_exception)
        return classify_geopolitical_signal_headline(
            "Iran closes the Strait of Hormuz",
            system_prompt="test prompt",
            model="test-model",
            api_key="test-key",
            base_url="https://example.test",
            timeout=10,
        )


def test_exact_high_is_accepted():
    assert _classify("HIGH") == "HIGH"


def test_exact_weak_is_accepted():
    assert _classify("WEAK") == "WEAK"


def test_lowercase_is_normalized():
    assert _classify("high") == "HIGH"
    assert _classify("weak") == "WEAK"


def test_whitespace_is_stripped():
    assert _classify("  HIGH  \n") == "HIGH"


def test_extra_text_defaults_to_weak():
    assert _classify("HIGH, because the strait is a major chokepoint") == "WEAK"


def test_unrecognized_word_defaults_to_weak():
    assert _classify("MAYBE") == "WEAK"


def test_empty_response_defaults_to_weak():
    assert _classify("") == "WEAK"


def test_request_exception_defaults_to_weak():
    assert _classify(ConnectionError("boom")) == "WEAK"


def test_no_retry_on_failure():
    # a single failure should not trigger any retry call
    with patch("pipeline.geopolitical_signal_stage_b.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = TimeoutError("timeout")
        classify_geopolitical_signal_headline(
            "test", system_prompt="p", model="m", api_key="k",
            base_url="https://example.test", timeout=10,
        )
    assert mock_urlopen.call_count == 1

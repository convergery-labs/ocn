"""Unit tests for Stage C, Layer 2 (model call + JSON validation)."""
import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pipeline.geopolitical_signal_layer2 import classify_geopolitical_signal_tags


def _mock_response(content: str):
    payload = {"choices": [{"message": {"content": content}}]}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


def _classify(content_or_exception):
    with patch("pipeline.geopolitical_signal_layer2.urlopen") as mock_urlopen:
        if isinstance(content_or_exception, Exception):
            mock_urlopen.side_effect = content_or_exception
        else:
            mock_urlopen.return_value = _mock_response(content_or_exception)
        return classify_geopolitical_signal_tags(
            "US announces new export controls on chipmaking equipment to China",
            system_prompt="test prompt",
            model="test-model",
            api_key="test-key",
            base_url="https://example.test",
            timeout=10,
        )


def test_well_formed_response_is_parsed_correctly():
    content = json.dumps({
        "channel": "trade",
        "actors": ["US", "China"],
        "assets": ["semis", "broad_equities"],
        "impacted_categories": ["Semiconductor Manufacturing", "Cloud & Compute Platforms"],
        "one_line": "US imposes new export controls on chip tools to China.",
    })
    result = _classify(content)
    assert result["channel"] == "trade"
    assert result["actors"] == ["US", "China"]
    assert result["assets"] == ["semis", "broad_equities"]
    assert result["impacted_categories"] == ["Semiconductor Manufacturing", "Cloud & Compute Platforms"]
    assert result["one_line"].startswith("US imposes")


def test_invalid_channel_value_is_dropped_not_whole_response():
    content = json.dumps({
        "channel": "not_a_real_channel",
        "actors": ["US"],
        "assets": ["semis"],
        "impacted_categories": ["Semiconductor Manufacturing"],
        "one_line": "Something happened.",
    })
    result = _classify(content)
    assert result["channel"] is None
    # other valid fields should survive independently
    assert result["actors"] == ["US"]
    assert result["assets"] == ["semis"]


def test_invalid_asset_is_filtered_out_valid_ones_kept():
    content = json.dumps({
        "channel": "trade",
        "actors": ["US"],
        "assets": ["semis", "not_a_real_asset", "broad_equities"],
        "impacted_categories": [],
        "one_line": "Something happened.",
    })
    result = _classify(content)
    assert result["assets"] == ["semis", "broad_equities"]


def test_unrecognized_category_is_filtered_out():
    content = json.dumps({
        "channel": "trade",
        "actors": ["US"],
        "assets": ["semis"],
        "impacted_categories": ["Semiconductor Manufacturing", "Not A Real Category"],
        "one_line": "Something happened.",
    })
    result = _classify(content)
    assert result["impacted_categories"] == ["Semiconductor Manufacturing"]


def test_malformed_json_fails_open_to_all_none():
    result = _classify("this is not JSON at all {broken")
    assert result == {
        "channel": None, "actors": None, "assets": None,
        "impacted_categories": None, "one_line": None,
    }


def test_non_dict_json_fails_open():
    result = _classify(json.dumps(["a", "list", "not", "a", "dict"]))
    assert result["channel"] is None
    assert result["one_line"] is None


def test_network_error_fails_open():
    result = _classify(ConnectionError("boom"))
    assert result["channel"] is None


def test_empty_string_one_line_is_treated_as_none():
    content = json.dumps({
        "channel": "trade", "actors": [], "assets": [],
        "impacted_categories": [], "one_line": "   ",
    })
    result = _classify(content)
    assert result["one_line"] is None


def test_markdown_fenced_json_is_parsed_correctly():
    # Confirmed live: the model wraps its JSON in a ```json ... ``` fence
    # despite the prompt saying "Return ONLY a JSON object" - without
    # stripping this, every single Layer 2 call would fail-open to null
    # tags, even on a well-formed, correct model response.
    inner = json.dumps({
        "channel": "trade",
        "actors": ["United States", "China", "Nvidia"],
        "assets": ["semis"],
        "impacted_categories": ["Semiconductor Manufacturing"],
        "one_line": "US export controls on Nvidia AI chips restrict China's access.",
    })
    content = f"```json\n{inner}\n```"
    result = _classify(content)
    assert result["channel"] == "trade"
    assert result["impacted_categories"] == ["Semiconductor Manufacturing"]


def test_no_retry_on_failure():
    with patch("pipeline.geopolitical_signal_layer2.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = TimeoutError("timeout")
        classify_geopolitical_signal_tags(
            "test", system_prompt="p", model="m", api_key="k",
            base_url="https://example.test", timeout=10,
        )
    assert mock_urlopen.call_count == 1

import pytest

from b2t.config import _load_stt_profile


def test_stt_profile_rejects_boolean_speaker_count() -> None:
    with pytest.raises(ValueError, match="speaker_count 必须是正整数"):
        _load_stt_profile({"speaker_count": True}, key="qwen")

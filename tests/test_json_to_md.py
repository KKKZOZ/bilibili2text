import json
from pathlib import Path

from b2t.converter.json_to_md import convert_json_to_md


def test_convert_qwen_sentences_preserves_each_timestamp(tmp_path: Path) -> None:
    source_path = tmp_path / "BV1ABcsztEcY_transcription.json"
    source_path.write_text(
        json.dumps(
            {
                "transcripts": [
                    {
                        "sentences": [
                            {"begin_time": 1234, "text": "提到标的一"},
                            {"begin_time": 65900, "text": "提到标的二"},
                        ]
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    markdown = convert_json_to_md(source_path).read_text(encoding="utf-8")

    assert "Speaker 00:01\n提到标的一" in markdown
    assert "Speaker 01:05\n提到标的二" in markdown


def test_convert_plain_text_keeps_untimed_fallback(tmp_path: Path) -> None:
    source_path = tmp_path / "upload_transcription.json"
    source_path.write_text(
        json.dumps({"text": "没有时间轴的纯文本"}, ensure_ascii=False),
        encoding="utf-8",
    )

    markdown = convert_json_to_md(source_path).read_text(encoding="utf-8")

    assert "Speaker 00:00\n没有时间轴的纯文本" in markdown


def test_convert_json_to_md_preserves_zero_speaker_id(tmp_path: Path) -> None:
    json_path = tmp_path / "episode_transcription.json"
    json_path.write_text(
        json.dumps(
            {
                "transcripts": [
                    {
                        "sentences": [
                            {
                                "begin_time": 0,
                                "speaker_id": 0,
                                "text": "first speaker",
                            },
                            {
                                "begin_time": 1000,
                                "speaker_id": 1,
                                "text": "second speaker",
                            },
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    output_path = convert_json_to_md(json_path, min_length=100)
    markdown = output_path.read_text(encoding="utf-8")

    assert "[spk_0] first speaker" in markdown
    assert "[spk_1] second speaker" in markdown

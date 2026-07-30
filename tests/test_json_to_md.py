import json

from b2t.converter.json_to_md import convert_json_to_md


def test_convert_qwen_sentences_preserves_each_timestamp(tmp_path) -> None:
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


def test_convert_plain_text_keeps_untimed_fallback(tmp_path) -> None:
    source_path = tmp_path / "upload_transcription.json"
    source_path.write_text(
        json.dumps({"text": "没有时间轴的纯文本"}, ensure_ascii=False),
        encoding="utf-8",
    )

    markdown = convert_json_to_md(source_path).read_text(encoding="utf-8")

    assert "Speaker 00:00\n没有时间轴的纯文本" in markdown

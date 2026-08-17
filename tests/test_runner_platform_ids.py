import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend import runner


def test_infer_resource_id_for_supported_podcast_urls(monkeypatch) -> None:
    xiaoyuzhou_url = "https://www.xiaoyuzhoufm.com/episode/6a0a7365e1eb34a93997ffa2"
    normalized, resource_id = runner._infer_resource_id_from_url(xiaoyuzhou_url)
    assert normalized == xiaoyuzhou_url
    assert resource_id == "xiaoyuzhou_6a0a7365e1eb34a93997ffa2"

    monkeypatch.setattr(
        runner,
        "resolve_ximalaya_sound_url",
        lambda url: ("https://www.ximalaya.com/sound/12345", "12345"),
    )
    normalized, resource_id = runner._infer_resource_id_from_url(
        "https://xima.tv/example"
    )
    assert normalized == "https://www.ximalaya.com/sound/12345"
    assert resource_id == "ximalaya_12345"


def test_infer_resource_id_distinguishes_bilibili_multipart_page() -> None:
    normalized, resource_id = runner._infer_resource_id_from_url(
        "https://www.bilibili.com/video/BV1anbR6EEje"
        "?vd_source=0913c1e4dedf4378c61d39741a2d6190&p=2"
    )

    assert normalized == "https://www.bilibili.com/video/BV1anbR6EEje?p=2"
    assert resource_id == "BV1anbR6EEje_p2"


def test_bilibili_multipart_page_uses_page_specific_cache_id(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeStorage:
        pass

    monkeypatch.setattr(runner, "get_runtime_app_config", lambda **kwargs: object())
    monkeypatch.setattr(runner, "get_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(runner, "get_stt_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(runner, "_append_job_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner,
        "_update_job",
        lambda job_id, **kwargs: captured.update(kwargs),
    )

    def fake_handle_if_existing(**kwargs) -> bool:
        captured["lookup_bvid"] = kwargs["bvid"]
        captured["lookup_transcription_id"] = kwargs["transcription_id"]
        return True

    monkeypatch.setattr(
        runner.existing_transcription_service,
        "handle_if_existing",
        fake_handle_if_existing,
    )

    runner._run_job(
        "job-bilibili-p2",
        url=(
            "https://www.bilibili.com/video/BV1anbR6EEje"
            "?vd_source=0913c1e4dedf4378c61d39741a2d6190&p=2"
        ),
        skip_summary=True,
        summary_preset=None,
        summary_profile=None,
        summary_prompt_template=None,
        auto_generate_fancy_html=False,
    )

    assert captured["lookup_bvid"] == "BV1anbR6EEje"
    assert captured["lookup_transcription_id"] == "BV1anbR6EEje_p2"
    assert captured["bvid"] == "BV1anbR6EEje"


def test_podcast_resource_id_enables_existing_transcription_reuse(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeStorage:
        pass

    monkeypatch.setattr(runner, "get_runtime_app_config", lambda **kwargs: object())
    monkeypatch.setattr(runner, "get_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(runner, "get_stt_storage_backend", lambda: FakeStorage())
    monkeypatch.setattr(runner, "_append_job_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner,
        "_update_job",
        lambda job_id, **kwargs: captured.update(kwargs),
    )

    def fake_handle_if_existing(**kwargs) -> bool:
        captured["lookup_bvid"] = kwargs["bvid"]
        return True

    monkeypatch.setattr(
        runner.existing_transcription_service,
        "handle_if_existing",
        fake_handle_if_existing,
    )
    monkeypatch.setattr(
        runner,
        "run_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cache hit should skip pipeline")
        ),
    )

    runner._run_job(
        "job-podcast",
        url="https://www.xiaoyuzhoufm.com/episode/6a0a7365e1eb34a93997ffa2",
        skip_summary=True,
        summary_preset=None,
        summary_profile=None,
        summary_prompt_template=None,
        auto_generate_fancy_html=False,
    )

    assert captured["lookup_bvid"] == "xiaoyuzhou_6a0a7365e1eb34a93997ffa2"
    assert captured["bvid"] == "xiaoyuzhou_6a0a7365e1eb34a93997ffa2"

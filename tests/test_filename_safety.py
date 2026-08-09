import json
from pathlib import Path

from b2t.config import create_app_config
from b2t.download.platform import build_filename_component, truncate_utf8_bytes
from b2t.pipeline import run_pipeline
from b2t.storage.local import LocalStorageBackend


def test_build_filename_component_preserves_prefix_suffix_and_utf8_boundary() -> None:
    platform_id = "xiaoyuzhou_0123456789abcdefghijklmn"
    prefix = f"{platform_id}_"
    assert (
        build_filename_component(
            "episode",
            prefix=prefix,
            suffix=".m4a",
            reserved_suffix="_summary_no_table.png",
        )
        == f"{prefix}episode.m4a"
    )

    filename = build_filename_component(
        "中文标题" * 30,
        prefix=prefix,
        suffix=".m4a",
        reserved_suffix="_summary_no_table.png",
    )

    assert filename.startswith(prefix)
    assert filename.endswith(".m4a")
    assert len(filename.encode("utf-8")) <= 255
    assert len(f"{Path(filename).stem}_summary_no_table.png".encode("utf-8")) <= 255
    assert truncate_utf8_bytes("中文", 4) == "中"


def test_pipeline_limits_long_utf8_names_without_losing_platform_id_or_extension(
    monkeypatch, tmp_path: Path
) -> None:
    config = create_app_config(output_dir=tmp_path)
    storage = LocalStorageBackend(tmp_path)
    platform_id = "xiaoyuzhou_0123456789abcdefghijklmn"
    source_audio = tmp_path / f"{'中' * 78}.第二集.m4a"
    source_audio.write_bytes(b"audio")

    class FakeSttProvider:
        def transcribe(self, audio_path, work_dir, progress_callback=None):
            json_path = work_dir / f"{Path(audio_path).stem}_transcription.json"
            json_path.write_text(
                json.dumps({"text": "transcript"}),
                encoding="utf-8",
            )
            return json_path

    monkeypatch.setattr(
        "b2t.pipeline.create_stt_provider",
        lambda *args, **kwargs: FakeSttProvider(),
    )

    results = run_pipeline(
        "",
        config,
        audio_path=source_audio,
        input_bvid=platform_id,
        skip_summary=True,
        storage_backend=storage,
        stt_storage_backend=storage,
    )

    artifact_paths = [
        Path(results[key].storage_key) for key in ("audio", "json", "markdown")
    ]
    work_dir = artifact_paths[0].parent

    assert work_dir.name.startswith(platform_id)
    assert len(work_dir.name.encode("utf-8")) <= 255
    assert artifact_paths[0].name.endswith(".m4a")
    for artifact_path in artifact_paths:
        assert artifact_path.name.startswith(platform_id)
        assert len(artifact_path.name.encode("utf-8")) <= 255

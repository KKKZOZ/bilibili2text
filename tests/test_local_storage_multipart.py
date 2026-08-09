from pathlib import Path

from b2t.storage.local import LocalStorageBackend


def _write_transcription(directory: Path, prefix: str) -> None:
    directory.mkdir()
    (directory / f"{prefix}_transcription.json").write_text("{}", encoding="utf-8")
    (directory / f"{prefix}_transcription.md").write_text("content", encoding="utf-8")


def test_local_storage_keeps_multipart_transcriptions_separate(tmp_path: Path) -> None:
    bvid = "BV1ua4y1Y7yX"
    base_dir = tmp_path / f"{bvid}_base-title"
    part_dir = tmp_path / f"{bvid}_p3_part-title"
    _write_transcription(base_dir, f"{bvid}_base-title")
    _write_transcription(part_dir, f"{bvid}_p3_part-title")
    storage = LocalStorageBackend(tmp_path)

    base = storage.find_existing_transcription(bvid)
    part = storage.find_existing_transcription(f"{bvid}_p3")

    assert base is not None
    assert part is not None
    assert Path(base["markdown"].storage_key).parent == base_dir
    assert Path(part["markdown"].storage_key).parent == part_dir

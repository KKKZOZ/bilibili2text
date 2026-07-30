import sys
import tempfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.download_registry import DownloadRegistry, media_type_for_filename
from backend.job_store import JobPatch, JobRepository
from backend.routes.download import (
    _find_precomputed_conversion,
    convert_artifact,
    preview_timeline_text,
)
from backend.schemas import ConvertRequest

from b2t.converter.converter import ConversionFormat
from b2t.storage import StoredArtifact


def test_job_repository_create_patch_cancel() -> None:
    repository = JobRepository(limit=10)
    created = repository.create(
        skip_summary=False,
        summary_preset=None,
        summary_profile=None,
        auto_generate_fancy_html=True,
    )

    job_id = str(created["job_id"])
    repository.patch(
        job_id,
        JobPatch(
            status="running",
            stage="downloading",
            progress=25,
            bvid="BV1234567890",
        ),
    )

    running = repository.get(job_id)
    assert running is not None
    assert running["status"] == "running"
    assert running["stage"] == "downloading"
    assert running["progress"] == 25
    assert running["bvid"] == "BV1234567890"

    cancelled, status = repository.cancel(job_id)
    assert cancelled is True
    assert status == "cancelled"
    assert repository.get(job_id)["status"] == "cancelled"


def test_download_registry_artifacts_content_and_media_types() -> None:
    registry = DownloadRegistry(artifact_limit=10, content_limit=10)
    artifact = StoredArtifact(
        filename="summary.md",
        storage_key="runs/summary.md",
        backend="local",
    )

    artifact_id = registry.store_artifact(artifact)
    content_id = registry.store_content(b"hello", "answer.txt")

    assert registry.get_artifact(artifact_id) == artifact
    assert registry.get_content(content_id) == (b"hello", "answer.txt")
    assert media_type_for_filename("answer.txt") == "text/plain; charset=utf-8"
    assert media_type_for_filename("summary.md") == "text/markdown; charset=utf-8"

    registry.remove_artifacts_by_storage_keys({"runs/summary.md"})
    assert registry.get_artifact(artifact_id) is None


def test_preview_timeline_text_returns_inline_plain_text(monkeypatch) -> None:
    timeline = "01:08 新易盛（300502.SZ）\n01:45 威高股份（01066.HK）\n"
    artifact = StoredArtifact(
        filename="BV123_summary_timeline.txt",
        storage_key="runs/BV123_summary_timeline.txt",
        backend="local",
    )

    class FakeStorage:
        @contextmanager
        def open_stream(self, storage_key: str) -> Iterator[object]:
            assert storage_key == artifact.storage_key
            with BytesIO(timeline.encode("utf-8")) as stream:
                yield stream

    monkeypatch.setattr(
        "backend.routes.download.download_registry.get_artifact",
        lambda download_id: artifact,
    )
    monkeypatch.setattr("backend.routes.download.get_storage_backend", FakeStorage)

    response = preview_timeline_text("timeline-id")

    assert response.body.decode("utf-8") == timeline
    assert response.media_type == "text/plain"
    assert response.headers["content-disposition"].startswith("inline;")


def test_find_precomputed_conversion_uses_summary_sibling_png(monkeypatch) -> None:
    class FakeStorage:
        @contextmanager
        def open_stream(self, storage_key: str) -> Iterator[object]:
            if storage_key != "runs/BV123_summary.png":
                raise FileNotFoundError(storage_key)
            yield object()

    monkeypatch.setattr("backend.routes.download.get_storage_backend", FakeStorage)
    artifact = StoredArtifact(
        filename="BV123_summary.md",
        storage_key="runs/BV123_summary.md",
        backend="local",
    )

    found = _find_precomputed_conversion(
        artifact=artifact,
        target_format=ConversionFormat.PNG,
        source_variant=None,
    )

    assert found == StoredArtifact(
        filename="BV123_summary.png",
        storage_key="runs/BV123_summary.png",
        backend="local",
    )


def test_find_precomputed_conversion_uses_summary_no_table_png(
    monkeypatch,
) -> None:
    class FakeStorage:
        @contextmanager
        def open_stream(self, storage_key: str) -> Iterator[object]:
            if storage_key != "runs/BV123_summary_no_table.png":
                raise FileNotFoundError(storage_key)
            yield object()

    monkeypatch.setattr("backend.routes.download.get_storage_backend", FakeStorage)
    artifact = StoredArtifact(
        filename="BV123_summary.md",
        storage_key="runs/BV123_summary.md",
        backend="local",
    )

    found = _find_precomputed_conversion(
        artifact=artifact,
        target_format=ConversionFormat.PNG,
        source_variant="summary_no_table",
    )

    assert found == StoredArtifact(
        filename="BV123_summary_no_table.png",
        storage_key="runs/BV123_summary_no_table.png",
        backend="local",
    )


def test_convert_artifact_uses_higher_dpr_only_for_summary_png(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        summary_path = temp_root / "BV123_summary.md"
        summary_path.write_text("# summary\n", encoding="utf-8")
        table_path = temp_root / "BV123_summary_table.md"
        table_path.write_text("| code |\n| --- |\n| 600000.SH |\n", encoding="utf-8")

        summary_artifact = StoredArtifact(
            filename=summary_path.name,
            storage_key=str(summary_path),
            backend="local",
        )
        table_artifact = StoredArtifact(
            filename=table_path.name,
            storage_key=str(table_path),
            backend="local",
        )

        captured: list[dict[str, object]] = []

        class FakeStorage:
            @contextmanager
            def open_stream(self, storage_key: str) -> Iterator[object]:
                with open(storage_key, "rb") as handle:
                    yield handle

            def store_file(
                self, local_path: Path, *, object_key: str
            ) -> StoredArtifact:
                return StoredArtifact(
                    filename=Path(local_path).name,
                    storage_key=object_key,
                    backend="local",
                )

        def fake_convert_file(input_path, target_format, output_path=None, **options):
            output = Path(output_path or Path(input_path).with_suffix(".png"))
            output.write_bytes(b"png")
            captured.append(
                {
                    "name": Path(input_path).name,
                    "target_format": target_format,
                    "options": options,
                }
            )
            return output

        monkeypatch.setattr(
            "backend.routes.download.download_registry.get_artifact",
            lambda download_id: (
                summary_artifact if download_id == "summary" else table_artifact
            ),
        )
        monkeypatch.setattr("backend.routes.download.get_storage_backend", FakeStorage)
        monkeypatch.setattr(
            "backend.routes.download._find_precomputed_conversion",
            lambda **kwargs: None,
        )
        monkeypatch.setattr("backend.routes.download.convert_file", fake_convert_file)
        monkeypatch.setattr(
            "backend.routes.download._lookup_artifact_pubdate",
            lambda storage_key: "2026-02-05 21:00:00",
        )

        convert_artifact(ConvertRequest(download_id="summary", target_format="png"))
        convert_artifact(ConvertRequest(download_id="table", target_format="png"))

        assert captured[0]["name"] == "BV123_summary.md"
        assert captured[0]["options"]["dpr"] == 4
        assert captured[0]["options"]["is_table"] is False

        assert captured[1]["name"] == "BV123_summary_table.md"
        assert "dpr" not in captured[1]["options"]
        assert captured[1]["options"]["is_table"] is True
        assert captured[1]["options"]["as_of_date"] == "2026-02-05 21:00:00"


def test_convert_artifact_desktop_png_uses_pad_viewport(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        summary_path = temp_root / "BV123_summary.md"
        summary_path.write_text("# summary\n", encoding="utf-8")

        summary_artifact = StoredArtifact(
            filename=summary_path.name,
            storage_key=str(summary_path),
            backend="local",
        )

        captured: list[dict[str, object]] = []

        class FakeStorage:
            @contextmanager
            def open_stream(self, storage_key: str) -> Iterator[object]:
                with open(storage_key, "rb") as handle:
                    yield handle

            def store_file(
                self, local_path: Path, *, object_key: str
            ) -> StoredArtifact:
                return StoredArtifact(
                    filename=Path(local_path).name,
                    storage_key=object_key,
                    backend="local",
                )

        def fake_convert_file(input_path, target_format, output_path=None, **options):
            output = Path(output_path or Path(input_path).with_suffix(".png"))
            output.write_bytes(b"png")
            captured.append(
                {
                    "output_name": output.name,
                    "target_format": target_format,
                    "options": options,
                }
            )
            return output

        monkeypatch.setattr(
            "backend.routes.download.download_registry.get_artifact",
            lambda download_id: summary_artifact,
        )
        monkeypatch.setattr("backend.routes.download.get_storage_backend", FakeStorage)
        monkeypatch.setattr(
            "backend.routes.download._find_precomputed_conversion",
            lambda **kwargs: None,
        )
        monkeypatch.setattr("backend.routes.download.convert_file", fake_convert_file)

        convert_artifact(
            ConvertRequest(
                download_id="summary",
                target_format="png",
                render_mode="desktop",
            )
        )

        assert captured[0]["output_name"] == "BV123_summary_desktop.png"
        assert captured[0]["options"]["width"] == 834
        assert captured[0]["options"]["height"] == 1112
        assert captured[0]["options"]["dpr"] == 2


def test_convert_artifact_uses_stock_status_options_for_summary_pdf(
    monkeypatch,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        summary_path = temp_root / "BV123_summary.md"
        summary_path.write_text("# summary\n", encoding="utf-8")
        table_path = temp_root / "BV123_summary_table.md"
        table_path.write_text("| code |\n| --- |\n| 600000.SH |\n", encoding="utf-8")

        summary_artifact = StoredArtifact(
            filename=summary_path.name,
            storage_key=str(summary_path),
            backend="local",
        )
        table_artifact = StoredArtifact(
            filename=table_path.name,
            storage_key=str(table_path),
            backend="local",
        )

        captured: list[dict[str, object]] = []

        class FakeStorage:
            @contextmanager
            def open_stream(self, storage_key: str) -> Iterator[object]:
                with open(storage_key, "rb") as handle:
                    yield handle

            def store_file(
                self, local_path: Path, *, object_key: str
            ) -> StoredArtifact:
                return StoredArtifact(
                    filename=Path(local_path).name,
                    storage_key=object_key,
                    backend="local",
                )

        def fake_convert_file(input_path, target_format, output_path=None, **options):
            output = Path(output_path or Path(input_path).with_suffix(".pdf"))
            output.write_bytes(b"pdf")
            captured.append(
                {
                    "name": Path(input_path).name,
                    "target_format": target_format,
                    "options": options,
                }
            )
            return output

        monkeypatch.setattr(
            "backend.routes.download.download_registry.get_artifact",
            lambda download_id: (
                summary_artifact if download_id == "summary" else table_artifact
            ),
        )
        monkeypatch.setattr("backend.routes.download.get_storage_backend", FakeStorage)
        monkeypatch.setattr(
            "backend.routes.download._find_precomputed_conversion",
            lambda **kwargs: None,
        )
        monkeypatch.setattr("backend.routes.download.convert_file", fake_convert_file)
        monkeypatch.setattr(
            "backend.routes.download._lookup_artifact_pubdate",
            lambda storage_key: "2026-02-05 21:00:00",
        )

        convert_artifact(ConvertRequest(download_id="summary", target_format="pdf"))
        convert_artifact(ConvertRequest(download_id="table", target_format="pdf"))

        assert captured[0]["name"] == "BV123_summary.md"
        assert captured[0]["options"]["enhance_stock_tables"] is True
        assert captured[0]["options"]["is_table"] is False

        assert captured[1]["name"] == "BV123_summary_table.md"
        assert captured[1]["options"]["is_table"] is True
        assert captured[1]["options"]["as_of_date"] == "2026-02-05 21:00:00"

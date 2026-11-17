import time
from pathlib import Path

from b2t.history import HistoryDB
from b2t.png_cache import TTL_SECONDS, PngCache
from b2t.storage import StoredArtifact
from b2t.storage.local import LocalStorageBackend


def test_cache_survives_until_storage_lifecycle_deletes_object(tmp_path):
    cache = PngCache(tmp_path / "db")
    storage = LocalStorageBackend(tmp_path / "output")
    png = tmp_path / "image.png"
    png.write_bytes(b"png")
    artifact = cache.store(
        storage, png, output_dir=tmp_path / "output", source_key="source.md"
    )
    png.unlink()
    assert Path(artifact.storage_key).is_file()
    assert "/cache/png/" in artifact.storage_key
    cache.register(artifact, source_key="source.md", created_at=100)
    assert (
        cache.find(storage, source_key="source.md", now=100 + TTL_SECONDS - 1)
        == artifact
    )
    assert (
        cache.find(storage, source_key="source.md", now=100 + TTL_SECONDS) == artifact
    )
    assert cache.expired(artifact.storage_key, now=100 + TTL_SECONDS)
    storage.delete_file(artifact.storage_key)
    assert cache.find(storage, source_key="source.md") is None
    with cache.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM png_cache").fetchone()[0] == 0


def test_modes_and_variants_do_not_reuse_each_other(tmp_path):
    cache = PngCache(tmp_path / "db")
    storage = LocalStorageBackend(tmp_path)
    png = tmp_path / "image.png"
    png.write_bytes(b"png")
    artifact = cache.store(
        storage,
        png,
        output_dir=tmp_path,
        source_key="source.md",
        render_mode="mobile",
        variant="summary_no_table",
    )
    assert (
        cache.find(
            storage,
            source_key="source.md",
            render_mode="mobile",
            variant="summary_no_table",
        )
        == artifact
    )
    assert (
        cache.find(
            storage,
            source_key="source.md",
            render_mode="desktop",
            variant="summary_no_table",
        )
        is None
    )
    assert cache.find(storage, source_key="source.md", render_mode="mobile") is None


def test_cleanup_updates_history_and_preserves_sources(tmp_path):
    db = HistoryDB(tmp_path / "db")
    cache = PngCache(tmp_path / "db")
    storage = LocalStorageBackend(tmp_path)
    source = tmp_path / "summary.md"
    source.write_text("source")
    png = tmp_path / "old.png"
    png.write_bytes(b"png")
    artifact = StoredArtifact(filename=png.name, storage_key=str(png), backend="local")
    cache.register(artifact, created_at=time.time() - TTL_SECONDS - 1)
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO transcription_runs(run_id,bvid,created_at,file_count) VALUES ('run','BV123','today',2)"
        )
        for kind, path in [("summary", source), ("summary_png", png)]:
            conn.execute(
                "INSERT INTO transcription_artifacts(run_id,kind,filename,storage_key,backend) VALUES ('run',?,?,?,'local')",
                (kind, path.name, str(path)),
            )
        conn.commit()
    assert cache.cleanup(storage) == {str(png)}
    assert source.read_text() == "source"
    with db._connect() as conn:
        assert (
            conn.execute("SELECT file_count FROM transcription_runs").fetchone()[0] == 1
        )
        assert (
            conn.execute("SELECT kind FROM transcription_artifacts").fetchone()[0]
            == "summary"
        )


def test_failed_delete_is_retried_and_missing_object_is_cache_miss(tmp_path):
    cache = PngCache(tmp_path)
    storage = LocalStorageBackend(tmp_path)
    artifact = StoredArtifact(
        filename="missing.png",
        storage_key=str(tmp_path / "missing.png"),
        backend="local",
    )
    cache.register(artifact, source_key="source.md", created_at=0)
    assert cache.find(storage, source_key="source.md", now=1) is None
    cache.register(artifact, source_key="source.md", created_at=0)
    storage.delete_file = lambda _: (_ for _ in ()).throw(RuntimeError("offline"))
    assert cache.cleanup(storage, now=TTL_SECONDS) == set()
    assert cache.expired(artifact.storage_key, now=TTL_SECONDS)

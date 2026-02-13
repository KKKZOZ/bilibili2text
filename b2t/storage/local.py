"""本地文件系统存储后端。"""

from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from b2t.storage.base import (
    StorageBackend,
    StoredArtifact,
    classify_artifact_filename,
)


class LocalStorageBackend(StorageBackend):
    backend_name = "local"
    persist_local_outputs = True

    def __init__(self, output_root: Path | str | None = None) -> None:
        if output_root is None:
            self._output_root: Path | None = None
        else:
            self._output_root = Path(output_root).expanduser().resolve()

    def supports_public_url(self) -> bool:
        return False

    def store_file(self, local_path: Path, *, object_key: str) -> StoredArtifact:
        path = Path(local_path).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"本地文件不存在: {path}")

        return StoredArtifact(
            filename=path.name,
            storage_key=str(path),
            backend=self.backend_name,
        )

    @contextmanager
    def open_stream(self, storage_key: str) -> Iterator[BinaryIO]:
        path = Path(storage_key)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"本地文件不存在: {path}")

        with path.open("rb") as stream:
            yield stream

    def delete_file(self, storage_key: str) -> None:
        """删除本地文件。"""
        path = Path(storage_key)
        if path.exists() and path.is_file():
            path.unlink()

    def find_existing_transcription(
        self,
        bvid: str,
    ) -> dict[str, StoredArtifact] | None:
        artifacts = self.list_existing_transcription_artifacts(bvid)
        if not artifacts:
            return None

        runs: dict[str, dict[str, StoredArtifact]] = {}
        run_order: list[str] = []
        for artifact in artifacts:
            parent_name = Path(artifact.storage_key).parent.name
            if not parent_name.lower().startswith(bvid.lower()):
                continue
            artifact_key = classify_artifact_filename(artifact.filename)
            if artifact_key is None:
                continue

            if parent_name not in runs:
                runs[parent_name] = {}
                run_order.append(parent_name)

            if artifact_key in runs[parent_name]:
                continue
            runs[parent_name][artifact_key] = artifact

        for run_name in run_order:
            grouped = runs[run_name]
            if "markdown" in grouped and "json" in grouped:
                return grouped
        for run_name in run_order:
            grouped = runs[run_name]
            if "markdown" in grouped:
                return grouped
        return None

    def list_existing_transcription_artifacts(
        self,
        bvid: str,
    ) -> list[StoredArtifact]:
        bvid = bvid.strip()
        if not bvid:
            return []

        if self._output_root is None or not self._output_root.exists():
            return []

        bvid_lower = bvid.lower()
        candidate_dirs = [
            path
            for path in self._output_root.iterdir()
            if path.is_dir() and path.name.lower().startswith(bvid_lower)
        ]
        if not candidate_dirs:
            return []

        def _dir_mtime(directory: Path) -> float:
            mtimes = [
                file_path.stat().st_mtime
                for file_path in directory.rglob("*")
                if file_path.is_file()
            ]
            if mtimes:
                return max(mtimes)
            return directory.stat().st_mtime

        candidate_dirs.sort(key=_dir_mtime, reverse=True)
        artifact_items: list[tuple[float, StoredArtifact]] = []
        for directory in candidate_dirs:
            for path in directory.rglob("*"):
                if not path.is_file():
                    continue
                if not path.name.lower().startswith(bvid_lower):
                    continue

                artifact_key = classify_artifact_filename(path.name)
                if artifact_key is None:
                    continue

                artifact_items.append(
                    (
                        path.stat().st_mtime,
                        StoredArtifact(
                            filename=path.name,
                            storage_key=str(path.resolve()),
                            backend=self.backend_name,
                        ),
                    )
                )

        artifact_items.sort(key=lambda item: item[0], reverse=True)
        artifacts: list[StoredArtifact] = []
        seen_keys: set[str] = set()
        for _, artifact in artifact_items:
            if artifact.storage_key in seen_keys:
                continue
            seen_keys.add(artifact.storage_key)
            artifacts.append(artifact)

        return artifacts

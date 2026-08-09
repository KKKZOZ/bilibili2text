"""STT Provider abstract definition"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

ProgressCallback = Callable[[str, str, int], None]


class STTProvider(ABC):
    """Unified speech transcription interface."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        work_dir: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        """Run transcription and return the path to the result file."""
        raise NotImplementedError

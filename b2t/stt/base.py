"""STT Provider 抽象定义"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[str, str, int], None]


class STTProvider(ABC):
    """统一的语音转录接口。"""

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        work_dir: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        """执行转录并返回转录结果文件路径。"""
        raise NotImplementedError

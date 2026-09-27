"""HTTP-only bridge to the independently running backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from b2t.config import BackendConfig

GenerationKind = Literal["summary", "report", "both"]


class BackendError(Exception):
    """A backend operation failed with a user-facing message."""


class SubmissionUnknown(BackendError):
    """The server may have accepted the request; do not automatically resubmit."""


@dataclass(frozen=True)
class JobProgress:
    label: str
    done: bool = False
    error: str = ""


def parse_progress(data: dict, kind: GenerationKind) -> JobProgress:
    status = data.get("status")
    if status in {"failed", "cancelled"}:
        return JobProgress(
            "任务失败" if status == "failed" else "已取消",
            done=True,
            error=data.get("error") or "",
        )
    if status == "succeeded":
        if kind == "summary":
            return JobProgress("总结完成", done=True)
        report_status = data.get("fancy_html_status")
        if report_status == "succeeded":
            return JobProgress(
                "总结和报告完成" if kind == "both" else "阅读报告完成", done=True
            )
        if report_status == "failed":
            return JobProgress(
                "阅读报告失败", done=True, error=data.get("fancy_html_error") or ""
            )
        return JobProgress("阅读报告生成中")
    return JobProgress(
        f"{data.get('stage_label') or '排队中'} {data.get('progress', 0)}%"
    )


class MonitorBackendClient:
    def __init__(self, config: BackendConfig, *, transport=None):
        host = config.host
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1" if host == "0.0.0.0" else "::1"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        self.base_url = f"http://{host}:{config.port}"
        self.client = httpx.AsyncClient(
            base_url=self.base_url, timeout=15, transport=transport
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def submit(self, bvid: str, kind: GenerationKind) -> str:
        # Omitting model/preset/profile delegates defaults to the backend.
        try:
            response = await self.client.post(
                "/api/process",
                json={
                    "url": f"https://www.bilibili.com/video/{bvid}",
                    "skip_summary": kind == "report",
                    "auto_generate_fancy_html": kind in {"report", "both"},
                },
            )
        except httpx.ConnectError as exc:
            raise BackendError(
                f"无法连接 {self.base_url}，请先运行 uv run b2t backend"
            ) from exc
        except httpx.RequestError as exc:
            raise SubmissionUnknown(
                "提交结果未知，请在 backend 网页检查任务；为避免重复生成，不自动重试"
            ) from exc
        if response.status_code >= 500:
            raise SubmissionUnknown("backend 服务异常，提交结果未知，请在网页检查任务")
        self._check_response(response)
        try:
            job_id = response.json()["job_id"]
            if not isinstance(job_id, str) or not job_id:
                raise ValueError("empty job id")
        except (ValueError, KeyError, TypeError) as exc:
            raise SubmissionUnknown(
                "backend 未返回有效任务编号，请在网页检查任务"
            ) from exc
        return job_id

    async def progress(self, job_id: str, kind: GenerationKind) -> JobProgress:
        try:
            response = await self.client.get(f"/api/process/{job_id}")
            self._check_response(response)
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("invalid status response")
        except (httpx.RequestError, ValueError, TypeError) as exc:
            raise BackendError(
                "任务状态查询失败，稍后重试（不会重新提交任务）"
            ) from exc
        return parse_progress(data, kind)

    @staticmethod
    def _check_response(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise BackendError(
            f"backend 返回 {response.status_code}：{detail or '请求失败'}"
        )

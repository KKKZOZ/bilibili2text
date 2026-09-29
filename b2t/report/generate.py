"""Prepare source evidence and publish a self-contained reading report."""

import asyncio
import hashlib
import html
import json
import re
import tempfile
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import parse_qsl, urlencode, urlunsplit

from b2t.cancellation import CancellationToken
from b2t.config import AppConfig, resolve_summarize_model_profile
from b2t.download.url_detect import parse_http_url
from b2t.report.options import ReportOptions
from b2t.report.pi import PI_VERSION, SKILL, run_pi

REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'"
_REPORT_SLOTS = BoundedSemaphore(2)


def clean_source_url(value: str) -> str:
    """Remove attribution parameters while preserving episode and playback targets."""
    value = value.strip()
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", value, flags=re.IGNORECASE):
        return f"https://www.bilibili.com/video/BV{value[2:]}/"
    parsed = parse_http_url(value)
    if parsed is None:
        return ""
    tracking = {
        "vd_source",
        "spm_id_from",
        "from_spmid",
        "spmid",
        "share_source",
        "share_medium",
        "share_plat",
        "share_session_id",
        "share_tag",
        "share_from",
        "share_times",
        "unique_k",
        "buvid",
    }
    query = urlencode(
        [
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in tracking and not key.lower().startswith("utm_")
        ]
    )
    return urlunsplit(parsed._replace(query=query))


def source_units(markdown: str, payload: dict | None = None) -> list[dict]:
    """Keep provider timing in milliseconds; never invent missing boundaries."""
    units = []
    if payload:
        rows = []
        for transcript in payload.get("transcripts", []):
            rows.extend(
                (s, "begin_time", "end_time", 1)
                for s in transcript.get("sentences", [])
            )
        if not rows:
            rows = [(s, "start", "end", 1000) for s in payload.get("segments", [])]
        if not rows and isinstance(payload.get("result"), dict):
            rows = [
                (s, "start_time", "end_time", 1)
                for s in payload["result"].get("utterances", [])
            ]
        for row, start_key, end_key, scale in rows:
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            start, end = row.get(start_key), row.get(end_key)
            timed = (
                isinstance(start, (int, float))
                and isinstance(end, (int, float))
                and 0 <= start <= end
            )
            units.append(
                {
                    "text": text,
                    "speaker": row.get("speaker_id"),
                    "start_ms": round(start * scale) if timed else None,
                    "end_ms": round(end * scale) if timed else None,
                }
            )
    if not units:
        units = [
            {"text": line, "start_ms": None, "end_ms": None}
            for line in markdown.splitlines()
            if line.strip()
        ]
    if not units:
        raise ValueError("转写正文为空，无法生成阅读报告")
    return [{"id": f"u{index:06d}", **unit} for index, unit in enumerate(units, 1)]


def validate_source_refs(value: str, ids: set[str]) -> None:
    """Validate explicit IDs and inclusive ranges against the actual transcript.

    Pi may compress long standard-mode bindings to u000001–u000010. Check
    every member, not just the endpoints; bound expansion by the input ID count.
    """
    normalized = re.sub(
        r"(u[0-9]{6})\s*([-–—])\s*(u[0-9]{6})", r"\1\2\3", value.strip()
    )
    if not normalized:
        raise ValueError("来源绑定为空")
    for ref in re.split(r"[\s,;，；]+", normalized):
        if ref in ids:
            continue
        span = re.fullmatch(r"u([0-9]{6})[-–—]u([0-9]{6})", ref)
        if span is None:
            raise ValueError(f"未知 ID 或格式不支持：{ref[:80]!r}")
        start, end = map(int, span.groups())
        if start > end:
            raise ValueError(f"来源区间倒序：{ref}")
        if end - start + 1 > len(ids):
            raise ValueError(f"来源区间超出转录单元数量：{ref}")
        for index in range(start, end + 1):
            unit_id = f"u{index:06d}"
            if unit_id not in ids:
                raise ValueError(f"来源区间 {ref} 包含不存在的 ID：{unit_id}")


class ReportValidator(HTMLParser):
    def __init__(self, ids: set[str]):
        super().__init__()
        self.ids = ids
        self.bindings = 0
        self.tags = set()

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        for key, value in attrs:
            if key == "data-source-units":
                try:
                    validate_source_refs(value or "", self.ids)
                except ValueError as exc:
                    line, _ = self.getpos()
                    raise ValueError(
                        f"报告包含无效来源 ID（第 {line} 行 <{tag}>：{exc}），请重新生成"
                    ) from None
                self.bindings += 1


def finish_html(raw: str, ids: set[str], settings: dict) -> str:
    parser = ReportValidator(ids)
    parser.feed(raw)
    if not {"html", "head", "body"}.issubset(parser.tags) or not parser.bindings:
        raise ValueError("报告缺少完整 HTML 结构或来源绑定，请重新生成")
    if re.search(r"\{\{[A-Z_]+\}\}", raw):
        raise ValueError("报告仍含未填充的模板占位符，请重新生成")
    metadata = html.escape(json.dumps(settings, ensure_ascii=False), quote=True)
    # First CSP wins by intersection with any later policies. It also applies to downloads.
    header = (
        f'<meta http-equiv="Content-Security-Policy" content="{html.escape(REPORT_CSP, quote=True)}">'
        f'<meta name="b2t-report-settings" content="{metadata}">'
    )
    return re.sub(
        r"(<head\b[^>]*>)", lambda m: m[0] + header, raw, count=1, flags=re.IGNORECASE
    )


def generate_report(
    source: Path,
    config: AppConfig,
    *,
    options: ReportOptions | None = None,
    metadata: dict | None = None,
    json_path: Path | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    if progress_callback:
        progress_callback("正在准备完整转录和报告素材")
    options = options or ReportOptions()
    profile_name = options.profile.strip() or config.fancy_html.profile
    profile = resolve_summarize_model_profile(config.summarize, override=profile_name)
    payload = json.loads(json_path.read_text(encoding="utf-8")) if json_path else None
    units = source_units(source.read_text(encoding="utf-8"), payload)
    with tempfile.TemporaryDirectory(prefix="b2t-report-") as temporary:
        workspace = Path(temporary)
        settings = {
            **options.model_dump(),
            "profile": profile_name,
            "provider": profile.provider,
            "model": profile.model,
            "pi_version": PI_VERSION,
            "skill_revision": hashlib.sha256(
                b"".join(
                    p.read_bytes() for p in sorted(SKILL.rglob("*")) if p.is_file()
                )
            ).hexdigest()[:16],
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
        input_data = {**(metadata or {}), "report_mode": options.mode}
        input_data["url"] = clean_source_url(str(input_data.get("url") or ""))
        (workspace / "input.json").write_text(
            json.dumps(input_data, ensure_ascii=False), encoding="utf-8"
        )
        lines = []
        for unit in units:
            timing = (
                f"{unit['start_ms'] / 1000:.3f}–{unit['end_ms'] / 1000:.3f}s"
                if unit["start_ms"] is not None
                else "时间范围未知"
            )
            speaker = (
                f"说话人 {unit['speaker']}: " if unit.get("speaker") is not None else ""
            )
            lines.append(f"[{unit['id']} | {timing}] {speaker}{unit['text']}")
        (workspace / "transcript.md").write_text("\n".join(lines), encoding="utf-8")
        if not _REPORT_SLOTS.acquire(blocking=False):
            raise RuntimeError("报告生成并发已满，请稍后重试")
        try:
            report = asyncio.run(
                run_pi(
                    workspace,
                    profile,
                    options,
                    cancellation_token,
                    docker_network=config.report.docker_network,
                    progress_callback=progress_callback,
                )
            )
        finally:
            _REPORT_SLOTS.release()
        raw = report.read_text(encoding="utf-8")
        if profile.api_key and profile.api_key in raw:
            raise ValueError("报告输出包含敏感凭证，已拒绝保存")
        result = finish_html(raw, {unit["id"] for unit in units}, settings)
        if cancellation_token:
            cancellation_token.raise_if_cancelled()
        output = source.with_name(f"{source.stem}_fancy.html")
        output.write_text(result, encoding="utf-8")
        return output

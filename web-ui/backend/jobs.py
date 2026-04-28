"""Compatibility helpers for job lifecycle operations."""

from backend.job_store import JobPatch, JobValue, job_repository


def _create_job(
    *,
    skip_summary: bool,
    summary_preset: str | None,
    summary_profile: str | None,
    auto_generate_fancy_html: bool,
) -> dict[str, JobValue]:
    return job_repository.create(
        skip_summary=skip_summary,
        summary_preset=summary_preset,
        summary_profile=summary_profile,
        auto_generate_fancy_html=auto_generate_fancy_html,
    )


def _update_job(job_id: str, **kwargs) -> None:
    job_repository.patch(job_id, JobPatch(**kwargs))


def _append_job_log(job_id: str, line: str) -> None:
    job_repository.append_log(job_id, line)


def _list_active_jobs() -> list[dict[str, JobValue]]:
    return job_repository.list_active()


def _get_job(job_id: str) -> dict[str, JobValue] | None:
    return job_repository.get(job_id)

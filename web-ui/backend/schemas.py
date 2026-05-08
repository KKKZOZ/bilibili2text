"""Pydantic request / response models for the bilibili-to-text API."""

from typing import Literal

from pydantic import BaseModel, Field


class ProcessRequest(BaseModel):
    url: str = Field(..., min_length=1, description="Bilibili 视频 URL")
    skip_summary: bool = Field(
        default=False,
        description="是否跳过总结步骤",
    )
    summary_preset: str | None = Field(
        default=None,
        description="总结 preset 名称",
    )
    summary_profile: str | None = Field(
        default=None,
        description="总结模型 profile 名称",
    )
    summary_prompt_template: str | None = Field(
        default=None,
        description="本次请求使用的自定义总结模板，必须包含 {content} 占位符",
    )
    auto_generate_fancy_html: bool = Field(
        default=False,
        description="总结完成后是否自动异步生成 fancy HTML",
    )
    api_key: str | None = Field(
        default=None,
        description="open-public 模式下用户自带的阿里云 DashScope API Key",
    )
    deepseek_api_key: str | None = Field(
        default=None,
        description="open-public 模式下用户自带的 DeepSeek API Key（可选，用于 LLM/RAG/Fancy HTML）",
    )


class ProcessStartResponse(BaseModel):
    job_id: str


class DownloadItemResponse(BaseModel):
    url: str
    filename: str
    kind: str


class ActiveJobItem(BaseModel):
    job_id: str
    status: str
    stage: str
    stage_label: str
    progress: int = Field(ge=0, le=100)
    bvid: str | None = None
    title: str | None = None
    author: str | None = None
    created_at: str
    updated_at: str


class ActiveJobsResponse(BaseModel):
    jobs: list[ActiveJobItem]


class ProcessStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    skip_summary: bool = False
    stage: str
    stage_label: str
    progress: int = Field(ge=0, le=100)
    download_url: str
    filename: str | None = None
    txt_download_url: str | None = None
    txt_filename: str | None = None
    summary_download_url: str | None = None
    summary_filename: str | None = None
    summary_txt_download_url: str | None = None
    summary_txt_filename: str | None = None
    summary_table_pdf_download_url: str | None = None
    summary_table_pdf_filename: str | None = None
    summary_preset: str | None = None
    summary_profile: str | None = None
    summary_prompt_template: str | None = None
    auto_generate_fancy_html: bool = False
    fancy_html_status: Literal["idle", "pending", "running", "succeeded", "failed"] = (
        "idle"
    )
    fancy_html_error: str | None = None
    already_transcribed: bool = False
    notice: str | None = None
    all_downloads: list[DownloadItemResponse] = Field(default_factory=list)
    error: str | None = None
    logs: list[str] = Field(default_factory=list)
    stage_durations: dict[str, str] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    author: str | None = None
    pubdate: str | None = None
    bvid: str | None = None
    title: str | None = None


class SummaryPresetItemResponse(BaseModel):
    name: str
    label: str
    prompt_template: str


class SummaryPresetListResponse(BaseModel):
    default_preset: str
    selected_preset: str
    presets: list[SummaryPresetItemResponse]


class SummaryProfileItemResponse(BaseModel):
    name: str
    provider: str
    model: str
    api_base: str


class SummaryProfileListResponse(BaseModel):
    default_profile: str
    selected_profile: str
    profiles: list[SummaryProfileItemResponse]


class RuntimeFeaturesResponse(BaseModel):
    mode: Literal["default", "open-public"]
    allow_upload_audio: bool
    allow_delete: bool
    requires_user_api_key: bool
    api_key_configured: bool
    deepseek_api_key_configured: bool = False
    counterscale_site_id: str = ""
    counterscale_tracker_url: str = ""


class OpenPublicApiKeyStatusResponse(BaseModel):
    provider: Literal["alibaba", "deepseek"] = "alibaba"
    configured: bool
    masked_key: str | None = None


class OpenPublicApiKeyUpdateRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="API Key")
    provider: Literal["alibaba", "deepseek"] = Field(
        default="alibaba",
        description="API Key 对应的服务商",
    )


class HistoryItemResponse(BaseModel):
    run_id: str
    bvid: str
    title: str
    author: str
    pubdate: str
    created_at: str
    has_summary: bool
    file_count: int
    record_type: str = "transcription"


class HistoryListResponse(BaseModel):
    items: list[HistoryItemResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class HistoryDetailArtifactResponse(BaseModel):
    kind: str
    filename: str
    download_url: str
    summary_preset: str = ""
    summary_profile: str = ""


class HistoryDetailResponse(BaseModel):
    run_id: str
    bvid: str
    title: str
    author: str
    pubdate: str
    created_at: str
    has_summary: bool
    artifacts: list[HistoryDetailArtifactResponse]
    record_type: str = "transcription"
    fancy_html_status: Literal["idle", "pending", "running", "succeeded", "failed"] = (
        "idle"
    )
    fancy_html_error: str | None = None


class HistoryRegenerateSummaryRequest(BaseModel):
    summary_preset: str | None = Field(
        default=None,
        description="总结 preset 名称，为空时使用后端默认",
    )
    summary_profile: str | None = Field(
        default=None,
        description="总结模型 profile 名称，为空时使用后端默认",
    )
    summary_prompt_template: str | None = Field(
        default=None,
        description="本次重生成使用的自定义总结模板，必须包含 {content} 占位符",
    )
    api_key: str | None = Field(
        default=None,
        description="open-public 模式下用户自带的阿里云 DashScope API Key",
    )
    deepseek_api_key: str | None = Field(
        default=None,
        description="open-public 模式下用户自带的 DeepSeek API Key（可选，用于 LLM/Fancy HTML）",
    )


class GenerateFancyHtmlRequest(BaseModel):
    download_id: str = Field(..., description="总结 Markdown 的下载 ID")
    history_run_id: str | None = Field(
        default=None,
        description="可选，历史记录 run_id，用于生成后刷新历史详情",
    )
    summary_preset: str | None = Field(
        default=None,
        description="源总结的 preset 元数据，用于落库归档",
    )
    summary_profile: str | None = Field(
        default=None,
        description="生成 fancy HTML 使用的 profile；为空时使用后端默认",
    )
    api_key: str | None = Field(
        default=None,
        description="open-public 模式下用户自带的阿里云 DashScope API Key",
    )
    deepseek_api_key: str | None = Field(
        default=None,
        description="open-public 模式下用户自带的 DeepSeek API Key（可选，用于 Fancy HTML）",
    )


class GenerateFancyHtmlResponse(BaseModel):
    download_url: str | None = None
    filename: str | None = None
    history_detail: HistoryDetailResponse | None = None


class ConvertRequest(BaseModel):
    download_id: str = Field(
        ..., description="下载 ID（来自 all_downloads 或 history 详情）"
    )
    target_format: str = Field(..., description="目标格式：txt, pdf, png, html")
    render_mode: Literal["desktop", "mobile"] | None = Field(
        default=None,
        description="可选渲染模式，仅用于 HTML -> PNG",
    )
    source_variant: Literal["summary_no_table"] | None = Field(
        default=None,
        description="可选源文件变体，用于命中预生成的派生文件缓存",
    )


class ConvertResponse(BaseModel):
    download_url: str
    filename: str

"""Pydantic request / response models for the bilibili-to-text API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from b2t.summarize.llm import validate_summary_prompt_template


class RuntimeCredentialsRequest(BaseModel):
    api_key: str | None = None
    deepseek_api_key: str | None = None
    custom_llm_base_url: str | None = None
    custom_llm_api_key: str | None = None
    custom_llm_model: str | None = None

    @field_validator(
        "api_key",
        "deepseek_api_key",
        "custom_llm_base_url",
        "custom_llm_api_key",
        "custom_llm_model",
        mode="before",
    )
    @classmethod
    def _clean_credentials(cls, value: object) -> str | None:
        cleaned = value.strip() if isinstance(value, str) else ""
        return cleaned or None

    def runtime_config_kwargs(self) -> dict[str, str | None]:
        return {
            "api_key": self.api_key,
            "deepseek_api_key": self.deepseek_api_key,
            "custom_llm_base_url": self.custom_llm_base_url,
            "custom_llm_api_key": self.custom_llm_api_key,
            "custom_llm_model": self.custom_llm_model,
        }


class SummarySelectionRequest(RuntimeCredentialsRequest):
    summary_preset: str | None = None
    summary_profile: str | None = None
    summary_prompt_template: str | None = None

    @field_validator("summary_preset", "summary_profile", mode="before")
    @classmethod
    def _clean_selection(cls, value: object) -> str | None:
        cleaned = value.strip() if isinstance(value, str) else ""
        return cleaned or None

    @field_validator("summary_prompt_template", mode="before")
    @classmethod
    def _clean_prompt_template(cls, value: object) -> str | None:
        cleaned = value.strip() if isinstance(value, str) else ""
        return validate_summary_prompt_template(cleaned) if cleaned else None


class ProcessRequest(SummarySelectionRequest):
    url: str = Field(
        ...,
        min_length=1,
        description="视频或播客 URL（支持 Bilibili、小宇宙、喜马拉雅）",
    )
    skip_summary: bool = Field(
        default=False,
        description="是否跳过总结步骤",
    )
    auto_generate_fancy_html: bool = Field(
        default=False,
        description="总结完成后是否自动异步生成 fancy HTML",
    )
    prefer_bilibili_subtitle: bool = Field(
        default=True,
        description="是否优先使用 B 站原生字幕，失败后回退到音频 ASR",
    )
    include_comments: bool = Field(
        default=True,
        description="是否下载并总结支持平台的热门评论",
    )
    comment_limit: int | None = Field(
        default=200,
        ge=1,
        le=1000,
        description="下载的主评论数量；每条主评论的子评论全部下载；为空表示下载全部主评论",
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
    used_bilibili_subtitle: bool = False
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
    history_run_id: str | None = None
    is_ephemeral_upload: bool = False
    expires_at: str | None = None


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


class OpenPublicApiKeyTestRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="API Key")
    provider: Literal["alibaba", "deepseek"] = Field(
        default="alibaba",
        description="API Key 对应的服务商",
    )


class OpenPublicApiKeyTestResponse(BaseModel):
    ok: bool
    content: str = ""


class OpenPublicCustomLlmTestRequest(BaseModel):
    base_url: str = Field(..., min_length=1, description="OpenAI-compatible base_url")
    api_key: str = Field(..., min_length=1, description="API Key")
    model: str = Field(..., min_length=1, description="模型名称")


class OpenPublicCustomLlmTestResponse(BaseModel):
    ok: bool
    content: str = ""


class HistoryItemResponse(BaseModel):
    run_id: str
    bvid: str
    page: int | None = None
    title: str
    author: str
    pubdate: str
    created_at: str
    has_summary: bool
    file_count: int
    tid: int = 0
    tname: str = ""
    parent_tname: str = ""
    record_type: str = "transcription"


class HistoryListResponse(BaseModel):
    items: list[HistoryItemResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class HistoryCategoryFilterOptionResponse(BaseModel):
    tid: int
    tname: str
    parent_tid: int = 0
    parent_tname: str = ""
    count: int
    is_parent: bool = False


class HistoryAuthorFilterOptionResponse(BaseModel):
    author: str
    count: int


class HistoryPlatformFilterOptionResponse(BaseModel):
    platform: str
    name: str
    count: int


class HistoryFilterOptionsResponse(BaseModel):
    platforms: list[HistoryPlatformFilterOptionResponse]
    categories: list[HistoryCategoryFilterOptionResponse]
    authors: list[HistoryAuthorFilterOptionResponse]


class HistoryDetailArtifactResponse(BaseModel):
    kind: str
    filename: str
    download_url: str
    summary_preset: str = ""
    summary_profile: str = ""
    derived_from: str = ""


class HistoryDetailResponse(BaseModel):
    run_id: str
    bvid: str
    page: int | None = None
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


class HistoryRegenerateSummaryRequest(SummarySelectionRequest):
    overwrite_existing: bool = Field(
        default=False,
        description="确认覆盖相同模型配置与总结模板生成的已有结果",
    )


class GenerateFancyHtmlRequest(RuntimeCredentialsRequest):
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
        description="可选 PNG 渲染模式",
    )
    source_variant: Literal["summary_no_table"] | None = Field(
        default=None,
        description="可选源文件变体，用于命中预生成的派生文件缓存",
    )


class ConvertResponse(BaseModel):
    download_url: str
    filename: str

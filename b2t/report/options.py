"""Public, non-secret report settings saved with each task."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["standard", "brief"] = "standard"
    profile: str = Field(default="", max_length=200)

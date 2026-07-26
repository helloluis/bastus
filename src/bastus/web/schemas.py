"""Request/response models for the API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    label: str = ""
    enabled_categories: list[str] = Field(min_length=1)
    num_tests: int = Field(default=2, ge=1, le=50)  # tests per enabled category
    beam_width: int = Field(default=3, ge=1, le=32)
    branching_factor: int = Field(default=2, ge=1, le=8)
    max_turns: int = Field(default=5, ge=1, le=20)
    break_threshold: float = Field(default=60.0, ge=0, le=100)
    multimodal: bool = False
    mock: bool = True

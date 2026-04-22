"""Pydantic 模型：API 请求/响应。"""

from pydantic import BaseModel, Field


class ModeItem(BaseModel):
    id: str
    name: str
    description: str
    uses_llm: bool = Field(alias="usesLLM")
    model_config = {"populate_by_name": True}


class SetCurrentModeRequest(BaseModel):
    mode: str


class DeviceItem(BaseModel):
    id: str
    name: str
    is_default: bool = False


class ProcessRequest(BaseModel):
    text: str
    mode: str | None = None
    target_language: str | None = None


class ProcessResponse(BaseModel):
    success: bool
    processed_text: str = ""
    mode: str = ""
    used_llm: bool = False
    duration_ms: int = 0
    fell_back_to_transcribe: bool = False
    error: str | None = None


class VoiceprintProfile(BaseModel):
    id: str
    name: str
    created_at: str
    enrollment_steps: int = 0
    enrollment_complete: bool = False


class CreateProfileRequest(BaseModel):
    name: str


class EnrollStepRequest(BaseModel):
    step: int
    audio_base64: str


class EnrollStepResponse(BaseModel):
    success: bool
    step: int
    total: int = 5
    quality_score: float = 0.0
    message: str = ""


class SetActiveProfilesRequest(BaseModel):
    profile_ids: list[str]


class WakeupSettings(BaseModel):
    method: str = "hotkey"
    hotkey_combo: str = "f2"
    vad_keyword: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"

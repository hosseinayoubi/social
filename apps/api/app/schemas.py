from pydantic import BaseModel, EmailStr
from typing import Literal, Optional, List
from datetime import datetime

Platform = Literal["instagram", "facebook"]

class LoginReq(BaseModel):
    email: EmailStr
    password: str

class LoginRes(BaseModel):
    token: str

class MeRes(BaseModel):
    id: int
    email: EmailStr
    workspace_id: int
    workspace_name: str

class ConfigRes(BaseModel):
    approval_required: bool
    interval_days: int
    max_candidates: int
    pick_top_n: int

class ConfigUpdate(BaseModel):
    approval_required: bool
    interval_days: int
    max_candidates: int
    pick_top_n: int

class SourcePageIn(BaseModel):
    platform: Platform
    handle: str
    enabled: bool = True

class SourcePageOut(SourcePageIn):
    id: int
    created_at: datetime

class CandidateOut(BaseModel):
    id: int
    platform: Platform
    original_url: str
    caption_raw: Optional[str] = None
    media_type: str
    media_url: Optional[str] = None
    posted_at_source: Optional[datetime] = None
    engagement_score: int
    status: str
    created_at: datetime

class GeneratedOut(BaseModel):
    title_en: str
    caption_en: str
    hashtags_en: List[str]

class CandidateWithGenerated(CandidateOut):
    generated: Optional[GeneratedOut] = None

class StatsRes(BaseModel):
    total_candidates: int
    total_published: int
    pending_approval: int
    last_run_at: Optional[datetime] = None

class LogEventOut(BaseModel):
    id: int
    level: str
    message: str
    job_id: Optional[int]
    created_at: datetime

class RunReq(BaseModel):
    # If omitted, uses workspace config approval_required
    auto_publish: Optional[bool] = None

class RunRes(BaseModel):
    enqueued_job_id: int

class ApproveRes(BaseModel):
    ok: bool

class TickRes(BaseModel):
    processed_jobs: int

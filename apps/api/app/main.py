from fastapi import FastAPI, Depends, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
from .settings import settings
from .db import engine, Base, get_db
from . import models
from .schemas import (
    LoginReq, LoginRes, MeRes, ConfigRes, ConfigUpdate,
    SourcePageIn, SourcePageOut, CandidateWithGenerated, StatsRes,
    LogEventOut, RunReq, RunRes, ApproveRes, TickRes
)
from .auth import get_current_user, create_token, verify_password, hash_password
from .jobs import enqueue_job, process_one_job, add_log
from .logging_rt import ws_manager

app = FastAPI(title="Social SaaS API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    # Ensure default admin + workspace + config exist
    db = next(get_db())
    try:
        user = db.query(models.User).first()
        if not user:
            user = models.User(
                email="admin@example.com",
                password_hash=hash_password("admin1234"),
                is_admin=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            ws = models.Workspace(name="Default Workspace", owner_id=user.id)
            db.add(ws)
            db.commit()
            db.refresh(ws)
            cfg = models.Config(workspace_id=ws.id, approval_required=True, interval_days=2, max_candidates=25, pick_top_n=5)
            db.add(cfg)
            db.commit()
    finally:
        db.close()

@app.post("/auth/login", response_model=LoginRes)
def login(body: LoginReq, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user.id)
    return LoginRes(token=token)

@app.get("/me", response_model=MeRes)
def me(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = db.query(models.Workspace).filter(models.Workspace.owner_id == user.id).first()
    if not ws:
        raise HTTPException(400, "Workspace missing")
    return MeRes(id=user.id, email=user.email, workspace_id=ws.id, workspace_name=ws.name)

def _workspace(db: Session, user: models.User) -> models.Workspace:
    ws = db.query(models.Workspace).filter(models.Workspace.owner_id == user.id).first()
    if not ws:
        raise HTTPException(400, "Workspace missing")
    return ws

@app.get("/api/config", response_model=ConfigRes)
def get_config(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    cfg = db.query(models.Config).filter(models.Config.workspace_id == ws.id).first()
    if not cfg:
        raise HTTPException(400, "Config missing")
    return ConfigRes(
        approval_required=cfg.approval_required,
        interval_days=cfg.interval_days,
        max_candidates=cfg.max_candidates,
        pick_top_n=cfg.pick_top_n,
    )

@app.post("/api/config", response_model=ConfigRes)
def update_config(body: ConfigUpdate, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    cfg = db.query(models.Config).filter(models.Config.workspace_id == ws.id).first()
    if not cfg:
        cfg = models.Config(workspace_id=ws.id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    cfg.approval_required = body.approval_required
    cfg.interval_days = body.interval_days
    cfg.max_candidates = body.max_candidates
    cfg.pick_top_n = body.pick_top_n
    cfg.updated_at = datetime.utcnow()
    db.commit()
    return ConfigRes(
        approval_required=cfg.approval_required,
        interval_days=cfg.interval_days,
        max_candidates=cfg.max_candidates,
        pick_top_n=cfg.pick_top_n,
    )

@app.get("/api/sources", response_model=list[SourcePageOut])
def list_sources(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    rows = db.query(models.SourcePage).filter(models.SourcePage.workspace_id == ws.id).order_by(models.SourcePage.id.desc()).all()
    return [SourcePageOut(id=r.id, platform=r.platform.value, handle=r.handle, enabled=r.enabled, created_at=r.created_at) for r in rows]

@app.post("/api/sources", response_model=SourcePageOut)
def add_source(body: SourcePageIn, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    r = models.SourcePage(workspace_id=ws.id, platform=models.Platform(body.platform), handle=body.handle, enabled=body.enabled)
    db.add(r)
    db.commit()
    db.refresh(r)
    add_log(db, ws.id, "success", f"Source added: {body.platform}::{body.handle}")
    return SourcePageOut(id=r.id, platform=r.platform.value, handle=r.handle, enabled=r.enabled, created_at=r.created_at)

@app.patch("/api/sources/{source_id}", response_model=SourcePageOut)
def toggle_source(source_id: int, body: SourcePageIn, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    r = db.query(models.SourcePage).filter(models.SourcePage.id == source_id, models.SourcePage.workspace_id == ws.id).first()
    if not r:
        raise HTTPException(404, "Source not found")
    r.platform = models.Platform(body.platform)
    r.handle = body.handle
    r.enabled = body.enabled
    db.commit()
    return SourcePageOut(id=r.id, platform=r.platform.value, handle=r.handle, enabled=r.enabled, created_at=r.created_at)

@app.get("/api/posts", response_model=list[CandidateWithGenerated])
def list_posts(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    rows = db.query(models.PostCandidate).filter(models.PostCandidate.workspace_id == ws.id).order_by(models.PostCandidate.id.desc()).limit(200).all()
    out = []
    for r in rows:
        gen = db.query(models.GeneratedContent).filter(models.GeneratedContent.candidate_id == r.id).first()
        out.append(CandidateWithGenerated(
            id=r.id, platform=r.platform.value, original_url=r.original_url, caption_raw=r.caption_raw,
            media_type=r.media_type, media_url=r.media_url, posted_at_source=r.posted_at_source,
            engagement_score=r.engagement_score, status=r.status.value, created_at=r.created_at,
            generated=(None if not gen else {"title_en": gen.title_en, "caption_en": gen.caption_en, "hashtags_en": gen.hashtags_en})
        ))
    return out

@app.post("/api/posts/{candidate_id}/approve", response_model=ApproveRes)
def approve(candidate_id: int, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    c = db.query(models.PostCandidate).filter(models.PostCandidate.id == candidate_id, models.PostCandidate.workspace_id == ws.id).first()
    if not c:
        raise HTTPException(404, "Candidate not found")
    if c.status != models.PostStatus.awaiting_approval:
        return ApproveRes(ok=True)
    c.status = models.PostStatus.approved
    c.updated_at = datetime.utcnow()
    db.commit()
    enqueue_job(db, ws.id, models.JobType.publish_one, {"candidate_id": c.id})
    return ApproveRes(ok=True)

@app.post("/api/run", response_model=RunRes)
def run_now(body: RunReq, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    job = enqueue_job(db, ws.id, models.JobType.run_pipeline, {"auto_publish": body.auto_publish, "model": settings.OPENAI_MODEL})
    return RunRes(enqueued_job_id=job.id)

@app.get("/api/stats", response_model=StatsRes)
def stats(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    total_candidates = db.query(models.PostCandidate).filter(models.PostCandidate.workspace_id == ws.id).count()
    total_published = db.query(models.PostCandidate).filter(models.PostCandidate.workspace_id == ws.id, models.PostCandidate.is_posted == True).count()
    pending_approval = db.query(models.PostCandidate).filter(models.PostCandidate.workspace_id == ws.id, models.PostCandidate.status == models.PostStatus.awaiting_approval).count()
    last_job = db.query(models.PublishJob).filter(models.PublishJob.workspace_id == ws.id, models.PublishJob.job_type == models.JobType.run_pipeline).order_by(models.PublishJob.id.desc()).first()
    return StatsRes(
        total_candidates=total_candidates,
        total_published=total_published,
        pending_approval=pending_approval,
        last_run_at=(last_job.updated_at if last_job else None),
    )

@app.get("/api/logs", response_model=list[LogEventOut])
def logs(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    rows = db.query(models.LogEvent).filter(models.LogEvent.workspace_id == ws.id).order_by(models.LogEvent.id.desc()).limit(400).all()
    return [LogEventOut(id=r.id, level=r.level, message=r.message, job_id=r.job_id, created_at=r.created_at) for r in rows]

@app.post("/api/logs/clear")
def clear_logs(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(db, user)
    db.query(models.LogEvent).filter(models.LogEvent.workspace_id == ws.id).delete()
    db.commit()
    return {"ok": True}

@app.post("/api/cron/tick", response_model=TickRes)
async def cron_tick(db: Session = Depends(get_db), authorization: str | None = None):
    # Simple bearer token check via header "Authorization: Bearer <token>"
    # If your scheduler can't set headers, you can also pass as query param in your own deployment.
    # Here we keep it strict.
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    token = authorization.replace("Bearer ", "").strip()
    if token != settings.CRON_TICK_TOKEN:
        raise HTTPException(403, "Forbidden")

    # Process a small number of jobs per tick to avoid long-running requests.
    processed = 0
    # For simplicity in MVP, process jobs for all workspaces
    wids = [w[0] for w in db.query(models.Workspace.id).all()]
    for wid in wids:
        for _ in range(5):
            did = await process_one_job(db, wid)
            if not did:
                break
            processed += 1
    return TickRes(processed_jobs=processed)

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            # keep-alive / allow client pings
            await ws.receive_text()
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(ws)

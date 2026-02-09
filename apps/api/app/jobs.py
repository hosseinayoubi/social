from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from . import models
from .openai_client import generate_english_content
from .social_connectors import collect_instagram, collect_facebook, download_to_temp, publish_instagram, publish_facebook

def add_log(db: Session, workspace_id: int, level: str, message: str, job_id: int | None = None):
    db.add(models.LogEvent(workspace_id=workspace_id, level=level, message=message, job_id=job_id))
    db.commit()

def enqueue_job(db: Session, workspace_id: int, job_type: models.JobType, payload: dict) -> models.PublishJob:
    job = models.PublishJob(
        workspace_id=workspace_id,
        job_type=job_type,
        status=models.JobStatus.queued,
        payload=payload,
        scheduled_for=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    add_log(db, workspace_id, "info", f"Job enqueued: {job_type} (job_id={job.id})", job.id)
    return job

def _claim_next_job(db: Session, workspace_id: int) -> models.PublishJob | None:
    # Postgres "SKIP LOCKED" claim
    # Works on Postgres. If you're on SQLite, this won't work.
    q = text("""
        SELECT id FROM publish_jobs
        WHERE workspace_id = :wid
          AND status = 'queued'
          AND scheduled_for <= now()
        ORDER BY id ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    """)
    row = db.execute(q, {"wid": workspace_id}).first()
    if not row:
        return None
    job_id = int(row[0])
    job = db.query(models.PublishJob).filter(models.PublishJob.id == job_id).first()
    if not job:
        return None
    job.status = models.JobStatus.running
    job.attempts += 1
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job

async def process_one_job(db: Session, workspace_id: int) -> bool:
    job = _claim_next_job(db, workspace_id)
    if not job:
        return False

    try:
        if job.job_type == models.JobType.run_pipeline:
            await _run_pipeline(db, workspace_id, job.id, job.payload)
        elif job.job_type == models.JobType.publish_one:
            await _publish_one(db, workspace_id, job.id, job.payload)
        job.status = models.JobStatus.done
        job.updated_at = datetime.utcnow()
        db.commit()
        add_log(db, workspace_id, "success", f"Job done: {job.job_type} (job_id={job.id})", job.id)
    except Exception as e:
        job.status = models.JobStatus.failed
        job.last_error = str(e)
        job.updated_at = datetime.utcnow()
        db.commit()
        add_log(db, workspace_id, "error", f"Job failed: {job.job_type} (job_id={job.id}) :: {e}", job.id)

    return True

async def _run_pipeline(db: Session, workspace_id: int, job_id: int, payload: dict):
    # payload may override auto_publish
    cfg = db.query(models.Config).filter(models.Config.workspace_id == workspace_id).first()
    if not cfg:
        raise RuntimeError("Missing config")
    auto_publish_override = payload.get("auto_publish")
    approval_required = cfg.approval_required if auto_publish_override is None else (not bool(auto_publish_override))

    add_log(db, workspace_id, "info", f"Pipeline start (approval_required={approval_required})", job_id)

    # Collect
    sources = db.query(models.SourcePage).filter(models.SourcePage.workspace_id == workspace_id, models.SourcePage.enabled == True).all()
    add_log(db, workspace_id, "info", f"Collecting from {len(sources)} sources...", job_id)

    collected = []
    for s in sources:
        if s.platform == models.Platform.instagram:
            collected.extend(await collect_instagram(s.handle, limit=cfg.max_candidates))
        else:
            collected.extend(await collect_facebook(s.handle, limit=cfg.max_candidates))

    add_log(db, workspace_id, "info", f"Collected {len(collected)} posts.", job_id)

    # Upsert candidates (dedupe by unique constraint)
    inserted = 0
    for p in collected:
        exists = db.query(models.PostCandidate).filter(
            models.PostCandidate.workspace_id == workspace_id,
            models.PostCandidate.platform == models.Platform(p.platform),
            models.PostCandidate.original_url == p.original_url
        ).first()
        if exists:
            continue
        c = models.PostCandidate(
            workspace_id=workspace_id,
            platform=models.Platform(p.platform),
            original_url=p.original_url,
            original_id=p.original_id,
            caption_raw=p.caption,
            media_type=p.media_type,
            media_url=p.media_url,
            posted_at_source=p.posted_at,
            engagement_score=p.engagement,
            status=models.PostStatus.new,
        )
        db.add(c)
        inserted += 1
    db.commit()
    add_log(db, workspace_id, "success", f"Inserted {inserted} new candidates.", job_id)

    # Select top N
    candidates = db.query(models.PostCandidate).filter(
        models.PostCandidate.workspace_id == workspace_id,
        models.PostCandidate.status.in_([models.PostStatus.new, models.PostStatus.selected, models.PostStatus.failed]),
        models.PostCandidate.is_posted == False
    ).order_by(models.PostCandidate.engagement_score.desc()).limit(cfg.pick_top_n).all()

    for c in candidates:
        c.status = models.PostStatus.selected
        c.updated_at = datetime.utcnow()
    db.commit()
    add_log(db, workspace_id, "info", f"Selected top {len(candidates)} candidates.", job_id)

    # Generate
    for c in candidates:
        add_log(db, workspace_id, "info", f"Generating content for candidate {c.id}...", job_id)
        gen = await generate_english_content(c.caption_raw, c.media_type)
        existing = db.query(models.GeneratedContent).filter(models.GeneratedContent.candidate_id == c.id).first()
        if existing:
            existing.title_en = gen["title"]
            existing.caption_en = gen["caption"]
            existing.hashtags_en = gen["hashtags"]
            existing.model = payload.get("model") or "gpt-5-mini"
        else:
            db.add(models.GeneratedContent(
                candidate_id=c.id,
                title_en=gen["title"],
                caption_en=gen["caption"],
                hashtags_en=gen["hashtags"],
                model=payload.get("model") or "gpt-5-mini",
            ))
        c.status = models.PostStatus.awaiting_approval if approval_required else models.PostStatus.approved
        c.updated_at = datetime.utcnow()
        db.commit()

    add_log(db, workspace_id, "success", "Generation done.", job_id)

    if approval_required:
        add_log(db, workspace_id, "info", "Waiting for manual approvals.", job_id)
        return

    # Enqueue publish jobs for approved candidates
    approved = db.query(models.PostCandidate).filter(
        models.PostCandidate.workspace_id == workspace_id,
        models.PostCandidate.status == models.PostStatus.approved,
        models.PostCandidate.is_posted == False
    ).order_by(models.PostCandidate.engagement_score.desc()).all()

    for c in approved:
        enqueue_job(db, workspace_id, models.JobType.publish_one, {"candidate_id": c.id})

async def _publish_one(db: Session, workspace_id: int, job_id: int, payload: dict):
    cid = int(payload["candidate_id"])
    c = db.query(models.PostCandidate).filter(models.PostCandidate.id == cid, models.PostCandidate.workspace_id == workspace_id).first()
    if not c:
        raise RuntimeError("Candidate not found")
    gen = db.query(models.GeneratedContent).filter(models.GeneratedContent.candidate_id == cid).first()
    if not gen:
        raise RuntimeError("Missing generated content")

    caption = f"{gen.caption_en}\n\n" + " ".join(gen.hashtags_en)

    if not c.media_url:
        raise RuntimeError("Missing media_url (collector didn't provide media)")
    add_log(db, workspace_id, "info", f"Downloading media for candidate {cid}...", job_id)
    suffix = ".mp4" if c.media_type == "video" else ".jpg"
    media_path = await download_to_temp(c.media_url, suffix=suffix)

    # Publish to enabled platforms: for MVP publish to the same platform by default.
    # You can expand this to publish to multiple destination accounts.
    add_log(db, workspace_id, "info", f"Publishing candidate {cid} to {c.platform}...", job_id)
    if c.platform == models.Platform.instagram:
        res = await publish_instagram(media_path, c.media_type, caption)
    else:
        res = await publish_facebook(media_path, c.media_type, caption)

    pr = models.PublishResult(job_id=job_id, platform=c.platform, success=True,
                             remote_post_id=res.get("remote_post_id"), remote_url=res.get("remote_url"))
    db.add(pr)
    c.is_posted = True
    c.status = models.PostStatus.published
    c.updated_at = datetime.utcnow()
    db.commit()
    add_log(db, workspace_id, "success", f"Published candidate {cid}.", job_id)

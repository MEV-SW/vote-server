import logging
import re

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Candidate

logger = logging.getLogger(__name__)

_FIGMA_RE = re.compile(r"figma\.com/(?:proto|design|file|board|slides)/", re.I)


def is_figma_url(url: str | None) -> bool:
    return bool(url and _FIGMA_RE.search(url))


def ensure_schema(engine: Engine) -> None:
    insp = inspect(engine)
    tables = insp.get_table_names()

    if "candidates" in tables:
        cols = {c["name"] for c in insp.get_columns("candidates")}
        if "figma_url" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE candidates ADD COLUMN figma_url TEXT"))
            logger.info("Added candidates.figma_url column")

    if "polls" in tables:
        cols = {c["name"] for c in insp.get_columns("polls")}
        if "max_selections" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE polls ADD COLUMN max_selections INTEGER NOT NULL DEFAULT 3"))
            logger.info("Added polls.max_selections column")
        if "poll_type" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE polls ADD COLUMN poll_type VARCHAR(20) NOT NULL DEFAULT 'open'"))
            logger.info("Added polls.poll_type column")
        if "verify_fields" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE polls ADD COLUMN verify_fields VARCHAR(50) NOT NULL DEFAULT 'name,email,phone'")
                )
            logger.info("Added polls.verify_fields column")
        if "kind" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE polls ADD COLUMN kind VARCHAR(20) NOT NULL DEFAULT 'vote'"))
            logger.info("Added polls.kind column")
        if "verify_method" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE polls ADD COLUMN verify_method VARCHAR(20) NOT NULL DEFAULT 'pin'"))
            logger.info("Added polls.verify_method column")
        if "identity_mode" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE polls ADD COLUMN identity_mode VARCHAR(20) NOT NULL DEFAULT 'secret'"))
            logger.info("Added polls.identity_mode column")
        if "owner_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE polls ADD COLUMN owner_id VARCHAR(200)"))
            logger.info("Added polls.owner_id column")
        if "owner_name" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE polls ADD COLUMN owner_name VARCHAR(200)"))
            logger.info("Added polls.owner_name column")

    if "admins" in tables:
        admin_cols = {c["name"] for c in insp.get_columns("admins")}
        if "idp_sub" not in admin_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE admins ADD COLUMN idp_sub VARCHAR(200)"))
            logger.info("Added admins.idp_sub column")

    if "ballots" in tables:
        cols = {c["name"] for c in insp.get_columns("ballots")}
        if "eligible_voter_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE ballots ADD COLUMN eligible_voter_id INTEGER"))
            logger.info("Added ballots.eligible_voter_id column")
        if "ballot_token_hash" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE ballots ADD COLUMN ballot_token_hash VARCHAR(64)"))
            logger.info("Added ballots.ballot_token_hash column")

    if "eligible_voters" in tables:
        cols = {c["name"] for c in insp.get_columns("eligible_voters")}
        if "pin_hash" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE eligible_voters ADD COLUMN pin_hash VARCHAR(255)"))
            logger.info("Added eligible_voters.pin_hash column")
        if "idp_sub" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE eligible_voters ADD COLUMN idp_sub VARCHAR(200)"))
            logger.info("Added eligible_voters.idp_sub column")


def migrate_figma_urls(db: Session) -> None:
    moved = 0
    for cand in db.query(Candidate).all():
        if cand.figma_url:
            continue
        if is_figma_url(cand.image_url):
            cand.figma_url = cand.image_url
            cand.image_url = None
            moved += 1
    if moved:
        db.commit()
        logger.info("Moved %s Figma URL(s) from image_url to figma_url", moved)

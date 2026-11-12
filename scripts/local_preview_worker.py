"""Optional local-only paper observer; never approves or sends exchange orders.

Enabled only with NEXORA_PREVIEW_WORKER=YES in the already guarded local API.
One scan per timeframe window, protective settlement checks every 60 seconds.
"""
import asyncio
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.user import User
from app.models.desktop_paper_bot import DesktopPaperBot
from app.models.paper_preview import PaperPreviewEnrollment, PaperPreviewPosition
from app.api.routes.paper_preview import scan, settle, _KRAKEN_INTERVALS

log = logging.getLogger(__name__)


async def observer_loop():
    while True:
        try:
            with SessionLocal() as db:
                targets = db.query(PaperPreviewEnrollment).filter(
                    PaperPreviewEnrollment.observer_enabled.is_(True)
                ).all()
                ids = [(row.user_id, row.bot_id) for row in targets]
            for user_id, bot_id in ids:
                with SessionLocal() as db:
                    user = db.query(User).filter(User.id == user_id).first()
                    bot = db.query(DesktopPaperBot).filter(
                        DesktopPaperBot.id == bot_id,
                        DesktopPaperBot.user_id == user_id,
                    ).first()
                    record = db.query(PaperPreviewEnrollment).filter(
                        PaperPreviewEnrollment.bot_id == bot_id,
                        PaperPreviewEnrollment.user_id == user_id,
                        PaperPreviewEnrollment.observer_enabled.is_(True),
                    ).first()
                    if not user or not bot or not record:
                        continue
                    try:
                        open_position = db.query(PaperPreviewPosition).filter(
                            PaperPreviewPosition.bot_id == bot_id,
                            PaperPreviewPosition.user_id == user_id,
                            PaperPreviewPosition.status == "OPEN",
                        ).first()
                        if open_position:
                            await settle(bot_id, db=db, user=user)
                        elif bot.timeframe in _KRAKEN_INTERVALS:
                            interval_seconds = _KRAKEN_INTERVALS[bot.timeframe] * 60
                            if not record.last_scanned_at or (
                                datetime.utcnow() - record.last_scanned_at
                            ).total_seconds() >= interval_seconds:
                                await scan(bot_id, db=db, user=user)
                    except Exception:
                        db.rollback()
                        log.exception("Paper observer failed for bot %s; no approval attempted", bot_id)
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Local paper observer iteration failed")
        await asyncio.sleep(60)

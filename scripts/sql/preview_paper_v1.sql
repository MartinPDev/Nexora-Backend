-- Apply manually to local cryptobot after a verified backup; never run against production.
BEGIN;
CREATE TABLE IF NOT EXISTS nexora_preview_enrollments (
 bot_id varchar PRIMARY KEY REFERENCES nexora_desktop_paper_bots(id),
 user_id varchar NOT NULL REFERENCES users(id),
 observer_enabled boolean NOT NULL DEFAULT false,
 last_action varchar(20),
 last_reason text,
 last_scanned_at timestamp,
 created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_preview_enrollments_user ON nexora_preview_enrollments(user_id);
CREATE TABLE IF NOT EXISTS nexora_preview_proposals (
 id varchar PRIMARY KEY,
 user_id varchar NOT NULL REFERENCES users(id),
 bot_id varchar NOT NULL REFERENCES nexora_desktop_paper_bots(id),
 symbol varchar NOT NULL,
 candle_timestamp numeric(20,0) NOT NULL,
 price numeric(24,10) NOT NULL,
 quantity numeric(24,12) NOT NULL,
 principal numeric(18,8) NOT NULL,
 fee numeric(18,8) NOT NULL,
 payload_hash varchar(64) NOT NULL,
 status varchar(20) NOT NULL DEFAULT 'PENDING',
 created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
 expires_at timestamp NOT NULL,
 CONSTRAINT uq_preview_bot_candle UNIQUE(bot_id,candle_timestamp)
);
CREATE INDEX IF NOT EXISTS ix_preview_proposals_user ON nexora_preview_proposals(user_id);
CREATE INDEX IF NOT EXISTS ix_preview_proposals_bot ON nexora_preview_proposals(bot_id);
CREATE TABLE IF NOT EXISTS nexora_preview_positions (
 id varchar PRIMARY KEY,
 user_id varchar NOT NULL REFERENCES users(id),
 bot_id varchar NOT NULL REFERENCES nexora_desktop_paper_bots(id),
 proposal_id varchar NOT NULL UNIQUE REFERENCES nexora_preview_proposals(id),
 symbol varchar NOT NULL,
 entry_price numeric(24,10) NOT NULL,
 quantity numeric(24,12) NOT NULL,
 principal numeric(18,8) NOT NULL,
 entry_fee numeric(18,8) NOT NULL,
 peak_price numeric(24,10) NOT NULL,
 status varchar(20) NOT NULL DEFAULT 'OPEN',
 opened_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
 closed_at timestamp,
 exit_price numeric(24,10),
 exit_fee numeric(18,8),
 pnl numeric(18,8),
 exit_reason varchar
);
CREATE INDEX IF NOT EXISTS ix_preview_positions_user ON nexora_preview_positions(user_id);
CREATE INDEX IF NOT EXISTS ix_preview_positions_bot ON nexora_preview_positions(bot_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_preview_open_bot ON nexora_preview_positions(bot_id) WHERE status='OPEN';
COMMIT;

-- v0.2: tamper-evident review trail. Each decision stores the previous decision's hash and its own
-- hash = sha256(canonical JSON of {content_hash, prev_hash}), where content_hash = sha256(canonical
-- decision JSON); see docs/data-model.md §5. Rows written before this migration are chained once, in
-- insertion order, by Store._migrate in the same transaction as this script.
DROP TRIGGER IF EXISTS reviews_no_update;
ALTER TABLE reviews ADD COLUMN prev_hash TEXT;
ALTER TABLE reviews ADD COLUMN hash TEXT;
ALTER TABLE reviews ADD COLUMN redacted INTEGER NOT NULL DEFAULT 0;
-- Set only when a decision is redacted: the content hash of the erased decision, so the chain still
-- verifies the link (verify_review_chain recomputes `hash` from it) while the content is gone.
ALTER TABLE reviews ADD COLUMN content_hash TEXT;
-- Updates are refused except (a) the one-time hash backfill of a v0.1 row, which may only add the
-- hashes, and (b) erasure of a deleted document's review content (design-review D15), which may only
-- replace the content with the fixed marker, blank the target and record the content hash; the id,
-- time and hashes stay, so the chain still links and still detects any other change.
CREATE TRIGGER reviews_no_update BEFORE UPDATE ON reviews
WHEN NOT (
  (OLD.hash IS NULL AND NEW.hash IS NOT NULL AND NEW.prev_hash IS NOT NULL AND OLD.prev_hash IS NULL
   AND NEW.json = OLD.json AND NEW.id = OLD.id AND NEW.redacted = OLD.redacted AND OLD.redacted = 0
   AND NEW.target_kind = OLD.target_kind AND NEW.target_id = OLD.target_id AND NEW.at = OLD.at
   AND NEW.content_hash IS NULL)
  OR (OLD.redacted = 0 AND NEW.redacted = 1 AND NEW.id = OLD.id AND OLD.hash IS NOT NULL
      AND NEW.hash IS OLD.hash AND NEW.prev_hash IS OLD.prev_hash AND NEW.at = OLD.at
      AND NEW.json = '{"redacted":true}' AND NEW.target_kind = 'redacted' AND NEW.target_id = ''
      AND OLD.content_hash IS NULL AND NEW.content_hash IS NOT NULL AND length(NEW.content_hash) = 64)
)
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;
CREATE TRIGGER reviews_no_delete BEFORE DELETE ON reviews
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;

-- v0.2: tamper-evident review trail. Each decision stores the previous decision's hash and its own
-- hash = sha256(canonical JSON of {decision, prev_hash}); see docs/data-model.md §5.
-- Rows written before this migration are chained once, in insertion order, by Store._migrate.
DROP TRIGGER IF EXISTS reviews_no_update;
ALTER TABLE reviews ADD COLUMN prev_hash TEXT;
ALTER TABLE reviews ADD COLUMN hash TEXT;
ALTER TABLE reviews ADD COLUMN redacted INTEGER NOT NULL DEFAULT 0;
-- Updates are refused except (a) the one-time hash backfill of a v0.1 row and (b) erasure of a
-- deleted document's review content (design-review D15), which keeps the row's id and hashes so the
-- chain still links.
CREATE TRIGGER reviews_no_update BEFORE UPDATE ON reviews
WHEN NOT (
  (OLD.hash IS NULL AND NEW.hash IS NOT NULL AND NEW.prev_hash IS NOT NULL AND NEW.json = OLD.json
   AND NEW.id = OLD.id AND NEW.redacted = OLD.redacted)
  OR (OLD.redacted = 0 AND NEW.redacted = 1 AND NEW.id = OLD.id AND NEW.hash IS OLD.hash
      AND NEW.prev_hash IS OLD.prev_hash)
)
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;
CREATE TRIGGER reviews_no_delete BEFORE DELETE ON reviews
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;

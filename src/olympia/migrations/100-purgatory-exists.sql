-- Sandboxed add-ons move to purgatory; bug 614686
UPDATE addons SET status=10 WHERE status=1;

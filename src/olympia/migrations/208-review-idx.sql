CREATE INDEX latest_reviews
    ON reviews (reply_to, is_latest, addon_id, created);

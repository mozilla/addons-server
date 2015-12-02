DELETE FROM download_sources WHERE id=17 AND name='userprofile';

INSERT INTO download_sources (name, type, created)
    VALUES
    ('version-history', 'full', NOW()),
    ('addon-detail-version', 'full', NOW());

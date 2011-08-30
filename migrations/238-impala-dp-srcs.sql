DELETE FROM download_sources WHERE type = 'prefix' AND name IN ('co-hc-', 'co-dp-');

INSERT INTO download_sources (name, type, created)
    VALUES ('co-hc-sidebar', 'full', NOW()),
           ('co-dp-sidebar', 'full', NOW()),
           ('dp-hc-dependencies', 'full', NOW()),
           ('dp-dl-dependencies', 'full', NOW()),
           ('dp-hc-upsell', 'full', NOW()),
           ('dp-dl-upsell', 'full', NOW()),
           ('discovery-dependencies', 'full', NOW()),
           ('discovery-upsell', 'full', NOW());

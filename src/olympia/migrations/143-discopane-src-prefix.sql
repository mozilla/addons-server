DELETE FROM download_sources WHERE name
    IN ('discovery-pane', 'discovery-pane-details', 'discovery-pane-eula');

INSERT INTO download_sources (name, type, created)
    VALUES ('discovery-', 'prefix', NOW());

INSERT INTO waffle_switch (name, active, note, created, modified)
VALUES ('akismet-rating-action', 0, 'Take action if Akismet flags a rating as spam', NOW(), NOW()),
VALUES ('akismet-addon-action', 0, 'Take action if Akismet flags addon metadata as spam', NOW(), NOW()),
VALUES ('akismet-collection-action', 0, 'Take action if Akismet flags collection metadata as spam', NOW(), NOW())
;

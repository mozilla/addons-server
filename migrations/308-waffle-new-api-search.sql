INSERT INTO `waffle_flag`
    (name, everyone, percent, superusers, staff, authenticated, rollout, note) VALUES
    ('new-api-search', 0, NULL, 0, 0, 0, 0, 'Enables the ES backed for API search (away from Sphinx).');
DELETE FROM waffle_switch WHERE name='new-api-search';

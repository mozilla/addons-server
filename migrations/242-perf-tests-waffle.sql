# This is wrong. See migration 243
INSERT INTO `waffle_flag`
    (name, everyone, percent, superusers, staff, authenticated, rollout, note) VALUES
    ('perf-tests',1,NULL,1,0,0,0, 'Allow devs to start addon perf tests');

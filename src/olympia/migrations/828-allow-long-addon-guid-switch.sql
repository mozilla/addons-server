INSERT INTO
    waffle_switch (name, active, created, modified, note)
VALUES
    ('allow-long-addon-guid', 0, NOW(), NOW(), 'Allow submission of add-ons with a GUID longer than 64 chars (bug 1203915)');

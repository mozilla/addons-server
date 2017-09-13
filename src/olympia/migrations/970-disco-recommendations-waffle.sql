INSERT INTO waffle_switch (name, active, created, modified, note)
    VALUES ('disco-recommendations', 0, NOW(), NOW(),
            'Enable switch to include recommendations from the taar service in '
            'the discovery api responses, if telemetry-client-id provided.');

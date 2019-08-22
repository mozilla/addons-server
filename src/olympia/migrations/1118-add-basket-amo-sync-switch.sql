INSERT IGNORE INTO waffle_switch (name, active, created, modified, note)
    VALUES ('basket-amo-sync', 0, NOW(), NOW(),
            'Enable switch to synchronize add-on & user data to Salesforce through Basket.');

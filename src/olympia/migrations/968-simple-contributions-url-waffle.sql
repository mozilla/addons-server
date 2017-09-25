INSERT INTO waffle_switch (name, active, created, modified, note)
    VALUES ('simple-contributions', 0, NOW(), NOW(),
            'Enable switch to show simple contributions url on public facing '
            'pages, rather than the paypal based contribution feature.');

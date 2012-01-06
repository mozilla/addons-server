INSERT INTO waffle_switch (name, active, note)
    VALUES ('zamboni-login', 0,
            'Flip this when AMO ditches remora and uses django for '
             'authentication. Enabling this switch will show success messages '
             'when users log in and register via Django.');

DELETE FROM waffle_switch WHERE name IN (
    'allow-refund', 'paypal-disable', 'browserid-login', 'collection-stats',
    'video-encode', 'theme-stats'
);

insert into waffle_switch_mkt (name, active, note, created, modified)
       values ('geoip-geodude', 0,
               'Toggles using the geodude GeoIP server to determine region',
               NOW(), NOW());

INSERT INTO waffle_switch_mkt (name, active, note)
VALUES ('in-app-payments-ui', 0, "Support in-app payments UI." )
ON DUPLICATE KEY UPDATE active = 0;

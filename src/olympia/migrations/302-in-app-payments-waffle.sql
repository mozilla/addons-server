INSERT INTO waffle_switch (name, active, note)
VALUES ('in-app-payments', 0, "Support in-app payments." )
ON DUPLICATE KEY UPDATE active = 0;

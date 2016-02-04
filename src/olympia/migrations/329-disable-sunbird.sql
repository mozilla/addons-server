-- disable sunbird; bug 617989
UPDATE applications SET supported=0 WHERE id=52 LIMIT 1;

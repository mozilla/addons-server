-- There should be only 126.
SET FOREIGN_KEY_CHECKS=0;
UPDATE addons SET description=NULL WHERE id=269980;
DELETE FROM translations WHERE locale > 0 LIMIT 150;
SET FOREIGN_KEY_CHECKS=1;

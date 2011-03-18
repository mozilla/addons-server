ALTER TABLE cannedresponses ADD COLUMN `sort_group` varchar(255) default NULL;

UPDATE cannedresponses SET sort_group=CONCAT_WS(',', sort_group, 'public') WHERE id IN (29, 33, 36, 34);
UPDATE cannedresponses SET sort_group=CONCAT_WS(',', sort_group, 'prelim') WHERE id IN (30, 31, 47, 37, 39, 44, 45, 36, 42, 46, 48, 34);
UPDATE cannedresponses SET sort_group=CONCAT_WS(',', sort_group, 'reject') WHERE id IN (32, 35, 43, 41, 37, 40, 39, 44, 45, 36, 42, 46, 34);
UPDATE cannedresponses SET sort_group=CONCAT_WS(',', sort_group, 'info') WHERE id IN (38);


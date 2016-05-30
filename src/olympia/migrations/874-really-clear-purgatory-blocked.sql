-- There shouldn't be any add-ons with this status but double checking.
UPDATE addons SET status=5 WHERE status in (10, 15);

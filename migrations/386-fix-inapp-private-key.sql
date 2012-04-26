-- We can't use these values anymore. The side effect here is that each app will
-- have to reconfigure their in-app payments.
DELETE FROM addon_inapp_log;
DELETE FROM addon_inapp_payment;
DELETE FROM addon_inapp;
-- Remove the unique constraint (it is handled in code).
ALTER TABLE addon_inapp DROP COLUMN private_key;
-- Switch from varbinary to blob.
ALTER TABLE addon_inapp ADD COLUMN private_key BLOB NULL;

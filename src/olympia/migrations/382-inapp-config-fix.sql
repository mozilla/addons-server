-- We can't use these values anymore. The side effect here is that each app will
-- have to reconfigure their in-app payments.
DELETE FROM addon_inapp_log;
DELETE FROM addon_inapp_payment;
DELETE FROM addon_inapp;
ALTER TABLE addon_inapp MODIFY COLUMN private_key VARBINARY(128) NULL;

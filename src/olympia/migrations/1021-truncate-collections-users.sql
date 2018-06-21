-- The collections contributors feature is being removed, but we need the
-- table to still be present during deploy, so only truncate it now, we'll
-- fully remove it during the following push.
TRUNCATE `collections_users`;

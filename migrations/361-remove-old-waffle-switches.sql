-- Deleted in this patch
DELETE FROM waffle_switch_amo WHERE name in ('zamboni-login');
DELETE FROM waffle_switch_mkt WHERE name in ('zamboni-login');

-- Can't find a reference to this in the code....?
DELETE FROM waffle_switch_amo WHERE name in ('zamboni-file-viewer');
DELETE FROM waffle_switch_mkt WHERE name in ('zamboni-file-viewer');

-- Deleted a while ago I think
DELETE FROM waffle_switch_amo WHERE name in ('market-ui-experiments');
DELETE FROM waffle_switch_mkt WHERE name in ('market-ui-experiments');

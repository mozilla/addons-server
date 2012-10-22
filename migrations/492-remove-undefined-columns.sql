-- nominationdate was in remora and moved to versions in commit 24016f3c9b7840c1c4fa59a687d49b7a733c8326.
ALTER TABLE addons DROP COLUMN nominationdate;
-- nominationage has no trace of usage in zamboni and recent addons have this column set to zero.
ALTER TABLE addons DROP COLUMN nominationage;
-- show_beta was removed from models in commit b47e4575e5c74f10b15101248e0b5abad320376c and set as a property.
ALTER TABLE addons DROP COLUMN show_beta;

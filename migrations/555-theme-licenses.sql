-- Instead of a foreign-key relationship, `license` corresponds to an ID
-- for a license constant.
alter table personas drop foreign key personas_ibfk_4;

alter table personas change column license_id license int(11) unsigned null;

-- All Rights Reserved
update personas set license = 1 where license in (7, 1034);

-- Creative Commons Attribution 3.0
update personas set license = 2 where license = 9;

-- Creative Commons Attribution-NonCommercial 3.0
update personas set license = 3 where license = 10;

-- Creative Commons Attribution-NonCommercial-NoDerivs 3.0
update personas set license = 4 where license = 11;

-- Creative Commons Attribution-Noncommercial-Share Alike 3.0
update personas set license = 5 where license in (8, 1035);

-- Creative Commons Attribution-NoDerivs 3.0
update personas set license = 6 where license = 12;

-- Creative Commons Attribution-ShareAlike 3.0
update personas set license = 7 where license = 13;

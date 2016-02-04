-- Got rid of FUTURE region and made it WORLDWIDE.
update addons_excluded_regions set region = 1 where region = 999;

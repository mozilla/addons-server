-- bug 658577
-- Run this on production to fix the version bump.
-- Run the verify script again afterwards to make sure it returns
-- empty results.
begin;
update applications_versions av
join appversions curmax on av.max=curmax.id
join appversions newmax on av.application_id=newmax.application_id
join versions v on v.id=av.version_id
join addons a on a.id=v.addon_id
set av.max = newmax.id
where
-- Firefox:
av.application_id=1
-- Version accidentally set by validator:
and curmax.version='5.*'
-- Version we want:
and newmax.version='4.0.*'\G

-- activity for BULK_VALIDATION_UPDATED
delete from log_activity where action=46\G
commit;

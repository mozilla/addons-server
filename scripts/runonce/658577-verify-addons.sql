-- bug 658577
-- Run this on production to a log to make sure we have the right addons.
-- Note that 5.* was only just created so it should only have
-- auto-validated addons in it.
select
    a.id as addon_id,
    a.slug,
    v.id as addon_version_id,
    v.version as addon_version,
    av.application_id,
    curmax.version as curmax,
    curmax.id as curmax_id,
    newmax.version as newmax,
    newmax.id as newmax_id
from applications_versions av
join appversions curmax on av.max=curmax.id
join appversions newmax on av.application_id=newmax.application_id
join versions v on v.id=av.version_id
join addons a on a.id=v.addon_id
where
-- Firefox:
av.application_id=1
-- Version accidentally set by validator:
and curmax.version='5.*'
-- Version we want:
and newmax.version='4.0.*'\G

-- activity for BULK_VALIDATION_UPDATED
select * from log_activity where action=46\G

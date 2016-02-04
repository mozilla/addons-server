-- From Sheeri in bug 716087
alter table users add index(resetcode_expires);
alter table stats_share_counts add index(service);

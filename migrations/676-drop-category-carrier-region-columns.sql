-- Delete supervisors of legacy operator shelves/special categories.
drop table categories_supervisors;

-- Delete legacy operator shelves/special categories.
delete from categories where carrier is not null or region is not null;

-- Remove unnecessary columns (collections are the new hotness).
alter table categories drop column carrier;
alter table categories drop column region;

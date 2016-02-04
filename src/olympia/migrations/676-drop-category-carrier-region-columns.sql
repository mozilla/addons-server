-- Delete supervisors of legacy operator shelves/special categories.
drop table categories_supervisors;

-- Cascade deletes for addons_categories.
alter table addons_categories drop foreign key addons_categories_ibfk_4;
alter table addons_categories add constraint addons_categories_ibfk_4 foreign key (category_id) REFERENCES categories (id) ON DELETE CASCADE;

-- Collections are the new hotness. Drop featured-specific models.
drop table zadmin_featuredapp;
drop table zadmin_featuredappcarrier;
drop table zadmin_featuredappregion;

-- Delete legacy operator shelves/special categories.
delete from categories where carrier is not null or region is not null;

-- Remove unnecessary columns (collections are the new hotness).
alter table categories drop column carrier;
alter table categories drop column region;

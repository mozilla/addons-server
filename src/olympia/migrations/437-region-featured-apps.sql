alter table zadmin_featuredapp add column region tinyint(2) unsigned not null default '0';
create index zadmin_featuredapp_region_idx on zadmin_featuredapp (region);

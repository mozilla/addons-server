alter table zadmin_featuredapp add column region varchar(255);
create index zadmin_featuredapp_region_idx on zadmin_featuredapp (region);

alter table addons add index(name,status,addontype_id), drop index addons_ibfk_2;

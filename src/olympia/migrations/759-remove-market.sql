DROP TABLE IF EXISTS refunds;
DROP TABLE IF EXISTS price_currency;
DROP TABLE IF EXISTS addons_premium;
DROP TABLE IF EXISTS inapp_products;
DROP TABLE IF EXISTS addon_purchase;
DROP TABLE IF EXISTS addon_payment_data;
DROP TABLE IF EXISTS paypal_checkstatus;


drop procedure if exists drop_fk_col_if_exists;

delimiter ';;'

create procedure drop_fk_col_if_exists() begin
    /* drop the foreign keys if they exist */
    if exists (select * from information_schema.table_constraints where table_schema = (SELECT DATABASE()) and table_name = 'stats_contributions' and constraint_name = 'related_id_refs') then
        alter table stats_contributions drop foreign key related_id_refs;
    end if;
    if exists (select * from information_schema.table_constraints where table_schema = (SELECT DATABASE()) and table_name = 'stats_contributions' and constraint_name = 'price_tier_id_refs') then
        alter table stats_contributions drop foreign key price_tier_id_refs;
    end if;
    if exists (select * from information_schema.table_constraints where table_schema = (SELECT DATABASE()) and table_name = 'stats_contributions' and constraint_name = 'user_id_refs') then
        alter table stats_contributions drop foreign key user_id_refs;
    end if;

    /* drop the columns if they exist */
    if exists (select * from information_schema.columns where table_schema = (SELECT DATABASE()) and table_name = 'stats_contributions' and column_name = 'price_tier_id') then
        alter table stats_contributions drop column price_tier_id;
    end if;
    if exists (select * from information_schema.columns where table_schema = (SELECT DATABASE()) and table_name = 'stats_contributions' and column_name = 'related_id') then
        alter table stats_contributions drop column related_id;
    end if;
    if exists (select * from information_schema.columns where table_schema = (SELECT DATABASE()) and table_name = 'stats_contributions' and column_name = 'user_id') then
        alter table stats_contributions drop column user_id;
    end if;
    if exists (select * from information_schema.columns where table_schema = (SELECT DATABASE()) and table_name = 'stats_contributions' and column_name = 'type') then
        alter table stats_contributions drop column type;
    end if;
end;;

delimiter ';'

call drop_fk_col_if_exists();

drop procedure if exists drop_fk_col_if_exists;

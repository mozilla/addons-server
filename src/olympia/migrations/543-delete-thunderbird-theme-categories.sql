-- Remove add-ons from Thunderbird Persona categories.
delete from addons_categories where category_id in (select id from categories where addontype_id = 9 and application_id = 18);

-- Delete Thunderbird Persona categories.
delete from categories where addontype_id = 9 and application_id = 18;

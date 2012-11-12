-- This was never even a foreign key. Tsk, tsk.
ALTER TABLE addons_devicetypes ADD CONSTRAINT addons_devicetypes_addon_id_fk
    FOREIGN KEY (addon_id) REFERENCES addons (id) ON DELETE CASCADE;

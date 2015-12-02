-- Moves nomination date from addon to version per bug 638855.
-- Also see migration 163 which adds the nomination column to versions.
UPDATE versions v
    INNER JOIN addons a ON (a.id = v.addon_id AND v.nomination IS NULL)
    SET v.nomination = a.nominationdate;
-- Not deleting addons.nominationdate as a sacrificial token
-- to please the gods of Remora

CREATE TABLE `frozen_addons` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `addon_id` integer NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE addons
    ADD COLUMN `hotness` double NOT NULL DEFAULT 0;

CREATE INDEX hotness_idx on addons (hotness);

-- See you in a couple hours.
CREATE INDEX addon_date_idx ON update_counts (addon_id, date);

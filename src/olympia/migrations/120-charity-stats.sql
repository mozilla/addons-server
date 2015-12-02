ALTER TABLE stats_contributions
    ADD COLUMN charity_id int(11) UNSIGNED,
    ADD CONSTRAINT FOREIGN KEY (charity_id) REFERENCES charities (id);

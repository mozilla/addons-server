ALTER TABLE applications_versions DROP FOREIGN KEY `applications_versions_ibfk_3`;
ALTER TABLE appversions DROP FOREIGN KEY `appversions_ibfk_1`;
ALTER TABLE collections DROP FOREIGN KEY `collections_ibfk_1`;
ALTER TABLE compat_override_range DROP FOREIGN KEY `compat_override_range_ibfk_1`;
ALTER TABLE features DROP FOREIGN KEY `features_ibfk_2`;
ALTER TABLE file_uploads DROP FOREIGN KEY `compat_with_app_id_refs_id_939661ad`;
ALTER TABLE incompatible_versions DROP FOREIGN KEY `incompatible_versions_ibfk_1`;
DROP TABLE applications;

-- Convert the last of our myisam tables to innodb. bug 804136

ALTER TABLE addons_dependencies engine=InnoDB;
ALTER TABLE appsupport engine=InnoDB, CONVERT TO CHARSET utf8;
ALTER TABLE discovery_modules engine=InnoDB, CONVERT TO CHARSET utf8;
ALTER TABLE email_preview engine=InnoDB, CONVERT TO CHARSET utf8;
ALTER TABLE featured_collections engine=InnoDB, CONVERT TO CHARSET utf8;
ALTER TABLE file_validation engine=InnoDB, CONVERT TO CHARSET utf8;
ALTER TABLE schema_version engine=InnoDB, CONVERT TO CHARSET utf8;
ALTER TABLE validation_job engine=InnoDB, CONVERT TO CHARSET utf8;
ALTER TABLE validation_result engine=InnoDB, CONVERT TO CHARSET utf8;
ALTER TABLE zadmin_siteevent engine=InnoDB, CONVERT TO CHARSET utf8;
ALTER TABLE zadmin_siteevent_mkt engine=InnoDB, CONVERT TO CHARSET utf8;

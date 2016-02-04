-- Make this a bool until I figure out why -dev choked on this.
ALTER TABLE `users` CHANGE COLUMN
  `read_dev_agreement` `read_dev_agreement` BOOL;

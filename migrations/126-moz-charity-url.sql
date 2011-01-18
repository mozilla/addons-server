-- Charity 1 was set to the Foundation in migration 88.
UPDATE charities SET url='http://www.mozilla.org/foundation/' WHERE id=1;

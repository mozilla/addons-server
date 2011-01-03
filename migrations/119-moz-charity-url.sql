-- Charity 1 was set to the Foundation in migration 88.
UPDATE charities SET url='http://www.mozilla.org/foundation/donate.html' WHERE id=1;

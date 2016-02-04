-- Set listed add-ons to disabled.
UPDATE addons SET status=5, nominationmessage='Disabling listed add-ons.' WHERE status=6;

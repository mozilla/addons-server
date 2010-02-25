-- Bug 543899
UPDATE collections SET addonCount=0 WHERE id IN (8280,29452,54397,2619);

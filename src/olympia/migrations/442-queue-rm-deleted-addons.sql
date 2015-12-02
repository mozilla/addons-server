DELETE FROM rereview_queue WHERE addon_id IN (SELECT id FROM addons WHERE addontype_id=11 AND status=11);
DELETE FROM escalation_queue WHERE addon_id IN (SELECT id FROM addons WHERE addontype_id=11 AND status=11);

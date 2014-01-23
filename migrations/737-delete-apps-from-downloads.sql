DELETE download_counts FROM download_counts
JOIN addons ON download_counts.addon_id=addons.id
WHERE addons.addontype_id=11;

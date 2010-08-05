UPDATE reviews SET addon_id=(SELECT addon_id FROM versions WHERE id=version_id);

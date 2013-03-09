UPDATE versions, addons
SET versions.nomination=versions.created
WHERE versions.addon_id=addons.id AND
      addons.addontype_id=11 AND
      versions.nomination IS NULL;

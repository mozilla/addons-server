-- Remove IARC related info from deleted apps.
DELETE webapps_iarc_info FROM webapps_iarc_info LEFT JOIN addons ON addons.id=webapps_iarc_info.addon_id WHERE addons.status=11;
DELETE webapps_contentrating FROM webapps_contentrating LEFT JOIN addons ON addons.id=webapps_contentrating.addon_id WHERE addons.status=11;
DELETE webapps_rating_descriptors FROM webapps_rating_descriptors LEFT JOIN addons ON addons.id=webapps_rating_descriptors.addon_id WHERE addons.status=11;
DELETE webapps_rating_interactives FROM webapps_rating_interactives LEFT JOIN addons ON addons.id=webapps_rating_interactives.addon_id WHERE addons.status=11;

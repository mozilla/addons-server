from mkt.constants import regions


def parse_region(region):
    """
    Returns a region class definition given a slug, id, or class definition.
    """

    if isinstance(region, type) and issubclass(region, regions.REGION):
        return region

    if str(region).isdigit():
        # Look up the region by ID.
        return regions.REGIONS_CHOICES_ID_DICT[int(region)]
    else:
        # Look up the region by slug.
        region_by_slug = regions.REGIONS_DICT.get(region)
        if region_by_slug is not None:
            return region_by_slug

        # Look up the region by name.
        region_lower = region.lower()
        for region in regions.ALL_REGIONS:
            if unicode(region.name).lower() == region_lower:
                return region

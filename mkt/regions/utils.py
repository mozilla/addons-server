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
        return regions.REGIONS_DICT[region]

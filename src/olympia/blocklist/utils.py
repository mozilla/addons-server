JSON_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def del_none(d):
    """
    Delete keys with the value ``None`` in a dictionary, recursively.

    This alters the input so you may wish to ``copy`` the dict first.
    """
    # d.iteritems isn't used as you can't del or the iterator breaks.
    for key, value in d.items():
        if value is None:
            del d[key]
        elif isinstance(value, dict):
            del_none(value)
        elif isinstance(value, list):
            for v in value:
                if isinstance(v, dict):
                    del_none(v)
                    if not v:
                        d[key] = []

    return d  # For convenience


def certificates_to_json(items):
    results = []
    for cert in items:
        results.append(del_none({
            'blockID': cert.block_id,
            'serialNumber': cert.serial,
            'issuerName': cert.issuer,
            'details': {
                'name': cert.details.name,
                'who': cert.details.who,
                'why': cert.details.why,
                'bug': cert.details.bug,
                'created': cert.details.created.strftime(JSON_DATE_FORMAT),
            }
        }))
    return results


def gfxs_to_json(items):
    results = []
    for gfx in items:
        devices = []
        if gfx.devices:
            devices = [d.strip() for d in gfx.devices.split(' ') if d.strip()]

        version_range = None
        if gfx.application_min or gfx.application_max:
            version_range = del_none({
                'minVersion': gfx.application_min,
                'maxVersion': gfx.application_max
            })

        results.append(del_none({
            'blockID': gfx.block_id,
            'os': gfx.os,
            'vendor': gfx.vendor,
            'devices': devices,
            'feature': gfx.feature,
            'featureStatus': gfx.feature_status,
            'driverVersion': gfx.driver_version,
            'driverVersionMax': gfx.driver_version_max,
            'driverVersionComparator': gfx.driver_version_comparator,
            'hardware': gfx.hardware,
            'versionRange': version_range,
            'details': {
                'name': gfx.details.name,
                'who': gfx.details.who,
                'why': gfx.details.why,
                'bug': gfx.details.bug,
                'created': gfx.details.created.strftime(JSON_DATE_FORMAT),
            }
        }))
    return results


def addons_to_json(items):
    results = []
    for addon in items.values():
        versionRange = []
        guid = addon.rows[0].guid
        name = addon.rows[0].name
        details = addon.rows[0].details
        for row in addon.rows:
            if row.min or row.max or row.severity or row.apps:
                targetApplication = [{
                    'guid': app.guid,
                    'minVersion': app.min,
                    'maxVersion': app.max,
                } for app in row.apps]

                versionRange.append({
                    'minVersion': row.min,
                    'maxVersion': row.max,
                    'severity': row.severity,
                    'targetApplication': targetApplication
                })
        prefs = [pref.strip() for pref in addon.prefs]
        results.append(del_none({
            'guid': guid,
            'blockID': addon.block_id,
            'name': name,
            'os': addon.os,
            'versionRange': versionRange,
            'prefs': prefs,
            'details': {
                'name': details.name,
                'who': details.who,
                'why': details.why,
                'bug': details.bug,
                'created': details.created.strftime(JSON_DATE_FORMAT),
            }
        }))
    return results


def plugins_to_json(items):
    results = []
    for plugin in items:
        record = {
            'blockID': plugin.block_id,
            'name': plugin.name,
            'os': plugin.os,
            'xpcomabi': plugin.xpcomabi,
            'infoURL': plugin.info_url,
            'versionRange': [{
                'minVersion': plugin.min,
                'maxVersion': plugin.max,
                'severity': plugin.severity,
                'vulnerabilityStatus': plugin.get_vulnerability_status,
                'targetApplication': [{
                    'guid': app.guid,
                    'minVersion': app.min,
                    'maxVersion': app.max,
                } for app in plugin.app.all()]
            }],
            'details': {
                'name': plugin.details.name,
                'who': plugin.details.who,
                'why': plugin.details.why,
                'bug': plugin.details.bug,
                'created': plugin.details.created.strftime(JSON_DATE_FORMAT),
            }
        }
        if plugin.name:
            record['matchName'] = plugin.name
        if plugin.description:
            record['matchDescription'] = plugin.description
        if plugin.filename:
            record['matchFilename'] = plugin.filename
        results.append(del_none(record))
    return results

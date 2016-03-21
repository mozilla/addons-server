JSON_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def certificates_to_json(items):
    results = []
    for cert in items:
        results.append({
            'blockID': cert.block_id,
            'serialNumber': cert.serial,
            'issuerName': cert.issuer,
            'details': {
                'who': cert.details.who,
                'why': cert.details.why,
                'bug': cert.details.bug,
                'created': cert.details.created.strftime(JSON_DATE_FORMAT),
            }
        })
    return results


def gfxs_to_json(items):
    results = []
    for gfx in items:
        devices = [d.strip() for d in gfx.devices.split(' ') if d.strip()]
        results.append({
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
            'details': {
                'who': gfx.details.who,
                'why': gfx.details.why,
                'bug': gfx.details.bug,
                'created': gfx.details.created.strftime(JSON_DATE_FORMAT),
            }
        })
    return results


def addons_to_json(items):
    results = []
    for guid, addon in items:
        versionRange = []
        for row in addon.rows:
            if row.min or row.max or row.severity or row.apps:
                targetApplication = []
                for app in row.apps:
                    targetApplication.append({
                        'guid': app.guid,
                        'minVersion': app.min,
                        'maxVersion': app.max,
                    })
                versionRange.append({
                    'minVersion': row.min,
                    'maxVersion': row.max,
                    'severity': row.severity or '0',
                    'targetApplication': targetApplication
                })
        prefs = [pref.strip() for pref in addon.prefs]
        results.append({
            'guid': guid,
            'blockID': addon.block_id,
            'os': addon.os,
            'versionRange': versionRange,
            'prefs': prefs,
            'details': {
                'who': addon.details.who,
                'why': addon.details.why,
                'bug': addon.details.bug,
                'created': addon.details.created.strftime(JSON_DATE_FORMAT),
            }
        })
    return results


def plugins_to_json(items):
    results = []
    for plugin in items:
        record = {
            'blockID': plugin.block_id,
            'os': plugin.os,
            'infoURL': plugin.info_url,
            'versionRange': {
                'minVersion': plugin.min,
                'maxVersion': plugin.max,
                'severity': plugin.severity,
                'vulneratibilityStatus': plugin.get_vulnerability_status,
                'targetApplication': {
                    'guid': plugin.app_guid,
                    'minVersion': plugin.app_min,
                    'maxVersion': plugin.app_max,
                }
            },
            'details': {
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
        results.append(record)
    return results

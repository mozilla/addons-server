from mkt.constants.features import FeatureProfile


def get_feature_profile(request):
    profile = None
    if request.GET.get('dev') in ('firefoxos', 'android'):
        sig = request.GET.get('pro')
        if sig:
            try:
                profile = FeatureProfile.from_signature(sig)
            except ValueError:
                pass
    return profile

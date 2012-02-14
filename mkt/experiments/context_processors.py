def fragment(request):
    is_ajax = request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
    return {'VIEW_FRAGMENT': is_ajax}

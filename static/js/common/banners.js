z.visitor = z.Storage('visitor');
z.currentVisit = z.SessionStorage('current-visit');

function initBanners() {
    var $body = $(document.body);

    if ($body.hasClass('editor-tools')) {
        // Don't bother showing those on editor tools, it has a bunch of weird
        // styles for the menu that don't play nice with those banners.
        return;
    }

    // Show the various banners, but only one at a time, and only if they
    // haven't been dimissed before.
    // To reset dismissal state: z.visitor.remove('xx')

    // Show the bad-browser message
    if (!z.visitor.get('seen_badbrowser_warning') && $body.hasClass('badbrowser')) {
        $('#site-nonfx').show();
    }
    // Show the first visit banner.
    else if (!z.visitor.get('seen_impala_first_visit')) {
        $body.addClass('firstvisit');
        z.visitor.set('seen_impala_first_visit', 1);
    }
    // Show the link to try the new frontend (only on the homepage for now).
    else if (!z.visitor.get('seen_try_new_frontend') && $body.hasClass('home')) {
        $('#try-new-frontend').show();
    }
    // Show the ACR pitch if it has not been dismissed.
    else if (!z.visitor.get('seen_acr_pitch') && $body.hasClass('acr-pitch')) {
        $body.find('#acr-pitch').show();
    }

    // Allow dismissal of site-balloons.
    $body.on('click', '.site-balloon .close, .site-tip .close', _pd(function() {
        var $parent = $(this).closest('.site-balloon, .site-tip');
        $parent.fadeOut();
        if ($parent.is('#site-nonfx')) {
            z.visitor.set('seen_badbrowser_warning', 1);
        } else if ($parent.is('#acr-pitch')) {
            z.visitor.set('seen_acr_pitch', 1);
        } else if ($parent.is('#appruntime-pitch')) {
            z.visitor.set('seen_appruntime_pitch', 1);
        } else if ($parent.is('#try-new-frontend')) {
            z.visitor.set('seen_try_new_frontend', 1);
        }
    }));
}

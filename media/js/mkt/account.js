(function() {
    var el = $('[data-preauth-results]');
    if (!el.exists() || !window.opener) {
        return;
    }
    var opener = window.opener,
        l = window.location,
        origin = l.protocol + '//' + l.host + (l.port && (':' + l.port));
    if (opener) {
        opener.postMessage(el.data('preauth-results'), origin);
    }
})();

(function() {
    if (!$('#account-settings').length) {
        return;
    }

    // Avatar handling.
    var $photo = $('#profile-photo'),
        $avatar = $photo.find('.avatar'),
        $a = $('<a>', {'text': gettext('Use original'),
                       'class': 'use-original',
                       'href': '#'}).hide();

    // Doing a POST on click because deleting on a GET is the worst thing ever.
    z.page.on('click', '#profile-photo .delete', _pd(function() {
        $.post(this.getAttribute('data-posturl')).success(function() {
            // Redirect back to this page.
            window.location = window.location;
        });
    }));

    $avatar.attr('data-original', $avatar.attr('src'));
    function use_original() {
        $photo.find('.use-original').hide();
        $photo.find('#id_photo').val('');
        $avatar.attr('src', $avatar.attr('data-original'));
    }
    $a.click(_pd(use_original));
    $avatar.after($a);

    $('#id_photo').change(function() {
        var $this = $(this),
            $parent = $this.closest('.form-col'),
            file = $this[0].files[0],
            file_name = file.name || file.fileName;
        $parent.find('.errorlist').remove();
        if (!file_name.match(/\.(jpg|png|jpeg)$/i)) {
            $ul = $('<ul>', {'class': 'errorlist'});
            $ul.append($('<li>',
                       {'text': gettext('Images must be either PNG or JPG.')}));
            $parent.append($ul);
            use_original();
            return;
        }
        var img = $this.objectUrl();
        if (img) {
            $a.show();
            $avatar.attr('src', img).addClass('previewed');
        }
    });
})();

(function() {
    z.page.on('fragmentloaded', function() {
        if (!$('#feedback-form').length) {
            return;
        }

        var $form = $('#feedback-form');

        z.page.on('submit', $form, _pd(function(e) {
            if ($form.find('textarea').val()) {
                $form.find('button[type=submit]').attr('disabled', true);
                $.post($form.attr('action'), $form.serialize(), function(data) {
                    $form.replaceWith($('<div>', {
                        'text': gettext('Message sent. Thanks for your feedback.'),
                        'class': 'notification-box success c'}));
                });
            } else {
                if ($form.find('div.error').length === 0) {
                    $form.prepend($('<div>', {
                        'text': gettext('Message must not be empty.'),
                        'class': 'error'}));
                }
            }
        }));

    });
})();

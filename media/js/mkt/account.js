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
    // For stylized <select>s.
    $('.styled.select select').focus(function() {
        $(this).closest('.select').addClass('active');
    }).blur(function() {
        $(this).closest('.select').removeClass('active');
    });

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


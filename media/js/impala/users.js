$(function() {
    if($('#user_edit').exists()) {
        $('.more-all, .more-none').click(_pd(function() {
            var $this = $(this);
            $this.closest('li').find('input:not([disabled]').attr('checked', $this.hasClass('more-all'));
        }));
    }

    // Hide change password box
    $('#acct-password').hide();
    $('#change-acct-password').click(_pd(function() {
          $('#acct-password').show();
          $('#id_oldpassword').focus();
          $(this).closest('li').hide();
    }));

    // Display image inline
    var $avatar = $('.profile-photo .avatar'),
        $a = $('<a>', {'text': gettext('use original'), 'class': 'use-original delete', 'href': '#'}).hide();

    $avatar.attr('data-original', $avatar.attr('src'));
    function use_original() {
        $('.use-original').hide();
        $('#id_photo').val("");
        $avatar.attr('src', $avatar.attr('data-original'));
    }
    $a.click(_pd(use_original));

    $avatar.after($a);
    $('#id_photo').change(function() {
        var $li = $(this).closest('li');
        $li.find('.errorlist').remove();
        if(!$(this)[0].files[0].fileName.match(/\.(jpg|png|jpeg)$/)) {
            $ul = $('<ul>', {'class': 'errorlist'});
            $ul.append($('<li>', {'text': gettext('Images must be either PNG or JPG.')}));
            $li.append($ul);
            use_original();
            return;
        }
        var img = $(this).objectUrl();
        if(img) {
            $a.css('display', 'inline');
            $avatar.attr('src', img);
        }
    });
});

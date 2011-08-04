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
        $a = $('<a>', {'text': 'use original', 'class': 'delete', 'href': '#'}).hide();

    $avatar.attr('data-original', $avatar.attr('src'));
    $a.click(_pd(function() {
        $(this).hide();
        $('#id_photo').val("");
        $avatar.attr('src', $avatar.attr('data-original'));
    }));

    $avatar.after($a);
    $('#id_photo').change(function() {
        var img = $(this).objectUrl();
        if(img) {
            $a.css('display', 'inline');
            $avatar.attr('src', img);
        }
    });
});

$(function() {
    // When I click on the avatar, append `#id=<id>` to the URL.
    $('.user-avatar img').click(_pd(function(e) {
        window.location.hash = 'id=' + $('.user-avatar').data('user-id');
        e.stopPropagation();
    }));

    $('#report-user-modal').modal('#report-user-abuse', {delegate: '#page'});

    if($('#user_edit').exists()) {
        $('.more-all, .more-none').click(_pd(function() {
            var $this = $(this);
            $this.closest('li').find('input:not([disabled]').prop('checked', $this.hasClass('more-all'));
        }));
    }

    // Hide change password box
    $('#acct-password').hide();
    $('#change-acct-password').click(_pd(function() {
          $('#acct-password').fadeIn();
          $('#id_oldpassword').focus();
          $(this).closest('li').hide();
    }));

    // Show password box if there's an error in it.
    $('#acct-password .errorlist li').exists(function() {
        $('#acct-password').show();
        $('#change-acct-password').closest('li').hide();
    });

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
        var $li = $(this).closest('li'),
            file = $(this)[0].files[0],
            file_name = file.name || file.fileName;
        $li.find('.errorlist').remove();
        if(!file_name.match(/\.(jpg|png|jpeg)$/i)) {
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

    if ($('#t-shirt-order-form').length) {
        var validate_required_fields = function() {
            var valid = _.every($(required, $form),
                                function (e) { return $.trim(e.value) });
            $submit.prop('disabled', !valid || null);
        }

        var $form = $('#t-shirt-order-form');
        var $submit = $('#t-shirt-request-submit');

        var required = 'input[aria-required=true], select[aria-required=true]';

        $form.live('change input', required, validate_required_fields);
        validate_required_fields();

        $form.submit(function (e) {
            $submit.prop('disabled', true);

            $.ajax({
                url: location.href,
                type: 'post',
                data: {csrfmiddlewaretoken: $('meta[name=csrf]').attr('content')},
                success: function () {
                    HTMLFormElement.prototype.submit.call($form[0]);
                },
                error: function () {
                    // Show server error message.
                    location.reload();
                }
            });

            e.preventDefault();
        });
    }
});


// Hijack "Admin / Editor Log in" context menuitem.
$('#admin-login').click(function() {
    window.location = $(this).attr('data-url');
});

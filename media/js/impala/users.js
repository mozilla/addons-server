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
});

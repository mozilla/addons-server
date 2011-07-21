$(function() {
    if($('#user_edit').exists()) {
        $('.more-all, .more-none').click(_pd(function() {
            var $this = $(this);
            $this.closest('li').find('input:not([disabled]').attr('checked', $this.hasClass('more-all'));
        }));
    }
});

define('account', [], function() {
    // If the language or region in the <form> change value,
    // then let's do a synchronous POST.
    z.page.on('submit', '#account-settings form', function(e) {
        var $this = $(this);
        $this.find('select[name=lang], select[name=region]').each(function() {
            var $this = $(this);
            if ($this.val() != $this.find('[data-default]').val()) {
                $this.trigger('reloadonnext');
                return;
            }
        });
    });
});

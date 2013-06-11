(function() {
    $('form').on('click', '.toggles a', _pd(function() {
        var $this = $(this);
        var $choices = $this.closest('td, div').find('.checkbox-choices input[type=checkbox]:not(:disabled)');
        if ($this.hasClass('all')) {
            $choices.prop('checked', true).trigger('change');
        } else {
            $choices.prop('checked', false).trigger('change');
        }
    })).on('editLoaded.disableCheckboxes', function(e) {
        // Disable individual checkbox fields when we see them.
        // (Customizing Django's CheckboxSelectMultiple widget is stupid.)
        $('.checkbox-choices[data-disabled]').each(function() {
            var $this = $(this);
            var choices = JSON.parse($this.attr('data-disabled'));
            var selectors = _.map(choices, function(val) {
                return format('input[value="{0}"]', val);
            });
            $this.find(selectors.join(', ')).attr('disabled', true).removeAttr('checked');
        });
    });
})();

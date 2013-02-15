define('forms', [], function() {
    // For stylized <select>s.
    z.body.on('focus', '.styled.select select', function() {
        $(this).closest('.select').addClass('active');
    }).on('blur', '.styled.select select', function() {
        $(this).closest('.select').removeClass('active');
    });

    function checkValid(form) {
        if (form) {
            $(form).find('button[type=submit]').attr('disabled', !form.checkValidity());
        }
    }
    z.doc.on('change keyup paste', 'input, select, textarea', function(e) {
        checkValid(e.target.form);
    }).on('fragmentloaded', function() {
        $('form').each(function() {
            checkValid(this);
        });
    });
});

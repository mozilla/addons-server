(function() {
    // For stylized <select>s.
    z.body.on('focus', '.styled.select select', function() {
        $(this).closest('.select').addClass('active');
    }).on('blur', '.styled.select select', function() {
        $(this).closest('.select').removeClass('active');
    });
})();

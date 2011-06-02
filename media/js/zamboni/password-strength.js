function initStrength(nodes) {
    function complexity(text) {
        var score = 0;
        if (text.length > 7) { score++; }
        if (text.length > 12) { score++; }
        if (text.match(/[0-9]/)) { score++; }
        if (text.match(/[a-z]/) && text.match(/[A-Z]/)) { score++; }
        if (text.match(/[^a-zA-Z0-9]/)) { score++; }
        if (score < 3) {
            return [gettext('Password strength: weak.'), 'weak'];
        } else if (score < 4) {
            return [gettext('Password strength: medium.'), 'medium'];
        } else {
            return [gettext('Password strength: strong.'), 'strong'];
        }
    }
    $(nodes).each(function() {
        var $el = $(this),
            $err = $el.next('ul.errorlist');
        if (!$err.length) {
            $err = $('<ul>', {'class':'errorlist'});
            $el.after($err);
        }
        var $count = $('<li>'),
            $strength = $('<li>', {'text':'', 'class':'strength'});
        $err.append($count).append($strength);
        $el.bind('keyup blur', function() {
            var diff = $el.attr('data-min-length') - $el.val().length;
            if (diff > 0) {
                $count.show().text(format(ngettext('At least {0} character left.',
                                                   'At least {0} characters left.', diff), diff));
            } else {
                $count.hide();
            }
            var rating = complexity($el.val());
            $strength.text(rating[0])
                     .removeClass('password-weak password-medium password-strong')
                     .addClass('password-'+rating[1]);
        });
    });
}

$(document).ready(function() {
    var passwords = $('input[type=password].password-strength');
    if (passwords.exists()) {
        initStrength(passwords);
    }
});

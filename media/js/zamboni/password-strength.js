function initStrength(nodes) {
    function complexity(text) {
        var score = 0;
        if (text.length > 7) { score++; }
        if (text.length > 12) { score++; }
        if (text.match(/[0-9]/)) { score++; }
        if (text.match(/[a-z]/) && text.match(/[A-Z]/)) { score++; }
        if (text.match(/[^a-zA-Z0-9]/)) { score++; }
        return score;
    }
    $(nodes).each(function() {
        var $el = $(this),
            $err = $el.next('ul.errorlist');
        if (!$err.length) {
            $err = $('<ul>', {'class':'errorlist'});
            $el.after($err);
        }
        var $count = $('<li>'),
            $strength = $('<li>', {'class':'strength'})
                         .append($('<span>', {'text':gettext('Password strength:')}))
                         .append($('<progress>', {'value':0, 'max':100, 'text':'0%'}));
        $err.append($count).append($strength);
        $el.bind('keyup blur', function() {
            var diff = $el.attr('data-min-length') - $el.val().length;
            if (diff > 0) {
                $count.show().text(format(ngettext('At least {0} character left.',
                                                   'At least {0} characters left.', diff), diff));
            } else {
                $count.hide();
            }
            var val = (complexity($el.val()) / 5) * 100;
            $strength.children('progress').attr('value', val).text(format('{0}%', val));
        });
    });
}

$(document).ready(function() {
    var passwords = $('input[type=password].password-strength');
    if (passwords.exists()) {
        initStrength(passwords);
    }
});

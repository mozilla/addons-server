define('notification', ['capabilities'], function(caps) {

    var notificationEl = $('<div id="notification">');
    z.body.append(notificationEl);

    var addedClasses = [];

    function reset() {
        notificationEl.removeClass(addedClasses.join(' '))
                      .text('');
        addedClasses = [];
        def = $.Deferred();
    }

    function show() {
        notificationEl.addClass('show');
    }

    function hide() {
        notificationEl.removeClass('show');
    }

    function die() {
        def.reject();
        def = false;
        hide();
    }

    function affirm() {
        def.resolve();
        def = false;
        hide();
    }

    var def;

    notificationEl.on('touchstart click', affirm);

    function notification(opts) {

        if (def && def.state() === 'pending') {
            def.reject();
        }

        if (!opts.message) return;

        reset();

        if ('classes' in opts) {
            addedClasses = opts.classes.split(/\s+/);
        }

        if (opts.closable) {
            addedClasses.push('closable');
        }
        if (opts.timeout) {
            setTimeout(die, opts.timeout);
        }

        notificationEl.addClass(addedClasses.join(' '))
                      .text(opts.message);

        notificationEl.addClass('show');

        return def.promise();

    };

    return notification;

});
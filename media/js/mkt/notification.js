define('notification', ['capabilities'], function(caps) {

    var notificationEl = $('<div id="notification">');
    z.body.append(notificationEl);

    var def;
    var addedClasses = [];

    function show() {
        notificationEl.addClass('show');
    }

    function hide() {
        notificationEl.removeClass('show');
    }

    function die() {
        def.reject();
        hide();
    }

    function affirm() {
        def.resolve();
        hide();
    }

    notificationEl.on('touchstart click', affirm);

    function notification(opts) {

        if (def && def.state() === 'pending') {
            def.reject();
        }
        def = $.Deferred();
        notificationEl.removeClass(addedClasses.join(' '))
                      .text('');
        addedClasses = [];

        if (!opts.message) return;

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

/*
    Functions that tests can use.
*/
tests = {};

tests.waitFor = function(checkCondition, config) {
    /*
        Wait for a condition before doing anything else.

        Good for making async tests fast on fast machines.
        Use it like this:

        tests.waitFor(function() {
            return (thing == 'done);
        }).thenDo(function() {
            equals(1,1);
            ok(stuff());
        });

        You can pass in a config object as the second argument
        with these possible attributed:

        config.interval = milliseconds to wait between polling condition
        config.timeout = milliseconds to wait before giving up on condition
    */
    if (typeof(config) === 'undefined') {
        config = {};
    }
    var interval = config.interval || 5,
        timeout = config.timeout || 300,
        run,
        runWhenReady,
        timeSpent = 0;

    run = function() {
        if (timeSpent > timeout) {
            throw new Error("Spent too long waiting for condition");
        }
        timeSpent += interval;
        var ready = checkCondition();
        if (!ready) {
            setTimeout(run, interval);
        } else {
            if (typeof runWhenReady === 'function') {
                runWhenReady();
            }
        }
    };
    setTimeout(run, interval);
    return {
        thenDo: function(fn) {
            runWhenReady = fn;
        }
    }
};

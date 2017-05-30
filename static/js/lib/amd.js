// See https://gist.github.com/4156519

// Minimal AMD support.

// Define a module:
// define('name', ['underscore', 'dep2'], function(_, dep2) {
//     exports = {};
//     ...
//     return exports;
// });

// Require a module explicitly
// var _ = require('underscore');

(function() {

    var defined = {};
    var resolved = {};

    function define(id, deps, module) {

        defined[id] = [deps, module];

    }

    function require(id) {

        if (!resolved[id]) {

            var definition = defined[id];

            if (!definition) {
                throw 'Attempted to resolve undefined module ' + id;
            }

            var deps = definition[0];
            var module = definition[1];

            var rDeps = [];

            for (var i=0; i<deps.length; i++) {
                rDeps.push(require(deps[i]));
            }

            resolved[id] = module.apply(window, rDeps);

        }
        return resolved[id];
    }

    window.require = require;
    window.define = define;

})();

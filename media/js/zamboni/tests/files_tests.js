$(document).ready(function(){
    var fileViewer = {
        setup: function() {
            this.sandbox = tests.createSandbox('#files-wrapper');
        },
        teardown: function() {
            this.sandbox.remove();
        }
    };

    module('File viewer', fileViewer);

    test('Show leaf', function() {
        var nodes = {
            $files: this.sandbox.find($('#files'))
        };
        var viewer = bind_viewer(nodes);
        viewer.toggle_leaf(this.sandbox.find('a.directory'));
        equal(this.sandbox.find('a.directory').hasClass('open'), true);
        equal(this.sandbox.find('ul:hidden').length, 0);
        viewer.toggle_leaf(this.sandbox.find('a.directory'));
        equal(this.sandbox.find('a.directory').hasClass('open'), false);
        equal(this.sandbox.find('ul:hidden').length, 1);
    });
});

$(document).ready(function(){

var transFixture = {
    setup: function() {
        this.sandbox = tests.createSandbox('#l10n-translation');
    },
    teardown: function() {
        this.sandbox.remove();
    }
};

module('z.refreshL10n', transFixture);

test('English', function() {
    z.refreshL10n('en-us');
    equals($('textarea:visible', this.sandbox).text().trim(),
           'Firebug integrates with Firefox to put a wealth of ' +
           'development tools...');
});

test('Japanese', function() {
    z.refreshL10n('ja');
    equals($('textarea:visible', this.sandbox).text().trim(),
           'Firebug は、Web ページを閲覧中にクリック一つで使える豊富な開発ツールを Firefox' +
           ' に統合します。あなたはあらゆる');
});

});

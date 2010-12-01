$(document).ready(function(){

var transFixture = {
    setup: function() {
        $("#qunit-fixture").append($("#l10n-translation").html());
    }
};

module('z.refreshL10n', transFixture);

asyncTest('English', function() {
    tests.waitFor(function() {
        return typeof(z.refreshL10n) !== 'undefined';
    }).thenDo(function() {
        z.refreshL10n('en-us');
        equals($('#qunit-fixture textarea:visible').text().trim(),
               'Firebug integrates with Firefox to put a wealth of ' +
               'development tools...');
        start();
    });
});

asyncTest('Japanese', function() {
    tests.waitFor(function() {
        return typeof(z.refreshL10n) !== 'undefined';
    }).thenDo(function() {
        z.refreshL10n('ja');
        equals($('#qunit-fixture textarea:visible').text().trim(),
               'Firebug は、Web ページを閲覧中にクリック一つで使える豊富な開発ツールを Firefox' +
               ' に統合します。あなたはあらゆる');
        start();
    });
});

});
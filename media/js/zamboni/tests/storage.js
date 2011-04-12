$(document).ready(function() {

    var storageFixture = {
        setup: function() {
            this.s = z.Storage();
            this.s_fruit = z.Storage('fruit');
            this.s_candy = z.Storage('candy');
        }
    };

    module('storage', storageFixture);

    test('Non-namespaced storage', function() {
        this.s.set('a', 'aaa');
        equals(localStorage.getItem('a'), 'aaa');
        equals(this.s.get('a'), 'aaa');

        this.s.remove('a');
        equals(this.s.get('a'), null);
        equals(localStorage.getItem('a'), null);
    });

    test('Namespaced storage', function() {
        this.s_fruit.set('a', 'apple');
        this.s_candy.set('a', 'airheads');
        equals(this.s_fruit.get('a'), 'apple');
        equals(localStorage.getItem('fruit-a'), 'apple');

        this.s_fruit.remove('a');
        equals(this.s_fruit.get('a'), null);
        equals(localStorage.getItem('fruit-a'), null);
        equals(this.s_candy.get('a'), 'airheads');
    });

});

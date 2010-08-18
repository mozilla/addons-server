/* Plugin to create tab interface, loosely based on jquery.ui.tabs. */

/* A Tabs object is a collection of tabs and panels.  A tab is an <a href>
 * pointing to the id of a panel.
 *
 * The element bound to the Tabs object will be given a .tab member by the
 * .tabify() plugin so it can be accessed later.
 */

var Tabs = function(el) {
    this.root = $(el);
    this.init();
};

Tabs.prototype = {
    init: function() {
        this.root.addClass('tab-wrapper');
        this.tabMap = {}
        this.panelMap = {}
        this.reset();

        this.select();

        /* Bind hashchange, trigger event to check for existing hash. */
        var self = this;
        $(document).bind('hashchange', function(e) {
            self.hashChange(e);
        }).trigger('hashchange');
    },

    /* Find and prepare all the tabs and panels.  Can be called multiple times,
     * e.g. to update tabs after insertion/deletion.
     */
    reset: function(o) {
        this.findTabs();
        this.findPanels();
        this.styleTabs(this.tabs);
        this.stylePanels(this.panels);
        return this;
    },

    /* Find tabs (li a[href]) and bind their click event. */
    findTabs: function() {
        this.list = this.root.find('ol,ul').eq(0);
        this.tabs = $('li:has(a[href])', this.list);

        var self = this;
        var cb = function(e) {
            e.preventDefault();
            self.select($(e.target).attr('href'), true);
            $("a", this).blur();
        };
        this.tabs.unbind('click', cb).click(cb);
    },

    /* Get the fragment this tab points to. */
    getHash: function(tab) {
        return $(tab).find('a').attr('href');
    },

    /* Find all the panels to go along with the tabs. */
    findPanels: function() {
        var self = this;
        var panels = [];
        this.tabs.each(function() {
            var hash = self.getHash(this);
            var panel = self.root.find('#' + hash)[0];
            if (panel) {
                self.tabMap[hash] = this;
                self.panelMap[hash] = panel;
                panels.push(panel);
            }
        });
        this.panels = $(panels);
    },

    styleTabs: function(tabs) {
        tabs = tabs || self.tabs;
        this.list.addClass('tab-nav');
        $(tabs).addClass('tab');
    },

    stylePanels: function(panels) {
        panels = panels || self.panels;
        $(panels).addClass('tab-panel');
    },

    /* Focus on the tab pointing to #hash.
     * If hash is not given, the first tab will be selected.
     * If updateHash is true, location.hash will be updated.
     */
    select: function(hash, updateHash) {
        if (typeof hash === 'undefined') {
            if (!this.tabs.filter('.tab-selected').length) {
                return this.select(this.getHash(this.tabs[0]));
            }
        }

        var tab = this.tabMap[hash],
            panel = this.panelMap[hash];

        this.tabs.filter('.tab-selected').removeClass('tab-selected');
        this.panels.filter('.tab-selected').removeClass('tab-selected');
        $([tab, panel]).addClass('tab-selected');

        this.root.trigger('tabselect', {tab: tab, panel: panel});

        if (updateHash) {
            safeHashChange(hash);
        }
    },

    /* Handler for onhashchange. */
    hashChange: function(e) {
        if (location.hash && _.haskey(this.tabMap, location.hash)) {
            e.preventDefault();
            this.select(location.hash);
        }
    }
};


$.fn.tabify = function() {
    this.each(function() {
        this.tab = new Tabs(this);
    });
    return this;
};


/* Change location.hash without scrolling. */
var safeHashChange = function(hash) {
    var el = $(hash);
    el.attr('id', '');
    location.hash = hash;
    el.attr('id', hash.slice(1));
};

/**
 * Initializes pagers on this page after the document has been loaded
 */
YAHOO.util.Event.onDOMReady(function ()
{
	var pagers = YAHOO.util.Dom.getElementsByClassName('pager');
	for (var i = 0; i < pagers.length; i++) {
		new Mozilla.Pager(pagers[i]);
	}
});

// create namespace
if (typeof Mozilla == 'undefined') {
	var Mozilla = {};
}

/**
 * Pager widget
 *
 * @param DOMElement container
 */
Mozilla.Pager = function(container)
{
	this.container = container;

	if (!this.container.id) {
		YAHOO.util.Dom.generateId(this.container, 'mozilla-pager-');
	}

	var pager_content_nodes = YAHOO.util.Dom.getElementsByClassName(
		'pager-content', 'div', this.container);

	this.id             = this.container.id;
	this.page_container = pager_content_nodes[0];
	this.pages_by_id    = {};
	this.pages          = [];
	this.previous_page  = null;
	this.current_page   = null;
	this.in_animation   = null;
	this.out_animation  = null;

	this.random_start_page = (YAHOO.util.Dom.hasClass(this.container, 'pager-random'));

	if (YAHOO.util.Dom.hasClass(this.container, 'pager-with-tabs')) {
		var pager_tab_nodes = YAHOO.util.Dom.getElementsByClassName(
			'pager-tabs', 'ul', this.container);

		this.tabs = pager_tab_nodes[0];
	} else {
		this.tabs = null;
	}

	if (YAHOO.util.Dom.hasClass(this.container, 'pager-with-nav')) {
		this.drawNav();
	} else {
		this.nav = null;
	}

	this.history =
		(!YAHOO.util.Dom.hasClass(this.container, 'pager-no-history'));

	// add pages
	var page_nodes = YAHOO.util.Dom.getChildrenBy(this.page_container,
		function (n) { return (n.nodeName == 'DIV'); });

	if (this.tabs) {
		// initialize pages with tabs
		var tab_nodes = YAHOO.util.Dom.getChildrenBy(this.tabs,
			function (n)
			{
				return (!YAHOO.util.Dom.hasClass(n, 'pager-not-tab'));
			});

		var index = 0;
		for (var i = 0; i < page_nodes.length; i++) {
			if (i < tab_nodes.length) {
				var tab_node = YAHOO.util.Dom.getFirstChildBy(tab_nodes[i],
					function(n) { return (n.nodeName == 'A'); });

				if (tab_node) {
					this.addPage(new Mozilla.Page(page_nodes[i], index,
						tab_node));

					index++;
				}
			}
		}
	} else {
		// initialize pages without tabs
		for (var i = 0; i < page_nodes.length; i++) {
			this.addPage(new Mozilla.Page(page_nodes[i], i));
		}
	}

	// initialize current page
	var current_page = null;
	if (this.history) {
		var hash = location.hash;
		hash = (hash.substring(0, 1) == '#') ? hash.substring(1) : hash;
		if (hash.length) {
			current_page = this.pages_by_id[hash];
			if (current_page) {
				this.setPage(current_page);
			}
		}

		// check if window location changes from back/forward button use
		// this doesn't matter in IE and Opera but is nice for Firefox and
		// recent Safari users.
		function setupInterval(pager)
		{
			var interval_function = function()
			{
				pager.checkLocation();
			}
			setInterval(interval_function,
				(Mozilla.Pager.LOCATION_INTERVAL * 1000), pager);
		}
		setupInterval(this);
	}

	if (!current_page && this.pages.length > 0) {
		if (this.random_start_page) {
			this.setPage(this.getPseudoRandomPage());
		} else {
			var def_page = YAHOO.util.Dom.getFirstChildBy(this.page_container,
				function(n){return YAHOO.util.Dom.hasClass(n, 'default-page')});
			if (def_page) {
				var def_id;
				if (def_page.id.substring(0, 5) == 'page-') {
					def_id = def_page.id.substring(5);
				} else {
					def_id = def_page.id;
				}
				this.setPage(this.pages_by_id[def_id]);
			} else {
				this.setPage(this.pages[0]);
			}
		}
	}
}

Mozilla.Pager.prototype.getPseudoRandomPage = function()
{
	var page = null;

	if (this.pages.length > 0) {
		var now = new Date();
		page = this.pages[now.getSeconds() % this.pages.length];
	}

	return page;
}

Mozilla.Pager.PAGE_DURATION     = 0.15; // seconds
Mozilla.Pager.LOCATION_INTERVAL = 0.20; // seconds
Mozilla.Pager.NEXT_TEXT         = 'Next';
Mozilla.Pager.PREV_TEXT         = 'Previous';
Mozilla.Pager.PAGE_NUMBER_TEXT  = '%s / %s';

Mozilla.Pager.prototype.prevPageWithAnimation = function()
{
	var index = this.current_page.index - 1;
	if (index < 0) {
		index = this.pages.length - 1;
	}

	this.setPageWithAnimation(this.pages[index]);
}

Mozilla.Pager.prototype.nextPageWithAnimation = function()
{
	var index = this.current_page.index + 1;
	if (index >= this.pages.length) {
		index = 0;
	}

	this.setPageWithAnimation(this.pages[index]);
}

Mozilla.Pager.prototype.drawNav = function()
{
	// create previous link
	this.prev = document.createElement('a');
	this.prev.href = '#';
	YAHOO.util.Dom.addClass(this.prev, 'pager-prev');
	this.prev.title = Mozilla.Pager.PREV_TEXT;
	this.prev.appendChild(document.createTextNode(''));

	this.prev_insensitive = document.createElement('span');
	this.prev_insensitive.style.display = 'none';
	YAHOO.util.Dom.addClass(this.prev_insensitive, 'pager-prev-insensitive');

	YAHOO.util.Event.on(this.prev, 'click',
		function (e)
		{
			YAHOO.util.Event.preventDefault(e);
			this.prevPageWithAnimation();
		},
		this, true);

	YAHOO.util.Event.on(this.prev, 'dblclick',
		function (e)
		{
			YAHOO.util.Event.preventDefault(e);
		},
		this, true);

	// create next link
	this.next = document.createElement('a');
	this.next.href = '#';
	YAHOO.util.Dom.addClass(this.next, 'pager-next');
	this.next.title = Mozilla.Pager.NEXT_TEXT;
	this.next.appendChild(document.createTextNode(''));

	this.next_insensitive = document.createElement('span');
	this.next_insensitive.style.display = 'none';
	YAHOO.util.Dom.addClass(this.next_insensitive, 'pager-next-insensitive');

	YAHOO.util.Event.on(this.next, 'click',
		function (e)
		{
			YAHOO.util.Event.preventDefault(e);
			this.nextPageWithAnimation();
		},
		this, true);

	YAHOO.util.Event.on(this.next, 'dblclick',
		function (e)
		{
			YAHOO.util.Event.preventDefault(e);
		},
		this, true);

	// create navigation element
	var divider = document.createElement('span');
	divider.appendChild(document.createTextNode('|'));
	YAHOO.util.Dom.addClass(divider, 'pager-nav-divider');

	this.page_number = document.createElement('span');
	YAHOO.util.Dom.addClass(this.page_number, 'pager-nav-page-number');

	this.nav = document.createElement('div');
	YAHOO.util.Dom.addClass(this.nav, 'pager-nav');
	this.nav.appendChild(this.page_number);
	this.nav.appendChild(this.prev_insensitive);
	this.nav.appendChild(this.prev);
	this.nav.appendChild(divider);
	this.nav.appendChild(this.next);
	this.nav.appendChild(this.next_insensitive);

	this.container.insertBefore(this.nav, this.page_container);
}

Mozilla.Pager.prototype.checkLocation = function()
{
	var hash = location.hash;
	hash = (hash.substring(0, 1) == '#') ? hash.substring(1) : hash;
	var current_hash = this.current_page.id;

	if (hash && hash !== current_hash) {
		var page = this.pages_by_id[hash];
		if (page) {
			this.setPageWithAnimation(page);
			this.current_page.focusTab(); // for accessibility
		}
	}
}

Mozilla.Pager.prototype.addPage = function(page)
{
	this.pages_by_id[page.id] = page;
	this.pages.push(page);
	if (page.tab) {
		YAHOO.util.Event.on(page.tab, 'click',
			function (e)
			{
				YAHOO.util.Event.preventDefault(e);
				this.setPageWithAnimation(page);
			},
			this, true);
	}
}

Mozilla.Pager.prototype.update = function()
{
	if (this.tabs) {
		this.updateTabs();
	}

	if (this.nav) {
		this.updateNav();
	}
}

Mozilla.Pager.prototype.updateTabs = function()
{
	var class_name = this.tabs.className;
	class_name = class_name.replace(/pager-selected-[\w-]+/g, '');
	class_name = class_name.replace(/^\s+|\s+$/g,'');
	this.tabs.className = class_name;

	this.current_page.selectTab();
	YAHOO.util.Dom.addClass(this.tabs,
		'pager-selected-' + this.current_page.id);
}

Mozilla.Pager.prototype.updateNav = function()
{
	// update page number
	var page_number = this.current_page.index + 1;
	var page_count  = this.pages.length;

	var text = Mozilla.Pager.PAGE_NUMBER_TEXT.replace(/%s/, page_number);
	text     = text.replace(/%s/, page_count);

	if (this.page_number.firstChild) {
		this.page_number.replaceChild(document.createTextNode(text),
			this.page_number.firstChild);
	} else {
		this.page_number.appendChild(document.createTextNode(text));
	}

	// update previous link
	this.setPrevSensitivity(this.current_page.index != 0);

	// update next link
	this.setNextSensitivity(this.current_page.index != this.pages.length - 1);
}

Mozilla.Pager.prototype.setPrevSensitivity = function(sensitive)
{
	if (sensitive) {
		this.prev_insensitive.style.display = 'none';
		this.prev.style.display = 'inline';

	} else {
		this.prev_insensitive.style.display = 'inline';
		this.prev.style.display = 'none';
	}
}

Mozilla.Pager.prototype.setNextSensitivity = function(sensitive)
{
	if (sensitive) {
		this.next_insensitive.style.display = 'none';
		this.next.style.display = 'inline';

	} else {
		this.next_insensitive.style.display = 'inline';
		this.next.style.display = 'none';
	}
}

Mozilla.Pager.prototype.setPage = function(page)
{
	if (this.current_page !== page) {
		if (this.current_page) {
			this.current_page.deselectTab();
			this.current_page.hide();
		}

		if (this.previous_page) {
			this.previous_page.hide();
		}

		this.previous_page = this.current_page;

		this.current_page = page;
		this.current_page.show();
		this.update();
	}
}

Mozilla.Pager.prototype.setPageWithAnimation = function(page)
{
	if (this.current_page !== page) {

		if (this.history) {
			// set address bar to current page
			var base_location = location.href.split('#')[0];
			location.href = base_location + '#' + page.id;
		}

		// deselect last selected page (not necessarily previous page)
		if (this.current_page) {
			this.current_page.deselectTab();
		}

		// start opacity at current opacity if page was changed while another
		// page was fading in
		if (this.in_animation && this.in_animation.isAnimated()) {
			var start_opacity = parseFloat(YAHOO.util.Dom.getStyle(
				this.page_container, 'opacity'));

			this.in_animation.stop(false);
		} else {
			var start_opacity = 1.0;
		}

		// fade out if we're not already fading out
		if (!this.out_animation || !this.out_animation.isAnimated()) {
			// only set previous page if we are not already fading out
			this.previous_page = this.current_page;

			this.out_animation = new YAHOO.util.Anim(this.page_container,
				{ opacity: { from: start_opacity, to: 0 } },
				Mozilla.Pager.PAGE_DURATION, YAHOO.util.Easing.easeOut);

			this.out_animation.onComplete.subscribe(this.fadeInPage,
				this, true);

			this.out_animation.animate();
		}

		// always set current page
		this.current_page = page;
		this.update();
	}

	// for Safari 1.5.x bug setting window.location.
	return false;
}

Mozilla.Pager.prototype.fadeInPage = function()
{
	if (this.previous_page) {
		this.previous_page.hide();
	}

	this.current_page.show();

	this.in_animation = new YAHOO.util.Anim(this.page_container,
		{ opacity: { from: 0, to: 1 } }, Mozilla.Pager.PAGE_DURATION,
		YAHOO.util.Easing.easeIn);

	this.in_animation.animate();
}

/**
 * Page in a pager
 *
 * @param DOMElement element
 * @param DOMElement tab_element
 */
Mozilla.Page = function(element, index, tab_element)
{
	this.element = element;

	if (!this.element.id) {
		YAHOO.util.Dom.generateId(this.element, 'mozilla-pager-page-');
	}

	// Change element id so updating the window.location does not navigate to
	// the page. This is mostly for IE.
	if (this.element.id.substring(0, 5) == 'page-') {
		this.id = this.element.id.substring(5);
	} else {
		this.id = this.element.id;
	}

	this.element.id = 'page-' + this.id;
	this.index      = index;

	if (tab_element) {
		this.tab = tab_element;
		this.tab.href = '#' + this.id;
	} else {
		this.tab = null;
	}

	this.hide();
}

Mozilla.Page.prototype.selectTab = function()
{
	if (this.tab) {
		YAHOO.util.Dom.addClass(this.tab, 'selected');
	}
}

Mozilla.Page.prototype.deselectTab = function()
{
	if (this.tab) {
		YAHOO.util.Dom.removeClass(this.tab, 'selected');
	}
}

Mozilla.Page.prototype.focusTab = function()
{
	if (this.tab) {
		this.tab.focus();
	}
}

Mozilla.Page.prototype.hide = function()
{
	this.element.style.display = 'none';
}

Mozilla.Page.prototype.show = function()
{
	this.element.style.display = 'block';
}

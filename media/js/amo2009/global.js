(function($) {
	window.Slideshow = function() {
		this.itemTotal = 0;
		this.currentItem = 1;
		this.itemWidth = 0;

		//  Set these properties when you instantiate an instance of this object.
		this.speed = 300; // the speed in milliseconds of the animation

		this.itemContainer = ''; // the selector for the element containing the items.
        this.wrapperElement = ''; // the tagName that will wrap the itemContainer.
		this.wrapperClass = ''; //the classname of the element that will wrap the itemContainer.
		this.controlsMarkup = ''; // the markup for the controls.
		this.leftController = ''; // the selector for the left controller.
		this.rightContorller = ''; // the selector for the right controller.
		this.activeClass = '';  // the classname to indicate that a controller is active.
		this.container = ''; //the complete container for all of the slideshow
		this.interval = null;
		this.scroll = true;
	};
	Slideshow.prototype.init = function() {
		this.itemTotal = parseInt($(this.itemContainer+'>li').length,10);
		if (this.itemTotal <= 1) {
			return;
		}

		$(this.itemContainer).wrap('<'+this.wrapperElement+' class="'+this.wrapperClass+'"></'+this.wrapperElement+'>');
		this.itemWidth = this.getItemWidth();
		// applying controls to 2nd parent rather than 1st fixes stacking context issue in FF2
		$($(this.itemContainer).parents()[1]).append(this.controlsMarkup);
		$(this.itemContainer+'>li').width(this.itemWidth+'px');

		this.checkControls();

		var self = this;
		$(self.leftController).live('click', function() {
			if ($(this).hasClass(self.activeClass)) {
				self.moveToItem(self.currentItem-1);
			}
			self.scroll = false;
			return false;
		});

		$(self.rightController).live('click', function() {
			if ($(this).hasClass(self.activeClass)) {
				self.moveToItem(self.currentItem+1);
			}
			self.scroll = false;
			return false;
		});

        $(self.container).mouseenter(function() {
            clearInterval(self.interval);
        });

        $(self.container).bind('newPopup', function() {
            clearInterval(self.interval);
        });

        $(self.container).mouseleave(function() {
            self.autoRotate();
        });

        self.autoRotate();

		$(window).resize(function() {
			self.itemWidth = self.getItemWidth();
			$(self.itemContainer+'>li').width(self.itemWidth+'px');
			self.popToItem(self.currentItem);
		});
	};

	Slideshow.prototype.autoRotate = function() {
	    if(this.scroll) {
	        var that = this; //closure due to setInterval's 'this' refers to window, not the current 'this'
            clearInterval(this.interval);
    	    this.interval = setInterval(function() {
    	        if(that.currentItem != that.itemTotal) {
                    that.moveToItem(that.currentItem+1);
                } else {
                    that.moveToItem(1);
                }
    	    }, 8000);
	    }
	};

	Slideshow.prototype.getItemWidth = function() {
		return $(this.itemContainer).parents('.'+this.wrapperClass).width();
	};
	Slideshow.prototype.popToItem = function(itemNumber) {
		if (!$(this.itemContainer).parents('.'+this.wrapperClass+' :animated').length) {
			$($(this.itemContainer).children("li").get(this.currentItem-1)).hide();
			$($(this.itemContainer).children("li").get(itemNumber-1)).show();
			this.currentItem = itemNumber;
			this.checkControls();
		}
	};
	Slideshow.prototype.moveToItem = function(itemNumber) {
		if (!$(this.itemContainer).parents('.'+this.wrapperClass+' :animated').length) {
			var lis = $(this.itemContainer).children("li");
			$(lis.get(this.currentItem-1)).fadeOut("fast", function () {
				$(lis.get(itemNumber-1)).fadeIn("fast");
			});
			this.currentItem = itemNumber;
			this.checkControls();
		}
	};
	Slideshow.prototype.checkControls = function() {
		if (this.currentItem == 1) {
			$(this.leftController).removeClass(this.activeClass);
		} else {
			$(this.leftController).addClass(this.activeClass);
		}
		if (this.currentItem == this.itemTotal) {
			$(this.rightController).removeClass(this.activeClass);
		} else {
			$(this.rightController).addClass(this.activeClass);
		}
	};

	// slidey dropdown area
	window.DropdownArea = function() {
		this.trigger = null;
		this.target = '';
		this.targetParent = '';
		this.callbackFunction = function(){};
		this.preventDefault = true;
		this.showSpeed = 200;
		this.hideSpeed = 200;
		this.hideOnBodyClick = true;
	};
	DropdownArea.prototype.bodyclick = function(e) {
		// this will get fired on click of body, we need to close the dropdown
		if (this.bodyWatching && this.hideOnBodyClick) {
			if (!
				($(e.target).get(0) == $(this.targetParent).get(0) ||
				 $(e.target).parents(this.targetParent).length)
			) {
			    this.hide();
			}

		}
	}
	DropdownArea.prototype.hide = function() {
		var self = this;
		$(self.targetParent).removeClass('expanded');
		$(self.target).slideUp(self.hideSpeed, function() {
    		//unbind bodyclick
    		self.bodyWatching = false;
		});
	}
	DropdownArea.prototype.show = function() {
		var self = this;
		$(self.targetParent).addClass('expanded');
		$(self.target).slideDown(self.showSpeed, function() {
			self.bodyWatching = true;
		});
	}
	DropdownArea.prototype.init = function() {
    // advanced dropdown
    var self = this;
    $(this.target).hide();
    if (this.trigger) {
     this.trigger.click(
       function(e) {
         if(! $(self.target+':animated').length) {
           if ($(self.target+':visible').length){
               self.callbackFunction();
               self.hide();
           } else {
             self.callbackFunction();
             self.show();
           }
         }
         $(self.target).trigger('click');
         return !self.preventDefault;
       }
     );
     // if box now showing bind bodyclick
     $('body').bind("click", function(e) {
       self.bodyclick(e);
     });
    }
	};

	// A special slideshow that updates the teaser 'selected' list item
    window.AmoSlideshow = function() {
        /* This is a convenience function that performs all the slideshow
         * setup we shouldn't have to think about if the slideshow code
         * was written with an eye for abstraction and reusability.
         * First one to refactor it gets a cookie.
         */
        function HeaderSlideshow() {
            if($('.teaser-items').hasClass('no-autorotate')) {
                Slideshow.prototype.autoRotate = function(){}
            }
            Slideshow.call(this);
        }
        HeaderSlideshow.prototype = new Slideshow();
        HeaderSlideshow.prototype.moveToItem = function(itemNumber) {
            Slideshow.prototype.moveToItem.call(this, itemNumber);
            $('.section-teaser .teaser-header li').removeClass('selected');
            $('.section-teaser .teaser-header li').eq(itemNumber - 1).addClass('selected');
        };

        var homepageSlider = new HeaderSlideshow();
        homepageSlider.itemContainer = '.teaser-items';
        homepageSlider.wrapperElement = 'div';
        homepageSlider.wrapperClass = 'window';
        homepageSlider.controlsMarkup = (
            '<p class="slideshow-controls">' +
            '<a href="#" class="prev" rel="prev">Previous</a>' +
            '<a href="#" class="next" rel="next">Next</a></p>'
        );
        homepageSlider.leftController = '.section-teaser a[rel="prev"]';
        homepageSlider.rightController = '.section-teaser a[rel="next"]';
        homepageSlider.activeClass = 'active';
        homepageSlider.container = '.section-teaser .featured-inner';
        homepageSlider.init();

        //Move the list of promo categories below the controls to allow all content to expand
        $('.teaser-header').insertBefore(".slideshow-controls");

        var headerListItems = $('.section-teaser .teaser-header li a');

        headerListItems.click(function() {
            headerListItems.parent('li').removeClass('selected');
            $(this).parent('li').addClass('selected');
            homepageSlider.moveToItem(headerListItems.index(this) + 1);
            homepageSlider.scroll = false;
            return false;
        });

        return homepageSlider;
    };

})(jQuery);

jQuery(function($) {
	// Greys out the favorites icon when it is clicked
    $(".item-info li.favorite").click(function () {
	  var self = this;
	  $(self).addClass("favorite-loading");
	  setTimeout(function() {
	    $(self).addClass("favorite-added");
	  },2000);
    });

    // Replaces rating selectboxes with the rating widget
    $("select[name='rating']").each(function(n, el) {
        var $el = $(el),
            $widget = $("<span class='ratingwidget stars stars-0'></span>"),
            rs = [],
            showStars = function(n) {
                $widget.removeClass('stars-0 stars-1 stars-2 stars-3 stars-4 stars-5').addClass('stars-' + n);
            };
        for (var i=1; i<=5; i++) {
            rs.push("<label data-stars='", i, "'>",
                    format(ngettext('{0} star', '{0} stars', i), [i]),
                    "<input type='radio' name='rating' value='", i, "'></label>");
        }
        var rating = 0;
        $widget.click(function(evt) {
            var t = $(evt.target);
            if (t.val()) {
                showStars(t.val());
            }
            rating = t.val();
        });
        $widget.mouseover(function(evt) {
            var t = $(evt.target);
            if (t.attr('data-stars')) {
                showStars(t.attr('data-stars'));
            }
        });
        $widget.mouseout(function(evt) {
            showStars(rating);
        });
        $widget.html(rs.join(''));
        $el.before($widget);
        $el.detach();
    });

	// Categories dropdown only on pages where it is not in secondary
	if($('#categories').parents('.secondary').length == 0) {
		var categories = new DropdownArea();
		// add class to style differently
		$('#categories').addClass('dropdown-categories');

		// set up images for dropdown
        var categoryContainer = $('#categories :first-child')[0];
        if (categoryContainer) {
            var clickableCategories = $(categoryContainer);
            clickableCategories.prepend('<img src="/img/amo2009/icons/category-dropdown-down.gif" alt="" /> ');

            // stop the accidental selection during double click
            clickableCategories.each(function(){
                this.onselectstart = function () { return false; }
                this.onmousedown = function () { return false; }
            });

            // set up variables for object
            categories.trigger = clickableCategories; // node
            categories.target = '#categories>ul'; // reference
            categories.targetParent = '#categories'; // reference
            categories.callbackFunction = function() {
                if($('#categories>ul:visible').length){
                    $('#categories img').attr('src', '/img/amo2009/icons/category-dropdown-down.gif');
                } else {
                    $('#categories img').attr('src', '/img/amo2009/icons/category-dropdown-up.gif');
                }
            };

            // initialise dropdown area
            categories.init();
        }
	} else {
        // Turn the link into a span so it's not deceptively clickable.
        var e = $('#categories h3');
        e.html('<span>' + e.text() + '</span>');
    }


	// advanced form dropdown
	var advancedForm = new DropdownArea();
	// set up variables for object
	advancedForm.trigger = ($('#advanced-link a')); // node
	advancedForm.target = ('.advanced'); // reference
	advancedForm.targetParent = ('.search-form'); // reference
	advancedForm.hideOnBodyClick = false;
    advancedForm.callbackFunction = function() {
        // TODO(jbalogh): advanced is only in zamboni; this should all move to
        // the search init when remora dies.
        // This gets called *before* the hide toggle, so logic is backwards.
        var val = $(this.targetParent).hasClass('expanded') ? 'off' : 'on';
        $(this.target).find('[name=advanced]').val(val);
    };
	advancedForm.init();

	// account dropdown in auxillary menu
	var accountDropdown = new DropdownArea();
	// set up variables for object
	accountDropdown.trigger = ($('ul.account .controller')); // node
	accountDropdown.target = ('ul.account ul'); // reference
	accountDropdown.targetParent = ('ul.account'); // reference
	accountDropdown.init();

	// tools dropdown in auxillary menu
	var toolsDropdown = new DropdownArea();
	// set up variables for object
	toolsDropdown.trigger = ($('ul.tools .controller')); // node
	toolsDropdown.target = ('ul.tools ul'); // reference
	toolsDropdown.targetParent = ('ul.tools'); // reference
	toolsDropdown.init();

	// change dropdown in auxillary menu
	var changeDropdown = new DropdownArea();
	// set up variables for object
	changeDropdown.trigger = ($('ul.change .controller')); // node
	changeDropdown.target = ('ul.change ul'); // reference
	changeDropdown.targetParent = ('ul.change'); // reference
	changeDropdown.init();

	// notification dropdown
	var notificationHelpDropdown = new DropdownArea();
	// set up variables for object
	notificationHelpDropdown.trigger = ($('.notification .toggle-help')); // node
	notificationHelpDropdown.target = ('.notification .toggle-info'); // reference
	notificationHelpDropdown.targetParent = ('.notification'); // reference
	notificationHelpDropdown.init();
	$('.notification a.close').click(function() {
		notificationHelpDropdown.hide();
		return false;
	})

	contributions.init();

	// listing where interaction is inline
	$('.home .listing div:first').addClass('interactive');

	function tabClickFactory(className) {
		return function(){
			$(this).parents('ul').find('li').removeClass('selected');
			$($(this).parents('li')[0]).addClass('selected');
			$(this).parents('.listing').attr('class','featured listing');
			$(this).parents('.listing').addClass(className);
			return false;
		}
	}
	$(".home a[href^='#recommended']").click(tabClickFactory('show-recommended'));
	$(".home a[href^='#popular']").click(tabClickFactory('show-popular'));
	$(".home a[href^='#added']").click(tabClickFactory('show-added'));
	$(".home a[href^='#updated']").click(tabClickFactory('show-updated'));
});

// Submit on locale choice
jQuery(function($) {
  var f = $('form.languages');
  f.find('input').change(function(){ this.form.submit(); });
});

jQuery(window).load(function() {
	// Crazyweird fix lets us style abbr using CSS in IE
	// - do NOT run onDomReady, must be onload
	document.createElement('abbr');
});

/* Initialization things that get run on every page. */

$(".hidden").hide(); // hide anything that should be hidden

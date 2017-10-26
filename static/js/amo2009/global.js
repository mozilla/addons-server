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

        $(self.container).on('newPopup', function() {
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
     $('body').on("click", function(e) {
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
});

/* Initialization things that get run on every page. */

$(".hidden").hide(); // hide anything that should be hidden

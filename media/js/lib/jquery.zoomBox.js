/*!
	* jQuery Zoombox: https://github.com/technicolorenvy/jquery-zoombox
	*
	* Dependencies:
	* jQuery 1.4+ (jquery.com)
	*
*/

(function($){
	
	var ver = '1.2',
		
		ID_PRE = "#zoombox-container",
		TRIG_CLASS = "zoombox-trigger",
		CONT_CLASS = "zoombox-container",
		CONT_CLOSER = "zoombox-close",
		E_SPACE = ".zbxEvents",
		OPTS = 'zbxOptions',
		STATE = 'zbxState',
		TARGET = 'zbxTarget',
		CALCS = 'zoomboxCalcs',
		
	methods = {
		init: function(options){
			return this.each(function(){
				var $trigger = $(this),
					params = $.extend({}, $.fn.zoombox.defaults, options);
					
				$trigger
					.addClass(TRIG_CLASS)
					.data(OPTS, params)
					.data(STATE, 0)
					.data(TARGET, ID_PRE+'-'+Math.floor(Math.random()*10000)+Math.floor(Math.random()*100));
				
				_binds(params, $trigger);
			});
		},
		open: function(){
			return this.each(function(){
				var $trigger = $(this);
				if($trigger.data(STATE) !== 1){ $trigger.click(); }
			});
		},
		close: function(){
			return this.each(function(){
				var $trigger = $(this);
				if($trigger.data(STATE) !== 0){ $trigger.click(); }
			});
		},
		destroy: function(){
			var $zbContainer = arguments[1] ? $(arguments[1]) : $(ID_PRE);
			return this.each(function(index){
				var $trigger = $(this),
					params = $trigger.data(OPTS);
					
				if(index === 0){
					_unBinds($trigger);
					$trigger.removeClass(TRIG_CLASS).data(OPTS, {});
					$zbContainer.remove();
				}
			});
		}
	};
	
	function _binds(params, $trigger){
		
		$trigger.bind('click'+E_SPACE, function(e){
			e.preventDefault();
			if($trigger.data(STATE) === 0){
				_zoomOpen($trigger, e);
			} else {
				_zoomClose($trigger, e);
			}
		});
		
		if(params.closeBtn === true){
			$($trigger.data(TARGET)+' .'+CONT_CLOSER).live('click'+E_SPACE, function(e){
				e.preventDefault();
				if($trigger.data(STATE) !== 0){ $trigger.click(); }	
			});
		}
		
		if(params.closeWhenEsc === true){
			$(window).bind('keyup'+E_SPACE, function(e){
				if(e.which == 27){
					if($trigger.data(STATE) !== 0){ $trigger.click(); }
				}
			});
		}
	}
	
	function _winBind(e){
		$(window).unbind('click'+E_SPACE, _winBind);
		
		$('.'+TRIG_CLASS).each(function(){
			if($(this).data(STATE) === 1){ $(this).click(); }
		});
	}
	
	function _unBinds($trigger){
		$trigger.unbind(E_SPACE);
		$('.'+CONT_CLOSER).unbind(E_SPACE);
		$(window).unbind(E_SPACE);
	}
	
	function _zoomOpen($trigger, e){
		if($trigger.data(STATE) === 0){
			$trigger.data(STATE, 1);
			
			var params = $trigger.data(OPTS),
				calcs = _returnZoomcalcs(params, $trigger, e),
				$container = $('<div/>').attr('id', _deClassify($trigger.data(TARGET)))
										.attr('class', CONT_CLASS)
										.css(params.containerCSSMap);
			
			if(params.closeBtn === true) {
				$container.append('<a class="'+CONT_CLOSER+'" style="display: none;"/>');
			}
			
			$(params.containerParent).append($container);
			$($trigger.data(TARGET)).css(calcs.startmap);

			if(params.preOpen != null){ params.preOpen(e); }
			
			$($trigger.data(TARGET))
				.css('opacity', '1')
				.animate(calcs.animapGrow, 
					params.speed, 
					params.easing, 
					function(){
						if(params.closeBtn === true) { $($trigger.data(TARGET)+' .'+CONT_CLOSER).fadeIn(); }
						if(params.closeIfNotSelf === true){ $(window).bind('click'+E_SPACE, _winBind); }
						if(params.onOpened !== null) { params.onOpened(e); }
					});
		}
	}
	
	function _zoomClose($trigger, e){
		if($trigger.data(STATE) === 1){
			$trigger.data(STATE, 0);
			
			var params = $trigger.data(OPTS),
				calcs = _returnZoomcalcs(params, $trigger);
			
			function _animate(){
				if(params.preClose != null){ params.preClose(e); }
				$($trigger.data(TARGET))
					.animate(calcs.animapShrink, 
						params.speed, 
						params.easing, 
						function(){
							$($trigger.data(TARGET)).remove();
							$trigger.removeData(CALCS);
							if(params.onClosed !== null) { params.onClosed(e); }
						});
			}	
				
			if(params.closeBtn === true) {
				$($trigger.data(TARGET)+' .'+CONT_CLOSER).fadeOut('fast', function(){
					_animate();
				});
			} else {
				_animate();
			}
		}

	}
	
	function _returnZoomcalcs(params, $trigger){
		var origin = {},
			calcs = {},
			animapLeft,
			animapTop,
			e = (arguments[2] !== undefined) ? arguments[2] : undefined;
			
		if($trigger.data(CALCS) === undefined) {
			
			if(params.growFromMouse === true) { origin.x = e.pageX; origin.y = e.pageY; }
			else if (params.growTagAttr !== undefined){
				var attrArr = $(e.currentTarget).attr(params.growTagAttr).split(', ');
				origin.x = attrArr[0]; 
				origin.y = attrArr[1];
			} 
			else if (e !== undefined){ 
				var offset = $(e.currentTarget).position();
				origin.x = offset.left; 
				origin.y = offset.top;
			}
			
			animapLeft = (params.targetPosX !== undefined) ? params.targetPosX : origin.x - parseInt(params.targetWidth / 2, 10);
			animapTop = (params.targetPosY !== undefined) ? params.targetPosY : origin.y - parseInt(params.targetHeight / 2, 10);
			
			calcs.startmap = {left: origin.x+'px', top: origin.y+'px'};
			calcs.animapGrow = {left: animapLeft+'px', width: params.targetWidth, top: animapTop+'px', height: params.targetHeight};
			calcs.animapShrink = {left: origin.x+'px', width: '1px', top: origin.y+'px', height: '1px'};
			
			$trigger.data(CALCS, calcs);
			
		} else {
			calcs = $trigger.data(CALCS);
		}
		
		return calcs;
	}
	
	function _deClassify(str){
		if(str.indexOf('#') == 0 || str.indexOf('.') == 0){
			return str.slice(1);
		} else {
			return str;
		}
	}
	
	$.fn.zoombox = function(method) {
		if (methods[method]) {
			return methods[method].apply(this, Array.prototype.slice.call(arguments, 1));
		} else if (typeof method === 'object' || !method) {
			return methods.init.apply(this, arguments);
		} else {
			$.error( 'Method ' + method + ' does not exist on jquery.zoombox' );
		}
	};
	
	$.fn.zoombox.ver = function() { return ver; };
	
	$.fn.zoombox.defaults = {
		containerCSSMap:	{opacity: '0', width: '1px', height: '1px', position: 'absolute'},
		containerParent:	'body',
		closeBtn: 			true,
		closeWhenEsc:		true,
		closeIfNotSelf:		false,
		easing:				'swing',
		growFromMouse:		false,
		growTagAttr:		undefined,
		onClosed:			null,
		onOpened:			null,
		preOpen: 			null,
		preClose: 			null,
		speed:				'fast',
		targetHeight:		'200',
		targetWidth:		'200',
		targetPosX: 		undefined,
		targetPosY: 		undefined
	};

})(jQuery);

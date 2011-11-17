/*
 * popcorn.js version 1.0
 * http://popcornjs.org
 *
 * Copyright 2011, Mozilla Foundation
 * Licensed under the MIT license
 */

(function(global, document) {

  // Popcorn.js does not support archaic browsers
  if ( !document.addEventListener ) {
    global.Popcorn = {
      isSupported: false
    };

    var methods = ( "forEach extend effects error guid sizeOf isArray nop position disable enable destroy " +
          "addTrackEvent removeTrackEvent getTrackEvents getTrackEvent getLastTrackEventId " +
          "timeUpdate plugin removePlugin compose effect parser xhr getJSONP getScript" ).split(/\s+/);

    while ( methods.length ) {
      global.Popcorn[ methods.shift() ] = function() {};
    }
    return;
  }

  var

  AP = Array.prototype,
  OP = Object.prototype,

  forEach = AP.forEach,
  slice = AP.slice,
  hasOwn = OP.hasOwnProperty,
  toString = OP.toString,

  // Copy global Popcorn (may not exist)
  _Popcorn = global.Popcorn,

  //  ID string matching
  rIdExp  = /^(#([\w\-\_\.]+))$/,

  //  Ready fn cache
  readyStack = [],
  readyBound = false,
  readyFired = false,

  //  Non-public internal data object
  internal = {
    events: {
      hash: {},
      apis: {}
    }
  },

  //  Non-public `requestAnimFrame`
  //  http://paulirish.com/2011/requestanimationframe-for-smart-animating/
  requestAnimFrame = (function(){
    return global.requestAnimationFrame ||
      global.webkitRequestAnimationFrame ||
      global.mozRequestAnimationFrame ||
      global.oRequestAnimationFrame ||
      global.msRequestAnimationFrame ||
      function( callback, element ) {
        global.setTimeout( callback, 16 );
      };
  }()),

  refresh = function( obj ) {
    var currentTime = obj.media.currentTime,
      animation = obj.options.frameAnimation,
      disabled = obj.data.disabled,
      tracks = obj.data.trackEvents,
      animating = tracks.animating,
      start = tracks.startIndex,
      registryByName = Popcorn.registryByName,
      animIndex = 0,
      byStart, natives, type;

    start = Math.min( start + 1, tracks.byStart.length - 2 );

    while ( start > 0 && tracks.byStart[ start ] ) {

      byStart = tracks.byStart[ start ];
      natives = byStart._natives;
      type = natives && natives.type;

      if ( !natives ||
          ( !!registryByName[ type ] || !!obj[ type ] ) ) {

        if ( ( byStart.start <= currentTime && byStart.end > currentTime ) &&
                disabled.indexOf( type ) === -1 ) {

          if ( !byStart._running ) {
            byStart._running = true;
            natives.start.call( obj, null, byStart );

            // if the 'frameAnimation' option is used,
            // push the current byStart object into the `animating` cue
            if ( animation &&
                ( byStart && byStart._running && byStart.natives.frame ) ) {

              natives.frame.call( obj, null, byStart, currentTime );
            }
          }
        } else if ( byStart._running === true ) {

          byStart._running = false;
          natives.end.call( obj, null, byStart );

          if ( animation && byStart._natives.frame ) {
            animIndex = animating.indexOf( byStart );
            if ( animIndex >= 0 ) {
              animating.splice( animIndex, 1 );
            }
          }
        }
      }

      start--;
    }
  },

  //  Declare constructor
  //  Returns an instance object.
  Popcorn = function( entity, options ) {
    //  Return new Popcorn object
    return new Popcorn.p.init( entity, options || null );
  };

  //  Popcorn API version, automatically inserted via build system.
  Popcorn.version = "1.0";

  //  Boolean flag allowing a client to determine if Popcorn can be supported
  Popcorn.isSupported = true;

  //  Instance caching
  Popcorn.instances = [];

  //  Declare a shortcut (Popcorn.p) to and a definition of
  //  the new prototype for our Popcorn constructor
  Popcorn.p = Popcorn.prototype = {

    init: function( entity, options ) {

      var matches;

      //  Supports Popcorn(function () { /../ })
      //  Originally proposed by Daniel Brooks

      if ( typeof entity === "function" ) {

        //  If document ready has already fired
        if ( document.readyState === "interactive" || document.readyState === "complete" ) {

          entity( document, Popcorn );

          return;
        }
        //  Add `entity` fn to ready stack
        readyStack.push( entity );

        //  This process should happen once per page load
        if ( !readyBound ) {

          //  set readyBound flag
          readyBound = true;

          var DOMContentLoaded  = function() {

            readyFired = true;

            //  Remove global DOM ready listener
            document.removeEventListener( "DOMContentLoaded", DOMContentLoaded, false );

            //  Execute all ready function in the stack
            for ( var i = 0, readyStackLength = readyStack.length; i < readyStackLength; i++ ) {

              readyStack[ i ].call( document, Popcorn );

            }
            //  GC readyStack
            readyStack = null;
          };

          //  Register global DOM ready listener
          document.addEventListener( "DOMContentLoaded", DOMContentLoaded, false );
        }

        return;
      }

      //  Check if entity is a valid string id
      matches = rIdExp.exec( entity );

      //  Get media element by id or object reference
      this.media = matches && matches.length && matches[ 2 ] ?
                     document.getElementById( matches[ 2 ] ) :
                     entity;

      //  Create an audio or video element property reference
      this[ ( this.media.nodeName && this.media.nodeName.toLowerCase() ) || "video" ] = this.media;

      //  Register new instance
      Popcorn.instances.push( this );

      this.options = options || {};

      this.isDestroyed = false;

      this.data = {

        // Executed by either timeupdate event or in rAF loop
        timeUpdate: Popcorn.nop,

        // Allows disabling a plugin per instance
        disabled: [],

        // Stores DOM event queues by type
        events: {},

        // Stores Special event hooks data
        hooks: {},

        // Store track event history data
        history: [],

        // Stores ad-hoc state related data]
        state: {
          volume: this.media.volume
        },

        // Store track event object references by trackId
        trackRefs: {},

        // Playback track event queues
        trackEvents: {
          byStart: [{

            start: -1,
            end: -1
          }],
          byEnd: [{
            start: -1,
            end: -1
          }],
          animating: [],
          startIndex: 0,
          endIndex: 0,
          previousUpdateTime: -1
        }
      };

      //  Wrap true ready check
      var isReady = function( that ) {

        var duration, videoDurationPlus;

        if ( that.media.readyState >= 2 ) {
          //  Adding padding to the front and end of the arrays
          //  this is so we do not fall off either end

          duration = that.media.duration;
          //  Check for no duration info (NaN)
          videoDurationPlus = duration != duration ? Number.MAX_VALUE : duration + 1;

          Popcorn.addTrackEvent( that, {
            start: videoDurationPlus,
            end: videoDurationPlus
          });

          if ( that.options.frameAnimation ) {
            //  if Popcorn is created with frameAnimation option set to true,
            //  requestAnimFrame is used instead of "timeupdate" media event.
            //  This is for greater frame time accuracy, theoretically up to
            //  60 frames per second as opposed to ~4 ( ~every 15-250ms)
            that.data.timeUpdate = function () {

              Popcorn.timeUpdate( that, {} );

              that.trigger( "timeupdate" );

              !that.isDestroyed && requestAnimFrame( that.data.timeUpdate );
            };

            !that.isDestroyed && requestAnimFrame( that.data.timeUpdate );

          } else {

            that.data.timeUpdate = function( event ) {
              Popcorn.timeUpdate( that, event );
            };

            if ( !that.isDestroyed ) {
              that.media.addEventListener( "timeupdate", that.data.timeUpdate, false );
            }
          }
        } else {
          global.setTimeout(function() {
            isReady( that );
          }, 1 );
        }
      };

      isReady( this );

      return this;
    }
  };

  //  Extend constructor prototype to instance prototype
  //  Allows chaining methods to instances
  Popcorn.p.init.prototype = Popcorn.p;

  Popcorn.forEach = function( obj, fn, context ) {

    if ( !obj || !fn ) {
      return {};
    }

    context = context || this;

    var key, len;

    // Use native whenever possible
    if ( forEach && obj.forEach === forEach ) {
      return obj.forEach( fn, context );
    }

    if ( toString.call( obj ) === "[object NodeList]" ) {
      for ( key = 0, len = obj.length; key < len; key++ ) {
        fn.call( context, obj[ key ], key, obj );
      }
      return obj;
    }

    for ( key in obj ) {
      if ( hasOwn.call( obj, key ) ) {
        fn.call( context, obj[ key ], key, obj );
      }
    }
    return obj;
  };

  Popcorn.extend = function( obj ) {
    var dest = obj, src = slice.call( arguments, 1 );

    Popcorn.forEach( src, function( copy ) {
      for ( var prop in copy ) {
        dest[ prop ] = copy[ prop ];
      }
    });

    return dest;
  };


  // A Few reusable utils, memoized onto Popcorn
  Popcorn.extend( Popcorn, {
    noConflict: function( deep ) {

      if ( deep ) {
        global.Popcorn = _Popcorn;
      }

      return Popcorn;
    },
    error: function( msg ) {
      throw new Error( msg );
    },
    guid: function( prefix ) {
      Popcorn.guid.counter++;
      return  ( prefix ? prefix : "" ) + ( +new Date() + Popcorn.guid.counter );
    },
    sizeOf: function( obj ) {
      var size = 0;

      for ( var prop in obj ) {
        size++;
      }

      return size;
    },
    isArray: Array.isArray || function( array ) {
      return toString.call( array ) === "[object Array]";
    },

    nop: function() {},

    position: function( elem ) {

      var clientRect = elem.getBoundingClientRect(),
          bounds = {},
          doc = elem.ownerDocument,
          docElem = document.documentElement,
          body = document.body,
          clientTop, clientLeft, scrollTop, scrollLeft, top, left;

      //  Determine correct clientTop/Left
      clientTop = docElem.clientTop || body.clientTop || 0;
      clientLeft = docElem.clientLeft || body.clientLeft || 0;

      //  Determine correct scrollTop/Left
      scrollTop = ( global.pageYOffset && docElem.scrollTop || body.scrollTop );
      scrollLeft = ( global.pageXOffset && docElem.scrollLeft || body.scrollLeft );

      //  Temp top/left
      top = Math.ceil( clientRect.top + scrollTop - clientTop );
      left = Math.ceil( clientRect.left + scrollLeft - clientLeft );

      for ( var p in clientRect ) {
        bounds[ p ] = Math.round( clientRect[ p ] );
      }

      return Popcorn.extend({}, bounds, { top: top, left: left });
    },

    disable: function( instance, plugin ) {

      var disabled = instance.data.disabled;

      if ( disabled.indexOf( plugin ) === -1 ) {
        disabled.push( plugin );
      }

      refresh( instance );

      return instance;
    },
    enable: function( instance, plugin ) {

      var disabled = instance.data.disabled,
          index = disabled.indexOf( plugin );

      if ( index > -1 ) {
        disabled.splice( index, 1 );
      }

      refresh( instance );

      return instance;
    },
    destroy: function( instance ) {
      var events = instance.data.events,
          singleEvent, item, fn;

      //  Iterate through all events and remove them
      for ( item in events ) {
        singleEvent = events[ item ];
        for ( fn in singleEvent ) {
          delete singleEvent[ fn ];
        }
        events[ item ] = null;
      }

      if ( !instance.isDestroyed ) {
        instance.data.timeUpdate && instance.media.removeEventListener( "timeupdate", instance.data.timeUpdate, false );
        instance.isDestroyed = true;
      }
    }
  });

  //  Memoized GUID Counter
  Popcorn.guid.counter = 1;

  //  Factory to implement getters, setters and controllers
  //  as Popcorn instance methods. The IIFE will create and return
  //  an object with defined methods
  Popcorn.extend(Popcorn.p, (function() {

      var methods = "load play pause currentTime playbackRate volume duration preload playbackRate " +
                    "autoplay loop controls muted buffered readyState seeking paused played seekable ended",
          ret = {};


      //  Build methods, store in object that is returned and passed to extend
      Popcorn.forEach( methods.split( /\s+/g ), function( name ) {

        ret[ name ] = function( arg ) {

          if ( typeof this.media[ name ] === "function" ) {

            // Support for shorthanded play(n)/pause(n) jump to currentTime
            // If arg is not null or undefined and called by one of the
            // allowed shorthandable methods, then set the currentTime
            // Supports time as seconds or SMPTE
            if ( arg != null && /play|pause/.test( name ) ) {
              this.media.currentTime = Popcorn.util.toSeconds( arg );
            }

            this.media[ name ]();

            return this;
          }


          if ( arg != null ) {

            this.media[ name ] = arg;

            return this;
          }

          return this.media[ name ];
        };
      });

      return ret;

    })()
  );

  Popcorn.forEach( "enable disable".split(" "), function( method ) {
    Popcorn.p[ method ] = function( plugin ) {
      return Popcorn[ method ]( this, plugin );
    };
  });

  Popcorn.extend(Popcorn.p, {

    //  Rounded currentTime
    roundTime: function() {
      return -~this.media.currentTime;
    },

    //  Attach an event to a single point in time
    exec: function( time, fn ) {

      //  Creating a one second track event with an empty end
      Popcorn.addTrackEvent( this, {
        start: time,
        end: time + 1,
        _running: false,
        _natives: {
          start: fn || Popcorn.nop,
          end: Popcorn.nop,
          type: "exec"
        }
      });

      return this;
    },

    // Mute the calling media, optionally toggle
    mute: function( toggle ) {

      var event = toggle == null || toggle === true ? "muted" : "unmuted";

      // If `toggle` is explicitly `false`,
      // unmute the media and restore the volume level
      if ( event === "unmuted" ) {
        this.media.muted = false;
        this.media.volume = this.data.state.volume;
      }

      // If `toggle` is either null or undefined,
      // save the current volume and mute the media element
      if ( event === "muted" ) {
        this.data.state.volume = this.media.volume;
        this.media.muted = true;
      }

      // Trigger either muted|unmuted event
      this.trigger( event );

      return this;
    },

    // Convenience method, unmute the calling media
    unmute: function( toggle ) {

      return this.mute( toggle == null ? false : !toggle );
    },

    // Get the client bounding box of an instance element
    position: function() {
      return Popcorn.position( this.media );
    },

    // Toggle a plugin's playback behaviour (on or off) per instance
    toggle: function( plugin ) {
      return Popcorn[ this.data.disabled.indexOf( plugin ) > -1 ? "enable" : "disable" ]( this, plugin );
    },

    // Set default values for plugin options objects per instance
    defaults: function( plugin, defaults ) {

      // If an array of default configurations is provided,
      // iterate and apply each to this instance
      if ( Popcorn.isArray( plugin ) ) {

        Popcorn.forEach( plugin, function( obj ) {
          for ( var name in obj ) {
            this.defaults( name, obj[ name ] );
          }
        }, this );

        return this;
      }

      if ( !this.options.defaults ) {
        this.options.defaults = {};
      }

      if ( !this.options.defaults[ plugin ] ) {
        this.options.defaults[ plugin ] = {};
      }

      Popcorn.extend( this.options.defaults[ plugin ], defaults );

      return this;
    }
  });

  Popcorn.Events  = {
    UIEvents: "blur focus focusin focusout load resize scroll unload",
    MouseEvents: "mousedown mouseup mousemove mouseover mouseout mouseenter mouseleave click dblclick",
    Events: "loadstart progress suspend emptied stalled play pause " +
            "loadedmetadata loadeddata waiting playing canplay canplaythrough " +
            "seeking seeked timeupdate ended ratechange durationchange volumechange"
  };

  Popcorn.Events.Natives = Popcorn.Events.UIEvents + " " +
                           Popcorn.Events.MouseEvents + " " +
                           Popcorn.Events.Events;

  internal.events.apiTypes = [ "UIEvents", "MouseEvents", "Events" ];

  // Privately compile events table at load time
  (function( events, data ) {

    var apis = internal.events.apiTypes,
    eventsList = events.Natives.split( /\s+/g ),
    idx = 0, len = eventsList.length, prop;

    for( ; idx < len; idx++ ) {
      data.hash[ eventsList[idx] ] = true;
    }

    apis.forEach(function( val, idx ) {

      data.apis[ val ] = {};

      var apiEvents = events[ val ].split( /\s+/g ),
      len = apiEvents.length,
      k = 0;

      for ( ; k < len; k++ ) {
        data.apis[ val ][ apiEvents[ k ] ] = true;
      }
    });
  })( Popcorn.Events, internal.events );

  Popcorn.events = {

    isNative: function( type ) {
      return !!internal.events.hash[ type ];
    },
    getInterface: function( type ) {

      if ( !Popcorn.events.isNative( type ) ) {
        return false;
      }

      var eventApi = internal.events,
        apis = eventApi.apiTypes,
        apihash = eventApi.apis,
        idx = 0, len = apis.length, api, tmp;

      for ( ; idx < len; idx++ ) {
        tmp = apis[ idx ];

        if ( apihash[ tmp ][ type ] ) {
          api = tmp;
          break;
        }
      }
      return api;
    },
    //  Compile all native events to single array
    all: Popcorn.Events.Natives.split( /\s+/g ),
    //  Defines all Event handling static functions
    fn: {
      trigger: function( type, data ) {

        var eventInterface, evt;
        //  setup checks for custom event system
        if ( this.data.events[ type ] && Popcorn.sizeOf( this.data.events[ type ] ) ) {

          eventInterface  = Popcorn.events.getInterface( type );

          if ( eventInterface ) {

            evt = document.createEvent( eventInterface );
            evt.initEvent( type, true, true, global, 1 );

            this.media.dispatchEvent( evt );

            return this;
          }

          //  Custom events
          Popcorn.forEach( this.data.events[ type ], function( obj, key ) {

            obj.call( this, data );

          }, this );

        }

        return this;
      },
      listen: function( type, fn ) {

        var self = this,
            hasEvents = true,
            eventHook = Popcorn.events.hooks[ type ],
            origType = type,
            tmp;

        if ( !this.data.events[ type ] ) {
          this.data.events[ type ] = {};
          hasEvents = false;
        }

        // Check and setup event hooks
        if ( eventHook ) {

          // Execute hook add method if defined
          if ( eventHook.add ) {
            eventHook.add.call( this, {}, fn );
          }

          // Reassign event type to our piggyback event type if defined
          if ( eventHook.bind ) {
            type = eventHook.bind;
          }

          // Reassign handler if defined
          if ( eventHook.handler ) {
            tmp = fn;

            fn = function wrapper( event ) {
              eventHook.handler.call( self, event, tmp );
            };
          }

          // assume the piggy back event is registered
          hasEvents = true;

          // Setup event registry entry
          if ( !this.data.events[ type ] ) {
            this.data.events[ type ] = {};
            // Toggle if the previous assumption was untrue
            hasEvents = false;
          }
        }

        //  Register event and handler
        this.data.events[ type ][ fn.name || ( fn.toString() + Popcorn.guid() ) ] = fn;

        // only attach one event of any type
        if ( !hasEvents && Popcorn.events.all.indexOf( type ) > -1 ) {

          this.media.addEventListener( type, function( event ) {

            Popcorn.forEach( self.data.events[ type ], function( obj, key ) {
              if ( typeof obj === "function" ) {
                obj.call( self, event );
              }
            });

          }, false);
        }
        return this;
      },
      unlisten: function( type, fn ) {

        if ( this.data.events[ type ] && this.data.events[ type ][ fn ] ) {

          delete this.data.events[ type ][ fn ];

          return this;
        }

        this.data.events[ type ] = null;

        return this;
      }
    },
    hooks: {
      canplayall: {
        bind: "canplaythrough",
        add: function( event, callback ) {

          var state = false;

          if ( this.media.readyState ) {

            callback.call( this, event );

            state = true;
          }

          this.data.hooks.canplayall = {
            fired: state
          };
        },
        // declare special handling instructions
        handler: function canplayall( event, callback ) {

          if ( !this.data.hooks.canplayall.fired ) {
            // trigger original user callback once
            callback.call( this, event );

            this.data.hooks.canplayall.fired = true;
          }
        }
      }
    }
  };

  //  Extend Popcorn.events.fns (listen, unlisten, trigger) to all Popcorn instances
  Popcorn.forEach( [ "trigger", "listen", "unlisten" ], function( key ) {
    Popcorn.p[ key ] = Popcorn.events.fn[ key ];
  });

  // Internal Only - Adds track events to the instance object
  Popcorn.addTrackEvent = function( obj, track ) {

    // Determine if this track has default options set for it
    // If so, apply them to the track object
    if ( track && track._natives && track._natives.type &&
        ( obj.options.defaults && obj.options.defaults[ track._natives.type ] ) ) {

      track = Popcorn.extend( {}, obj.options.defaults[ track._natives.type ], track );
    }

    if ( track._natives ) {
      //  Supports user defined track event id
      track._id = !track.id ? Popcorn.guid( track._natives.type ) : track.id;

      //  Push track event ids into the history
      obj.data.history.push( track._id );
    }

    track.start = Popcorn.util.toSeconds( track.start, obj.options.framerate );
    track.end   = Popcorn.util.toSeconds( track.end, obj.options.framerate );

    //  Store this definition in an array sorted by times
    var byStart = obj.data.trackEvents.byStart,
        byEnd = obj.data.trackEvents.byEnd,
        startIndex, endIndex,
        currentTime;

    for ( startIndex = byStart.length - 1; startIndex >= 0; startIndex-- ) {

      if ( track.start >= byStart[ startIndex ].start ) {
        byStart.splice( startIndex + 1, 0, track );
        break;
      }
    }

    for ( endIndex = byEnd.length - 1; endIndex >= 0; endIndex-- ) {

      if ( track.end > byEnd[ endIndex ].end ) {
        byEnd.splice( endIndex + 1, 0, track );
        break;
      }
    }

    // Display track event immediately if it's enabled and current
    if ( track._natives &&
        ( !!Popcorn.registryByName[ track._natives.type ] || !!obj[ track._natives.type ] ) ) {

      currentTime = obj.media.currentTime;
      if ( track.end > currentTime &&
        track.start <= currentTime &&
        obj.data.disabled.indexOf( track._natives.type ) === -1 ) {

        track._running = true;
        track._natives.start.call( obj, null, track );

        if ( obj.options.frameAnimation &&
          track._natives.frame ) {

          obj.data.trackEvents.animating.push( track );
          track._natives.frame.call( obj, null, track, currentTime );
        }
      }
    }

    // update startIndex and endIndex
    if ( startIndex <= obj.data.trackEvents.startIndex &&
      track.start <= obj.data.trackEvents.previousUpdateTime ) {

      obj.data.trackEvents.startIndex++;
    }

    if ( endIndex <= obj.data.trackEvents.endIndex &&
      track.end < obj.data.trackEvents.previousUpdateTime ) {

      obj.data.trackEvents.endIndex++;
    }

    this.timeUpdate( obj, null, true );

    // Store references to user added trackevents in ref table
    if ( track._id ) {
      Popcorn.addTrackEvent.ref( obj, track );
    }
  };

  // Internal Only - Adds track event references to the instance object's trackRefs hash table
  Popcorn.addTrackEvent.ref = function( obj, track ) {
    obj.data.trackRefs[ track._id ] = track;

    return obj;
  };

  Popcorn.removeTrackEvent  = function( obj, trackId ) {

    var historyLen = obj.data.history.length,
        indexWasAt = 0,
        byStart = [],
        byEnd = [],
        animating = [],
        history = [];

    Popcorn.forEach( obj.data.trackEvents.byStart, function( o, i, context ) {
      // Preserve the original start/end trackEvents
      if ( !o._id ) {
        byStart.push( obj.data.trackEvents.byStart[i] );
        byEnd.push( obj.data.trackEvents.byEnd[i] );
      }

      // Filter for user track events (vs system track events)
      if ( o._id ) {

        // Filter for the trackevent to remove
        if ( o._id !== trackId ) {
          byStart.push( obj.data.trackEvents.byStart[i] );
          byEnd.push( obj.data.trackEvents.byEnd[i] );
        }

        //  Capture the position of the track being removed.
        if ( o._id === trackId ) {
          indexWasAt = i;
          o._natives._teardown && o._natives._teardown.call( obj, o );
        }
      }

    });

    if ( obj.data.trackEvents.animating.length ) {
      Popcorn.forEach( obj.data.trackEvents.animating, function( o, i, context ) {
        // Preserve the original start/end trackEvents
        if ( !o._id ) {
          animating.push( obj.data.trackEvents.animating[i] );
        }

        // Filter for user track events (vs system track events)
        if ( o._id ) {
          // Filter for the trackevent to remove
          if ( o._id !== trackId ) {
            animating.push( obj.data.trackEvents.animating[i] );
          }
        }
      });
    }

    //  Update
    if ( indexWasAt <= obj.data.trackEvents.startIndex ) {
      obj.data.trackEvents.startIndex--;
    }

    if ( indexWasAt <= obj.data.trackEvents.endIndex ) {
      obj.data.trackEvents.endIndex--;
    }

    obj.data.trackEvents.byStart = byStart;
    obj.data.trackEvents.byEnd = byEnd;
    obj.data.trackEvents.animating = animating;

    for ( var i = 0; i < historyLen; i++ ) {
      if ( obj.data.history[ i ] !== trackId ) {
        history.push( obj.data.history[ i ] );
      }
    }

    // Update ordered history array
    obj.data.history = history;

    // Update track event references
    Popcorn.removeTrackEvent.ref( obj, trackId );
  };

  // Internal Only - Removes track event references from instance object's trackRefs hash table
  Popcorn.removeTrackEvent.ref = function( obj, trackId ) {
    delete obj.data.trackRefs[ trackId ];

    return obj;
  };

  // Return an array of track events bound to this instance object
  Popcorn.getTrackEvents = function( obj ) {

    var trackevents = [],
      refs = obj.data.trackEvents.byStart,
      length = refs.length,
      idx = 0,
      ref;

    for ( ; idx < length; idx++ ) {
      ref = refs[ idx ];
      // Return only user attributed track event references
      if ( ref._id ) {
        trackevents.push( ref );
      }
    }

    return trackevents;
  };

  // Internal Only - Returns an instance object's trackRefs hash table
  Popcorn.getTrackEvents.ref = function( obj ) {
    return obj.data.trackRefs;
  };

  // Return a single track event bound to this instance object
  Popcorn.getTrackEvent = function( obj, trackId ) {
    return obj.data.trackRefs[ trackId ];
  };

  // Internal Only - Returns an instance object's track reference by track id
  Popcorn.getTrackEvent.ref = function( obj, trackId ) {
    return obj.data.trackRefs[ trackId ];
  };

  Popcorn.getLastTrackEventId = function( obj ) {
    return obj.data.history[ obj.data.history.length - 1 ];
  };

  Popcorn.timeUpdate = function( obj, event ) {

    var currentTime = obj.media.currentTime,
        previousTime = obj.data.trackEvents.previousUpdateTime,
        tracks = obj.data.trackEvents,
        animating = tracks.animating,
        end = tracks.endIndex,
        start = tracks.startIndex,
        animIndex = 0,

        registryByName = Popcorn.registryByName,

        byEnd, byStart, byAnimate, natives, type;

    //  Playbar advancing
    if ( previousTime <= currentTime ) {

      while ( tracks.byEnd[ end ] && tracks.byEnd[ end ].end <= currentTime ) {

        byEnd = tracks.byEnd[ end ];
        natives = byEnd._natives;
        type = natives && natives.type;

        //  If plugin does not exist on this instance, remove it
        if ( !natives ||
            ( !!registryByName[ type ] ||
              !!obj[ type ] ) ) {

          if ( byEnd._running === true ) {
            byEnd._running = false;
            natives.end.call( obj, event, byEnd );
          }

          end++;
        } else {
          // remove track event
          Popcorn.removeTrackEvent( obj, byEnd._id );
          return;
        }
      }

      while ( tracks.byStart[ start ] && tracks.byStart[ start ].start <= currentTime ) {

        byStart = tracks.byStart[ start ];
        natives = byStart._natives;
        type = natives && natives.type;

        //  If plugin does not exist on this instance, remove it
        if ( !natives ||
            ( !!registryByName[ type ] ||
              !!obj[ type ] ) ) {

          if ( byStart.end > currentTime &&
                byStart._running === false &&
                  obj.data.disabled.indexOf( type ) === -1 ) {

            byStart._running = true;
            natives.start.call( obj, event, byStart );

            // If the `frameAnimation` option is used,
            // push the current byStart object into the `animating` cue
            if ( obj.options.frameAnimation &&
                ( byStart && byStart._running && byStart._natives.frame ) ) {

              animating.push( byStart );
            }
          }
          start++;
        } else {
          // remove track event
          Popcorn.removeTrackEvent( obj, byStart._id );
          return;
        }
      }

      // If the `frameAnimation` option is used, iterate the animating track
      // and execute the `frame` callback
      if ( obj.options.frameAnimation ) {
        while ( animIndex < animating.length ) {

          byAnimate = animating[ animIndex ];

          if ( !byAnimate._running ) {
            animating.splice( animIndex, 1 );
          } else {
            byAnimate._natives.frame.call( obj, event, byAnimate, currentTime );
            animIndex++;
          }
        }
      }

    // Playbar receding
    } else if ( previousTime > currentTime ) {

      while ( tracks.byStart[ start ] && tracks.byStart[ start ].start > currentTime ) {

        byStart = tracks.byStart[ start ];
        natives = byStart._natives;
        type = natives && natives.type;

        // if plugin does not exist on this instance, remove it
        if ( !natives ||
            ( !!registryByName[ type ] ||
              !!obj[ type ] ) ) {

          if ( byStart._running === true ) {
            byStart._running = false;
            natives.end.call( obj, event, byStart );
          }
          start--;
        } else {
          // remove track event
          Popcorn.removeTrackEvent( obj, byStart._id );
          return;
        }
      }

      while ( tracks.byEnd[ end ] && tracks.byEnd[ end ].end > currentTime ) {

        byEnd = tracks.byEnd[ end ];
        natives = byEnd._natives;
        type = natives && natives.type;

        // if plugin does not exist on this instance, remove it
        if ( !natives ||
            ( !!registryByName[ type ] ||
              !!obj[ type ] ) ) {

          if ( byEnd.start <= currentTime &&
                byEnd._running === false  &&
                  obj.data.disabled.indexOf( type ) === -1 ) {

            byEnd._running = true;
            natives.start.call( obj, event, byEnd );

            // If the `frameAnimation` option is used,
            // push the current byEnd object into the `animating` cue
            if ( obj.options.frameAnimation &&
                  ( byEnd && byEnd._running && byEnd._natives.frame ) ) {

              animating.push( byEnd );
            }
          }
          end--;
        } else {
          // remove track event
          Popcorn.removeTrackEvent( obj, byEnd._id );
          return;
        }
      }

      // If the `frameAnimation` option is used, iterate the animating track
      // and execute the `frame` callback
      if ( obj.options.frameAnimation ) {
        while ( animIndex < animating.length ) {

          byAnimate = animating[ animIndex ];

          if ( !byAnimate._running ) {
            animating.splice( animIndex, 1 );
          } else {
            byAnimate._natives.frame.call( obj, event, byAnimate, currentTime );
            animIndex++;
          }
        }
      }
    // time bar is not moving ( video is paused )
    }

    tracks.endIndex = end;
    tracks.startIndex = start;
    tracks.previousUpdateTime = currentTime;
  };

  //  Map and Extend TrackEvent functions to all Popcorn instances
  Popcorn.extend( Popcorn.p, {

    getTrackEvents: function() {
      return Popcorn.getTrackEvents.call( null, this );
    },

    getTrackEvent: function( id ) {
      return Popcorn.getTrackEvent.call( null, this, id );
    },

    getLastTrackEventId: function() {
      return Popcorn.getLastTrackEventId.call( null, this );
    },

    removeTrackEvent: function( id ) {

      Popcorn.removeTrackEvent.call( null, this, id );
      return this;
    },

    removePlugin: function( name ) {
      Popcorn.removePlugin.call( null, this, name );
      return this;
    },

    timeUpdate: function( event ) {
      Popcorn.timeUpdate.call( null, this, event );
      return this;
    },

    destroy: function() {
      Popcorn.destroy.call( null, this );
      return this;
    }
  });

  //  Plugin manifests
  Popcorn.manifest = {};
  //  Plugins are registered
  Popcorn.registry = [];
  Popcorn.registryByName = {};
  //  An interface for extending Popcorn
  //  with plugin functionality
  Popcorn.plugin = function( name, definition, manifest ) {

    if ( Popcorn.protect.natives.indexOf( name.toLowerCase() ) >= 0 ) {
      Popcorn.error( "'" + name + "' is a protected function name" );
      return;
    }

    //  Provides some sugar, but ultimately extends
    //  the definition into Popcorn.p
    var reserved = [ "start", "end" ],
        plugin = {},
        setup,
        isfn = typeof definition === "function",
        methods = [ "_setup", "_teardown", "start", "end", "frame" ];

    // combines calls of two function calls into one
    var combineFn = function( first, second ) {

      first = first || Popcorn.nop;
      second = second || Popcorn.nop;

      return function() {
        first.apply( this, arguments );
        second.apply( this, arguments );
      };
    };

    //  If `manifest` arg is undefined, check for manifest within the `definition` object
    //  If no `definition.manifest`, an empty object is a sufficient fallback
    Popcorn.manifest[ name ] = manifest = manifest || definition.manifest || {};

    // apply safe, and empty default functions
    methods.forEach(function( method ) {
      definition[ method ] = safeTry( definition[ method ] || Popcorn.nop, name );
    });

    var pluginFn = function( setup, options ) {

      if ( !options ) {
        return this;
      }

      //  Storing the plugin natives
      var natives = options._natives = {},
          compose = "",
          defaults, originalOpts, manifestOpts, mergedSetupOpts;

      Popcorn.extend( natives, setup );

      options._natives.type = name;
      options._running = false;

      natives.start = natives.start || natives[ "in" ];
      natives.end = natives.end || natives[ "out" ];

      // extend teardown to always call end if running
      natives._teardown = combineFn(function() {

        var args = slice.call( arguments );

        // end function signature is not the same as teardown,
        // put null on the front of arguments for the event parameter
        args.unshift( null );

        // only call end if event is running
        args[ 1 ]._running && natives.end.apply( this, args );
      }, natives._teardown );

      // Check for previously set default options
      defaults = this.options.defaults && this.options.defaults[ options._natives && options._natives.type ];

      // default to an empty string if no effect exists
      // split string into an array of effects
      options.compose = options.compose && options.compose.split( " " ) || [];
      options.effect = options.effect && options.effect.split( " " ) || [];

      // join the two arrays together
      options.compose = options.compose.concat( options.effect );

      options.compose.forEach(function( composeOption ) {

        // if the requested compose is garbage, throw it away
        compose = Popcorn.compositions[ composeOption ] || {};

        // extends previous functions with compose function
        methods.forEach(function( method ) {
          natives[ method ] = combineFn( natives[ method ], compose[ method ] );
        });
      });

      //  Ensure a manifest object, an empty object is a sufficient fallback
      options._natives.manifest = manifest;

      //  Checks for expected properties
      if ( !( "start" in options ) ) {
        options.start = options[ "in" ] || 0;
      }

      if ( !( "end" in options ) ) {
        options.end = options[ "out" ] || this.duration() || Number.MAX_VALUE;
      }

      // Merge with defaults if they exist, make sure per call is prioritized
      mergedSetupOpts = defaults ? Popcorn.extend( {}, defaults, options ) :
                          options;

      // Resolves 239, 241, 242
      if ( !mergedSetupOpts.target ) {

        //  Sometimes the manifest may be missing entirely
        //  or it has an options object that doesn't have a `target` property
        manifestOpts = "options" in manifest && manifest.options;

        mergedSetupOpts.target = manifestOpts && "target" in manifestOpts && manifestOpts.target;
      }

      // Trigger _setup method if exists
      options._natives._setup && options._natives._setup.call( this, mergedSetupOpts );

      // Create new track event for this instance
      Popcorn.addTrackEvent( this, Popcorn.extend( mergedSetupOpts, options ) );

      //  Future support for plugin event definitions
      //  for all of the native events
      Popcorn.forEach( setup, function( callback, type ) {

        if ( type !== "type" ) {

          if ( reserved.indexOf( type ) === -1 ) {

            this.listen( type, callback );
          }
        }

      }, this );

      return this;
    };

    //  Assign new named definition
    plugin[ name ] = function( options ) {
      return pluginFn.call( this, isfn ? definition.call( this, options ) : definition,
                                  options );
    };

    //  Extend Popcorn.p with new named definition
    Popcorn.extend( Popcorn.p, plugin );

    //  Push into the registry
    var entry = {
      fn: plugin[ name ],
      definition: definition,
      base: definition,
      parents: [],
      name: name
    };
    Popcorn.registry.push(
       Popcorn.extend( plugin, entry, {
        type: name
      })
    );
    Popcorn.registryByName[ name ] = entry;

    return plugin;
  };

  // Storage for plugin function errors
  Popcorn.plugin.errors = [];

  // Returns wrapped plugin function
  function safeTry( fn, pluginName ) {
    return function() {

      //  When Popcorn.plugin.debug is true, do not suppress errors
      if ( Popcorn.plugin.debug ) {
        return fn.apply( this, arguments );
      }

      try {
        return fn.apply( this, arguments );
      } catch ( ex ) {

        // Push plugin function errors into logging queue
        Popcorn.plugin.errors.push({
          plugin: pluginName,
          thrown: ex,
          source: fn.toString()
        });

        // Trigger an error that the instance can listen for
        // and react to
        this.trigger( "error", Popcorn.plugin.errors );
      }
    };
  }

  // Debug-mode flag for plugin development
  Popcorn.plugin.debug = false;

  //  removePlugin( type ) removes all tracks of that from all instances of popcorn
  //  removePlugin( obj, type ) removes all tracks of type from obj, where obj is a single instance of popcorn
  Popcorn.removePlugin = function( obj, name ) {

    //  Check if we are removing plugin from an instance or from all of Popcorn
    if ( !name ) {

      //  Fix the order
      name = obj;
      obj = Popcorn.p;

      if ( Popcorn.protect.natives.indexOf( name.toLowerCase() ) >= 0 ) {
        Popcorn.error( "'" + name + "' is a protected function name" );
        return;
      }

      var registryLen = Popcorn.registry.length,
          registryIdx;

      // remove plugin reference from registry
      for ( registryIdx = 0; registryIdx < registryLen; registryIdx++ ) {
        if ( Popcorn.registry[ registryIdx ].name === name ) {
          Popcorn.registry.splice( registryIdx, 1 );
          delete Popcorn.registryByName[ name ];
          delete Popcorn.manifest[ name ];

          // delete the plugin
          delete obj[ name ];

          // plugin found and removed, stop checking, we are done
          return;
        }
      }

    }

    var byStart = obj.data.trackEvents.byStart,
        byEnd = obj.data.trackEvents.byEnd,
        animating = obj.data.trackEvents.animating,
        idx, sl;

    // remove all trackEvents
    for ( idx = 0, sl = byStart.length; idx < sl; idx++ ) {

      if ( ( byStart[ idx ] && byStart[ idx ]._natives && byStart[ idx ]._natives.type === name ) &&
                ( byEnd[ idx ] && byEnd[ idx ]._natives && byEnd[ idx ]._natives.type === name ) ) {

        byStart[ idx ]._natives._teardown && byStart[ idx ]._natives._teardown.call( obj, byStart[ idx ] );

        byStart.splice( idx, 1 );
        byEnd.splice( idx, 1 );

        // update for loop if something removed, but keep checking
        idx--; sl--;
        if ( obj.data.trackEvents.startIndex <= idx ) {
          obj.data.trackEvents.startIndex--;
          obj.data.trackEvents.endIndex--;
        }
      }
    }

    //remove all animating events
    for ( idx = 0, sl = animating.length; idx < sl; idx++ ) {

      if ( animating[ idx ] && animating[ idx ]._natives && animating[ idx ]._natives.type === name ) {

        animating.splice( idx, 1 );

        // update for loop if something removed, but keep checking
        idx--; sl--;
      }
    }

  };

  Popcorn.compositions = {};

  //  Plugin inheritance
  Popcorn.compose = function( name, definition, manifest ) {

    //  If `manifest` arg is undefined, check for manifest within the `definition` object
    //  If no `definition.manifest`, an empty object is a sufficient fallback
    Popcorn.manifest[ name ] = manifest = manifest || definition.manifest || {};

    // register the effect by name
    Popcorn.compositions[ name ] = definition;
  };

  Popcorn.plugin.effect = Popcorn.effect = Popcorn.compose;

  // stores parsers keyed on filetype
  Popcorn.parsers = {};

  // An interface for extending Popcorn
  // with parser functionality
  Popcorn.parser = function( name, type, definition ) {

    if ( Popcorn.protect.natives.indexOf( name.toLowerCase() ) >= 0 ) {
      Popcorn.error( "'" + name + "' is a protected function name" );
      return;
    }

    // fixes parameters for overloaded function call
    if ( typeof type === "function" && !definition ) {
      definition = type;
      type = "";
    }

    if ( typeof definition !== "function" || typeof type !== "string" ) {
      return;
    }

    // Provides some sugar, but ultimately extends
    // the definition into Popcorn.p

    var natives = Popcorn.events.all,
        parseFn,
        parser = {};

    parseFn = function( filename, callback ) {

      if ( !filename ) {
        return this;
      }

      var that = this;

      Popcorn.xhr({
        url: filename,
        dataType: type,
        success: function( data ) {

          var tracksObject = definition( data ),
              tracksData,
              tracksDataLen,
              tracksDef,
              idx = 0;

          tracksData = tracksObject.data || [];
          tracksDataLen = tracksData.length;
          tracksDef = null;

          //  If no tracks to process, return immediately
          if ( !tracksDataLen ) {
            return;
          }

          //  Create tracks out of parsed object
          for ( ; idx < tracksDataLen; idx++ ) {

            tracksDef = tracksData[ idx ];

            for ( var key in tracksDef ) {

              if ( hasOwn.call( tracksDef, key ) && !!that[ key ] ) {

                that[ key ]( tracksDef[ key ] );
              }
            }
          }
          if ( callback ) {
            callback();
          }
        }
      });

      return this;
    };

    // Assign new named definition
    parser[ name ] = parseFn;

    // Extend Popcorn.p with new named definition
    Popcorn.extend( Popcorn.p, parser );

    // keys the function name by filetype extension
    //Popcorn.parsers[ name ] = true;

    return parser;
  };

  Popcorn.player = function( name, player ) {

    player = player || {};

    var playerFn = function( target, src, options ) {

      options = options || {};

      // List of events
      var date = new Date() / 1000,
          baselineTime = date,
          currentTime = 0,
          volume = 1,
          muted = false,
          events = {},

          // The container div of the resource
          container = document.getElementById( rIdExp.exec( target ) && rIdExp.exec( target )[ 2 ] ) ||
                        document.getElementById( target ) ||
                          target,
          basePlayer = {},
          timeout,
          popcorn;

      // copies a div into the media object
      for( var val in container ) {

        if ( typeof container[ val ] === "object" ) {

          basePlayer[ val ] = container[ val ];
        } else if ( typeof container[ val ] === "function" ) {

          basePlayer[ val ] = (function( value ) {

            // this is a stupid ugly kludgy hack in honour of Safari
            // in Safari a NodeList is a function, not an object
            if ( "length" in container[ value ] && !container[ value ].call ) {

              return container[ value ];
            } else {

              return function() {

                return container[ value ].apply( container, arguments );
              };
            }
          }( val ));
        } else {

          Popcorn.player.defineProperty( basePlayer, val, {
            get: (function( value ) {

              return function() {

                return container[ value ];
              };
            }( val )),
            set: Popcorn.nop,
            configurable: true
          });
        }
      }

      var timeupdate = function() {

        date = new Date() / 1000;

        if ( !basePlayer.paused ) {

          basePlayer.currentTime = basePlayer.currentTime + ( date - baselineTime );
          basePlayer.dispatchEvent( "timeupdate" );
          timeout = setTimeout( timeupdate, 10 );
        }

        baselineTime = date;
      };

      basePlayer.play = function() {

        this.paused = false;

        if ( basePlayer.readyState >= 4 ) {

          baselineTime = new Date() / 1000;
          basePlayer.dispatchEvent( "play" );
          timeupdate();
        }
      };

      basePlayer.pause = function() {

        this.paused = true;
        basePlayer.dispatchEvent( "pause" );
      };

      Popcorn.player.defineProperty( basePlayer, "currentTime", {
        get: function() {

          return currentTime;
        },
        set: function( val ) {

          // make sure val is a number
          currentTime = +val;
          basePlayer.dispatchEvent( "timeupdate" );
          return currentTime;
        },
        configurable: true
      });

      Popcorn.player.defineProperty( basePlayer, "volume", {
        get: function() {

          return volume;
        },
        set: function( val ) {

          // make sure val is a number
          volume = +val;
          basePlayer.dispatchEvent( "volumechange" );
          return volume;
        },
        configurable: true
      });

      Popcorn.player.defineProperty( basePlayer, "muted", {
        get: function() {

          return muted;
        },
        set: function( val ) {

          // make sure val is a number
          muted = +val;
          basePlayer.dispatchEvent( "volumechange" );
          return muted;
        },
        configurable: true
      });

      // Adds an event listener to the object
      basePlayer.addEventListener = function( evtName, fn ) {

        if ( !events[ evtName ] ) {

          events[ evtName ] = [];
        }

        events[ evtName ].push( fn );
        return fn;
      };

      // Can take event object or simple string
      basePlayer.dispatchEvent = function( oEvent ) {

        var evt,
            self = this,
            eventInterface,
            eventName = oEvent.type;

        // A string was passed, create event object
        if ( !eventName ) {

          eventName = oEvent;
          eventInterface  = Popcorn.events.getInterface( eventName );

          if ( eventInterface ) {

            evt = document.createEvent( eventInterface );
            evt.initEvent( eventName, true, true, window, 1 );
          }
        }

        Popcorn.forEach( events[ eventName ], function( val ) {

          val.call( self, evt, self );
        });
      };

      // Attempt to get src from playerFn parameter
      basePlayer.src = src || "";
      basePlayer.readyState = 0;
      basePlayer.duration = 0;
      basePlayer.paused = true;
      basePlayer.ended = 0;

      if ( player._setup ) {

        player._setup.call( basePlayer, options );
      } else {

        // there is no setup, which means there is nothing to load
        basePlayer.readyState = 4;
        basePlayer.dispatchEvent( "load" );
        basePlayer.dispatchEvent( "loadeddata" );
      }

      // when a custom player is loaded, load basePlayer state into custom player
      basePlayer.addEventListener( "load", function() {

        // if a player is not ready before currentTime is called, this will set it after it is ready
        basePlayer.currentTime = currentTime;

        // same as above with volume and muted
        basePlayer.volume = volume;
        basePlayer.muted = muted;
      });

      basePlayer.addEventListener( "loadeddata", function() {

        // if play was called before player ready, start playing video
        !basePlayer.paused && basePlayer.play();
      });

      popcorn = new Popcorn.p.init( basePlayer, options );

      return popcorn;
    };

    Popcorn[ name ] = Popcorn[ name ] || playerFn;
  };

  Popcorn.player.defineProperty = Object.defineProperty || function( object, description, options ) {

    object.__defineGetter__( description, options.get || Popcorn.nop );
    object.__defineSetter__( description, options.set || Popcorn.nop );
  };

  //  Cache references to reused RegExps
  var rparams = /\?/,
  //  XHR Setup object
  setup = {
    url: "",
    data: "",
    dataType: "",
    success: Popcorn.nop,
    type: "GET",
    async: true,
    xhr: function() {
      return new global.XMLHttpRequest();
    }
  };

  Popcorn.xhr = function( options ) {

    options.dataType = options.dataType && options.dataType.toLowerCase() || null;

    if ( options.dataType &&
         ( options.dataType === "jsonp" || options.dataType === "script" ) ) {

      Popcorn.xhr.getJSONP(
        options.url,
        options.success,
        options.dataType === "script"
      );
      return;
    }

    var settings = Popcorn.extend( {}, setup, options );

    //  Create new XMLHttpRequest object
    settings.ajax  = settings.xhr();

    if ( settings.ajax ) {

      if ( settings.type === "GET" && settings.data ) {

        //  append query string
        settings.url += ( rparams.test( settings.url ) ? "&" : "?" ) + settings.data;

        //  Garbage collect and reset settings.data
        settings.data = null;
      }


      settings.ajax.open( settings.type, settings.url, settings.async );
      settings.ajax.send( settings.data || null );

      return Popcorn.xhr.httpData( settings );
    }
  };


  Popcorn.xhr.httpData = function( settings ) {

    var data, json = null,
        parser, xml = null;

    settings.ajax.onreadystatechange = function() {

      if ( settings.ajax.readyState === 4 ) {

        try {
          json = JSON.parse( settings.ajax.responseText );
        } catch( e ) {
          //suppress
        }

        data = {
          xml: settings.ajax.responseXML,
          text: settings.ajax.responseText,
          json: json
        };

        // Normalize: data.xml is non-null in IE9 regardless of if response is valid xml
        if ( !data.xml || !data.xml.documentElement ) {
          data.xml = null;

          try {
            parser = new DOMParser();
            xml = parser.parseFromString( settings.ajax.responseText, "text/xml" );

            if ( !xml.getElementsByTagName( "parsererror" ).length ) {
              data.xml = xml;
            }
          } catch ( e ) {
            // data.xml remains null
          }
        }

        //  If a dataType was specified, return that type of data
        if ( settings.dataType ) {
          data = data[ settings.dataType ];
        }


        settings.success.call( settings.ajax, data );

      }
    };
    return data;
  };

  Popcorn.xhr.getJSONP = function( url, success, isScript ) {

    var head = document.head || document.getElementsByTagName( "head" )[ 0 ] || document.documentElement,
      script = document.createElement( "script" ),
      paramStr = url.split( "?" )[ 1 ],
      isFired = false,
      params = [],
      callback, parts, callparam;

    if ( paramStr && !isScript ) {
      params = paramStr.split( "&" );
    }

    if ( params.length ) {
      parts = params[ params.length - 1 ].split( "=" );
    }

    callback = params.length ? ( parts[ 1 ] ? parts[ 1 ] : parts[ 0 ]  ) : "jsonp";

    if ( !paramStr && !isScript ) {
      url += "?callback=" + callback;
    }

    if ( callback && !isScript ) {

      //  If a callback name already exists
      if ( !!window[ callback ] ) {
        //  Create a new unique callback name
        callback = Popcorn.guid( callback );
      }

      //  Define the JSONP success callback globally
      window[ callback ] = function( data ) {
        // Fire success callbacks
        success && success( data );
        isFired = true;
      };

      //  Replace callback param and callback name
      url = url.replace( parts.join( "=" ), parts[ 0 ] + "=" + callback );
    }

    script.onload = function() {

      //  Handling remote script loading callbacks
      if ( isScript ) {
        //  getScript
        success && success();
      }

      //  Executing for JSONP requests
      if ( isFired ) {
        //  Garbage collect the callback
        delete window[ callback ];
      }
      //  Garbage collect the script resource
      head.removeChild( script );
    };

    script.src = url;

    head.insertBefore( script, head.firstChild );

    return;
  };

  Popcorn.getJSONP = Popcorn.xhr.getJSONP;

  Popcorn.getScript = Popcorn.xhr.getScript = function( url, success ) {

    return Popcorn.xhr.getJSONP( url, success, true );
  };

  Popcorn.util = {
    // Simple function to parse a timestamp into seconds
    // Acceptable formats are:
    // HH:MM:SS.MMM
    // HH:MM:SS;FF
    // Hours and minutes are optional. They default to 0
    toSeconds: function( timeStr, framerate ) {
      // Hours and minutes are optional
      // Seconds must be specified
      // Seconds can be followed by milliseconds OR by the frame information
      var validTimeFormat = /^([0-9]+:){0,2}[0-9]+([.;][0-9]+)?$/,
          errorMessage = "Invalid time format",
          digitPairs, lastIndex, lastPair, firstPair,
          frameInfo, frameTime;

      if ( typeof timeStr === "number" ) {
        return timeStr;
      }

      if ( typeof timeStr === "string" &&
            !validTimeFormat.test( timeStr ) ) {
        Popcorn.error( errorMessage );
      }

      digitPairs = timeStr.split( ":" );
      lastIndex = digitPairs.length - 1;
      lastPair = digitPairs[ lastIndex ];

      // Fix last element:
      if ( lastPair.indexOf( ";" ) > -1 ) {

        frameInfo = lastPair.split( ";" );
        frameTime = 0;

        if ( framerate && ( typeof framerate === "number" ) ) {
          frameTime = parseFloat( frameInfo[ 1 ], 10 ) / framerate;
        }

        digitPairs[ lastIndex ] = parseInt( frameInfo[ 0 ], 10 ) + frameTime;
      }

      firstPair = digitPairs[ 0 ];

      return {

        1: parseFloat( firstPair, 10 ),

        2: ( parseInt( firstPair, 10 ) * 60 ) +
              parseFloat( digitPairs[ 1 ], 10 ),

        3: ( parseInt( firstPair, 10 ) * 3600 ) +
            ( parseInt( digitPairs[ 1 ], 10 ) * 60 ) +
              parseFloat( digitPairs[ 2 ], 10 )

      }[ digitPairs.length || 1 ];
    }
  };


  // Initialize locale data
  // Based on http://en.wikipedia.org/wiki/Language_localisation#Language_tags_and_codes
  function initLocale( arg ) {

    var locale = typeof arg === "string" ? arg : [ arg.language, arg.region ].join( "-" ),
        parts = locale.split( "-" );

    // Setup locale data table
    return {
      iso6391: locale,
      language: parts[ 0 ] || "",
      region: parts[ 1 ] || ""
    };
  }

  // Declare locale data table
  var localeData = initLocale( global.navigator.userLanguage || global.navigator.language );

  Popcorn.locale = {

    // Popcorn.locale.get()
    // returns reference to privately
    // defined localeData
    get: function() {
      return localeData;
    },

    // Popcorn.locale.set( string|object );
    set: function( arg ) {

      localeData = initLocale( arg );

      Popcorn.locale.broadcast();

      return localeData;
    },

    // Popcorn.locale.broadcast( type )
    // Sends events to all popcorn media instances that are
    // listening for locale events
    broadcast: function( type ) {

      var instances = Popcorn.instances,
          length = instances.length,
          idx = 0,
          instance;

      type = type || "locale:changed";

      // Iterate all current instances
      for ( ; idx < length; idx++ ) {
        instance = instances[ idx ];

        // For those instances with locale event listeners,
        // trigger a locale change event
        if ( type in instance.data.events  ) {
          instance.trigger( type );
        }
      }
    }
  };

  // alias for exec function
  Popcorn.p.cue = Popcorn.p.exec;

  function getItems() {

    var item,
        list = [];

    if ( Object.keys ) {
      list = Object.keys( Popcorn.p );
    } else {

      for ( item in Popcorn.p ) {
        if ( hasOwn.call( Popcorn.p, item ) ) {
          list.push( item );
        }
      }
    }

    return list.join( "," ).toLowerCase().split( ",");
  }

  //  Protected API methods
  Popcorn.protect = {
    natives: getItems()
  };

  //  Exposes Popcorn to global context
  global.Popcorn = Popcorn;

})(window, window.document);
/*!
 * Popcorn.sequence
 *
 * Copyright 2011, Rick Waldron
 * Licensed under MIT license.
 *
 */

/* jslint forin: true, maxerr: 50, indent: 4, es5: true  */
/* global Popcorn: true */

// Requires Popcorn.js
(function( global, Popcorn ) {

  // TODO: as support increases, migrate to element.dataset
  var doc = global.document,
      location = global.location,
      rprotocol = /:\/\//,
      // TODO: better solution to this sucky stop-gap
      lochref = location.href.replace( location.href.split("/").slice(-1)[0], "" ),
      // privately held
      range = function(start, stop, step) {

        start = start || 0;
        stop = ( stop || start || 0 ) + 1;
        step = step || 1;

        var len = Math.ceil((stop - start) / step) || 0,
            idx = 0,
            range = [];

        range.length = len;

        while (idx < len) {
         range[idx++] = start;
         start += step;
        }
        return range;
      };

  Popcorn.sequence = function( parent, list ) {
    return new Popcorn.sequence.init( parent, list );
  };

  Popcorn.sequence.init = function( parent, list ) {

    // Video element
    this.parent = doc.getElementById( parent );

    // Store ref to a special ID
    this.seqId = Popcorn.guid( "__sequenced" );

    // List of HTMLVideoElements
    this.queue = [];

    // List of Popcorn objects
    this.playlist = [];

    // Lists of in/out points
    this.inOuts = {

      // Stores the video in/out times for each video in sequence
      ofVideos: [],

      // Stores the clip in/out times for each clip in sequences
      ofClips: []

    };

    // Store first video dimensions
    this.dims = {
      width: 0, //this.video.videoWidth,
      height: 0 //this.video.videoHeight
    };

    this.active = 0;
    this.cycling = false;
    this.playing = false;

    this.times = {
      last: 0
    };

    // Store event pointers and queues
    this.events = {

    };

    var self = this,
        clipOffset = 0;

    // Create `video` elements
    Popcorn.forEach( list, function( media, idx ) {

      var video = doc.createElement( "video" );

      video.preload = "auto";

      // Setup newly created video element
      video.controls = true;

      // If the first, show it, if the after, hide it
      video.style.display = ( idx && "none" ) || "" ;

      // Seta registered sequence id
      video.id = self.seqId + "-" + idx ;

      // Push this video into the sequence queue
      self.queue.push( video );

      var //satisfy lint
       mIn = media["in"],
       mOut = media["out"];

      // Push the in/out points into sequence ioVideos
      self.inOuts.ofVideos.push({
        "in": ( mIn !== undefined && mIn ) || 1,
        "out": ( mOut !== undefined && mOut ) || 0
      });

      self.inOuts.ofVideos[ idx ]["out"] = self.inOuts.ofVideos[ idx ]["out"] || self.inOuts.ofVideos[ idx ]["in"] + 2;

      // Set the sources
      video.src = !rprotocol.test( media.src ) ? lochref + media.src : media.src;

      // Set some squence specific data vars
      video.setAttribute("data-sequence-owner", parent );
      video.setAttribute("data-sequence-guid", self.seqId );
      video.setAttribute("data-sequence-id", idx );
      video.setAttribute("data-sequence-clip", [ self.inOuts.ofVideos[ idx ]["in"], self.inOuts.ofVideos[ idx ]["out"] ].join(":") );

      // Append the video to the parent element
      self.parent.appendChild( video );


      self.playlist.push( Popcorn("#" + video.id ) );

    });

    self.inOuts.ofVideos.forEach(function( obj ) {

      var clipDuration = obj["out"] - obj["in"],
          offs = {
            "in": clipOffset,
            "out": clipOffset + clipDuration
          };

      self.inOuts.ofClips.push( offs );

      clipOffset = offs["out"] + 1;
    });

    Popcorn.forEach( this.queue, function( media, idx ) {

      function canPlayThrough( event ) {

        // If this is idx zero, use it as dimension for all
        if ( !idx ) {
          self.dims.width = media.videoWidth;
          self.dims.height = media.videoHeight;
        }

        media.currentTime = self.inOuts.ofVideos[ idx ]["in"] - 0.5;

        media.removeEventListener( "canplaythrough", canPlayThrough, false );

        return true;
      }

      // Hook up event listeners for managing special playback
      media.addEventListener( "canplaythrough", canPlayThrough, false );

      // TODO: consolidate & DRY
      media.addEventListener( "play", function( event ) {

        self.playing = true;

      }, false );

      media.addEventListener( "pause", function( event ) {

        self.playing = false;

      }, false );

      media.addEventListener( "timeupdate", function( event ) {

        var target = event.srcElement || event.target,
            seqIdx = +(  (target.dataset && target.dataset.sequenceId) || target.getAttribute("data-sequence-id") ),
            floor = Math.floor( media.currentTime );

        if ( self.times.last !== floor &&
              seqIdx === self.active ) {

          self.times.last = floor;

          if ( floor === self.inOuts.ofVideos[ seqIdx ]["out"] ) {

            Popcorn.sequence.cycle.call( self, seqIdx );
          }
        }
      }, false );
    });

    return this;
  };

  Popcorn.sequence.init.prototype = Popcorn.sequence.prototype;

  //
  Popcorn.sequence.cycle = function( idx ) {

    if ( !this.queue ) {
      Popcorn.error("Popcorn.sequence.cycle is not a public method");
    }

    var // Localize references
    queue = this.queue,
    ioVideos = this.inOuts.ofVideos,
    current = queue[ idx ],
    nextIdx = 0,
    next, clip;


    var // Popcorn instances
    $popnext,
    $popprev;


    if ( queue[ idx + 1 ] ) {
      nextIdx = idx + 1;
    }

    // Reset queue
    if ( !queue[ idx + 1 ] ) {

      nextIdx = 0;
      this.playlist[ idx ].pause();

    } else {

      next = queue[ nextIdx ];
      clip = ioVideos[ nextIdx ];

      // Constrain dimentions
      Popcorn.extend( next, {
        width: this.dims.width,
        height: this.dims.height
      });

      $popnext = this.playlist[ nextIdx ];
      $popprev = this.playlist[ idx ];

      // When not resetting to 0
      current.pause();

      this.active = nextIdx;
      this.times.last = clip["in"] - 1;

      // Play the next video in the sequence
      $popnext.currentTime( clip["in"] );

      $popnext[ nextIdx ? "play" : "pause" ]();

      // Trigger custom cycling event hook
      this.trigger( "cycle", {

        position: {
          previous: idx,
          current: nextIdx
        }

      });

      // Set the previous back to it's beginning time
      // $popprev.currentTime( ioVideos[ idx ].in );

      if ( nextIdx ) {
        // Hide the currently ending video
        current.style.display = "none";
        // Show the next video in the sequence
        next.style.display = "";
      }

      this.cycling = false;
    }

    return this;
  };

  var excludes = [ "timeupdate", "play", "pause" ];

  // Sequence object prototype
  Popcorn.extend( Popcorn.sequence.prototype, {

    // Returns Popcorn object from sequence at index
    eq: function( idx ) {
      return this.playlist[ idx ];
    },
    // Remove a sequence from it's playback display container
    remove: function() {
      this.parent.innerHTML = null;
    },
    // Returns Clip object from sequence at index
    clip: function( idx ) {
      return this.inOuts.ofVideos[ idx ];
    },
    // Returns sum duration for all videos in sequence
    duration: function() {

      var ret = 0,
          seq = this.inOuts.ofClips,
          idx = 0;

      for ( ; idx < seq.length; idx++ ) {
        ret += seq[ idx ]["out"] - seq[ idx ]["in"] + 1;
      }

      return ret - 1;
    },

    play: function() {

      this.playlist[ this.active ].play();

      return this;
    },
    // Attach an event to a single point in time
    exec: function ( time, fn ) {

      var index = this.active;

      this.inOuts.ofClips.forEach(function( off, idx ) {
        if ( time >= off["in"] && time <= off["out"] ) {
          index = idx;
        }
      });

      //offsetBy = time - self.inOuts.ofVideos[ index ].in;

      time += this.inOuts.ofVideos[ index ]["in"] - this.inOuts.ofClips[ index ]["in"];

      // Creating a one second track event with an empty end
      Popcorn.addTrackEvent( this.playlist[ index ], {
        start: time - 1,
        end: time,
        _running: false,
        _natives: {
          start: fn || Popcorn.nop,
          end: Popcorn.nop,
          type: "exec"
        }
      });

      return this;
    },
    // Binds event handlers that fire only when all
    // videos in sequence have heard the event
    listen: function( type, callback ) {

      var self = this,
          seq = this.playlist,
          total = seq.length,
          count = 0,
          fnName;

      if ( !callback ) {
        callback = Popcorn.nop;
      }

      // Handling for DOM and Media events
      if ( Popcorn.Events.Natives.indexOf( type ) > -1 ) {
        Popcorn.forEach( seq, function( video ) {

          video.listen( type, function( event ) {

            event.active = self;

            if ( excludes.indexOf( type ) > -1 ) {

              callback.call( video, event );

            } else {
              if ( ++count === total ) {
                callback.call( video, event );
              }
            }
          });
        });

      } else {

        // If no events registered with this name, create a cache
        if ( !this.events[ type ] ) {
          this.events[ type ] = {};
        }

        // Normalize a callback name key
        fnName = callback.name || Popcorn.guid( "__" + type );

        // Store in event cache
        this.events[ type ][ fnName ] = callback;
      }

      // Return the sequence object
      return this;
    },
    unlisten: function( type, name ) {
      // TODO: finish implementation
    },
    trigger: function( type, data ) {
      var self = this;

      // Handling for DOM and Media events
      if ( Popcorn.Events.Natives.indexOf( type ) > -1 ) {

        //  find the active video and trigger api events on that video.
        return;

      } else {

        // Only proceed if there are events of this type
        // currently registered on the sequence
        if ( this.events[ type ] ) {

          Popcorn.forEach( this.events[ type ], function( callback, name ) {
            callback.call( self, { type: type }, data );
          });

        }
      }

      return this;
    }
  });


  Popcorn.forEach( Popcorn.manifest, function( obj, plugin ) {

    // Implement passthrough methods to plugins
    Popcorn.sequence.prototype[ plugin ] = function( options ) {

      // console.log( this, options );
      var videos = {}, assignTo = [],
      idx, off, inOuts, inIdx, outIdx, keys, clip, clipInOut, clipRange;

      for ( idx = 0; idx < this.inOuts.ofClips.length; idx++  ) {
        // store reference
        off = this.inOuts.ofClips[ idx ];
        // array to test against
        inOuts = range( off["in"], off["out"] );

        inIdx = inOuts.indexOf( options.start );
        outIdx = inOuts.indexOf( options.end );

        if ( inIdx > -1 ) {
          videos[ idx ] = Popcorn.extend( {}, off, {
            start: inOuts[ inIdx ],
            clipIdx: inIdx
          });
        }

        if ( outIdx > -1 ) {
          videos[ idx ] = Popcorn.extend( {}, off, {
            end: inOuts[ outIdx ],
            clipIdx: outIdx
          });
        }
      }

      keys = Object.keys( videos ).map(function( val ) {
                return +val;
              });

      assignTo = range( keys[ 0 ], keys[ 1 ] );

      //console.log( "PLUGIN CALL MAPS: ", videos, keys, assignTo );
      for ( idx = 0; idx < assignTo.length; idx++ ) {

        var compile = {},
        play = assignTo[ idx ],
        vClip = videos[ play ];

        if ( vClip ) {

          // has instructions
          clip = this.inOuts.ofVideos[ play ];
          clipInOut = vClip.clipIdx;
          clipRange = range( clip["in"], clip["out"] );

          if ( vClip.start ) {
            compile.start = clipRange[ clipInOut ];
            compile.end = clipRange[ clipRange.length - 1 ];
          }

          if ( vClip.end ) {
            compile.start = clipRange[ 0 ];
            compile.end = clipRange[ clipInOut ];
          }

          //compile.start += 0.1;
          //compile.end += 0.9;

        } else {

          compile.start = this.inOuts.ofVideos[ play ]["in"];
          compile.end = this.inOuts.ofVideos[ play ]["out"];

          //compile.start += 0.1;
          //compile.end += 0.9;

        }

        // Handling full clip persistance
        //if ( compile.start === compile.end ) {
          //compile.start -= 0.1;
          //compile.end += 0.9;
        //}

        // Call the plugin on the appropriate Popcorn object in the playlist
        // Merge original options object & compiled (start/end) object into
        // a new fresh object
        this.playlist[ play ][ plugin ](

          Popcorn.extend( {}, options, compile )

        );

      }

      // Return the sequence object
      return this;
    };

  });
})( this, Popcorn );
(function( Popcorn ) {
  document.addEventListener( "DOMContentLoaded", function() {

    //  Supports non-specific elements
    var dataAttr = "data-timeline-sources",
        medias = document.querySelectorAll( "[" + dataAttr + "]" );

    Popcorn.forEach( medias, function( idx, key ) {

      var media = medias[ key ],
          hasDataSources = false,
          dataSources, data, popcornMedia;

      //  Ensure that the DOM has an id
      if ( !media.id ) {

        media.id = Popcorn.guid( "__popcorn" );
      }

      //  Ensure we're looking at a dom node
      if ( media.nodeType && media.nodeType === 1 ) {

        popcornMedia = Popcorn( "#" + media.id );

        dataSources = ( media.getAttribute( dataAttr ) || "" ).split( "," );

        if ( dataSources[ 0 ] ) {

          Popcorn.forEach( dataSources, function( source ) {

            // split the parser and data as parser!file
            data = source.split( "!" );

            // if no parser is defined for the file, assume "parse" + file extension
            if ( data.length === 1 ) {

              // parse a relative URL for the filename, split to get extension
              data = source.match( /(.*)[\/\\]([^\/\\]+\.\w+)$/ )[ 2 ].split( "." );

              data[ 0 ] = "parse" + data[ 1 ].toUpperCase();
              data[ 1 ] = source;
            }

            //  If the media has data sources and the correct parser is registered, continue to load
            if ( dataSources[ 0 ] && popcornMedia[ data[ 0 ] ] ) {

              //  Set up the media and load in the datasources
              popcornMedia[ data[ 0 ] ]( data[ 1 ] );

            }
          });

        }

        //  Only play the media if it was specified to do so
        if ( !!popcornMedia.autoplay ) {
          popcornMedia.play();
        }

      }
    });
  }, false );

})( Popcorn );// PLUGIN: Attribution

(function( Popcorn ) {

  /**
   * Attribution popcorn plug-in
   * Adds text to an element on the page.
   * Options parameter will need a mandatory start, end, target.
   * Optional parameters include nameofwork, NameOfWorkUrl, CopyrightHolder, CopyrightHolderUrl, license & licenseUrl.
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Target is the id of the document element that the text needs to be attached to, this target element must exist on the DOM
   * nameofwork is the title of the attribution
   * NameOfWorkUrl is a url that provides more details about the attribution
   * CopyrightHolder is the name of the person/institution that holds the rights to the attribution
   * CopyrightHolderUrl is the url that provides more details about the copyrightholder
   * license is the type of license that the work is copyrighted under
   * LicenseUrl is the url that provides more details about the ticense type
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .attribution({
          start: 5, // seconds
          end: 15, // seconds
          target: 'attributiondiv'
        } )
   *
   */
  Popcorn.plugin( "attribution" , (function() {

    var
    common = "data:image/png;base64,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",
    licenses = {
      "cc-by": common + "eeSURBVHja7JpfbNvGHce/R9JBU9Qa89QN2gD5TepLmGTJYyyte9mypiSC7aXrIj8NqDFI6lavLezISpwuE5LJwpACw7aaWJ8L0/kD7B8iyi2wRXYiGikgvUkPNbY+ybXbh5l/bg8kT6RlO7Zjq2maM0488e4o8sPv/e53vzOhlEYIIZ/hadr3RCklBAAFgNt/vwWO48BxHHieB8fx4DkOHO8dOQ6EcOAIASEEIMS/CigoqEPhUAeO42bbtt2jY8O2HTiOzeoc6rD2lFL/Zlj5SUg/fvknAAACgPpweZ53M8d3yzzv1nG8B5mAEC7I14PjgXVcmLbt5WDZDkN2HIeBDYJ+kiALAMJweQFC6Ojmm3O3UKlUUKvVsLa6FrrQYGQQp06dQup7Kbx09kewHR4cZ7kvxOZAQLx3GRg+DnVHArwxRPYH7v2FOrQPNDQajdD5RCIB+ZyM4yeP9RUyAUD/duevEASBQRUEwc28gKo+j+KVIpaXl3d0wWg0irG3xjA8fBqWbcO2LViWl20LlmUzhW+m5L2q+L//+RTXy9fRbDQBAMlkEpIkAQAMw4Cu6wCAeCKO0cwovvmt5/uiYAKA/rP6Dwi80AUrDGBAEJCfmIQ2q7EOoihClmXEYjEMDw8DAKrVKtrtNjRNw8rKCmsrKzJ+NfZLHH72MCzLgmlZsCwTlmWFTYYP2PFs+R5s8eernyMzmsXq6ipkWUapVEIsFgu1abfbyOVy0DQNkUgEl4uXDxwyA3znwzsY8MEOCBgQBkJwRVFENptFJpOBKIpbXlBVVeRyOQY6nojjT+/9Ec8cPgzLMmGaJlPyppDp3gBPvHkBzUYT6XQaMzMz3eHpmaDg9VRVxcjICOKJOC5duXjggDkA4D0bLPA8BD6sXEmSUK/Xkc/nt4ULAOl0Gq1Wiw3NZqOJq8VrIVvOMY+EdLP3txHMTm1us9GELMsYe+ONh7ZPp9OQZRnNRhP3F+oHbiY4AOB8t4znUdXnQ3ArlUrPcNsuiaKISqXCIGuzGqrVefC8sDlkznf7EIK806R94N5rqVRC4oUXNvqhm46GUqkU6nvggF0FuyouXikyUDMzMw9V7XaQ/b7F3xQ9X9qDSzyfmvM8DIIuZLI7yI1GA8lkskcEIyMjbISMjIyE6mKxGJLJZI+ncXAK9h7+5twt5i1ks1mmwr0kURSZUpaXl3Hzxi22YHEhb20idps2u09VVTctb9fnwAD7aqpUKgxOJpNhjXRdh6IoSKVSSKVSKBQKW9ZNT0+H7J2v4sqdSkC9XdNAyKOZiMc9uQsNQsARglqt5rpYsszA6LqOVCoV6qTrOnRdRyaTgaIoPXVLS0tsNpdlGaqqolaruSvAAFigC7frle/+IQzD2HQy85WbTqd31OcAFew+qL9CO3r0KGuQy+WY3Wq1WmzSO3/+PFOyJElotVqYnZ0N+cgAWHltda1rDtjR57p3E5FIJKDrOtrtduh80F0Lln2fWNd1JBKJ/ih44+QStE/+m06n04jFYgy0P5H4KvXrZFnumVC67hf72LcHkM/JaEw1kMvlMDs7u6M+vmjkc3J/FPxVTsdPHkM8EYemaT3ewlZwNU1DPBHvS1yC84MtQX8xaJ98NauqipWVFRiGgaGhIRQKha6v6y2Tg3XB4dj1S9nHvj7Er98eQyQSgaqqUBSF/WbQD26321AUBdPT04hEIhjNjPZvkvNvZDAyiLXVNSwtLbEG+Xye3fSRI0dC4Pw6wzB66vzkX2swMghKA8thUPjv1Pu254d4LvIcyten8dt3itA0DZqmQZIkSJIEURSh6zoTTT+DPWzevnvvLg4dOoTChQK0WQ2iKKLT6YQ8g3K5zGIMyWQS+XyeqbdcLrO2wToAGBoaQrvdxovffxHXSlfxv/V1mOY6TMuEaVqw/biEY8OxHRaE32vo8nEKV7Jgz78X/4WBgUP4aP4jZH6RYcvJbDb7SD/gB1YAYOqdKfzwzA+wbq5j3TRhmSZMawPgRwj4PK4Bdw4A29JJpoYRjUYBAIVCocf12U1aWVlhs3U0GvUC8X5o0oHj2WLfXDypiQMAhzqwbXcf7dLliwyQoiihGO9u4KZSKdZ37M0xL8BudyEHQpRskqVP1pYRm9wB0PH8OF24X6PGgzp99Wev+lM9lSSJ1ut1utPUarWoJEmsv6zI1HhQpwv3a/Ti5Yvs/Ncod79kX8/QxfoCNT42qKzI7LwoinRycpJ2Op0twXY6HTo5OUlFUWT9Tp46SZc+NuiisUDH8+NfR7i0Z/U/kR/Hy4oMQRBwrXgN7//l/T1vGRUuTcKyLNy9W8NrP3/t4IdiwLwEdzOCq9SN3/tmIoJ5Ij/uKvlBnb6n/plGo9Edv7FoNErLvy9T40GdLhoL9N0/vNs3tVBKty0Hz31pCvZT9vUMXvnpK2wXQq9UcWPuxrbb9mfls0gmh9le29zcDUwVpvqnlE0U/GUq96EBwuMnjmEifwHf/k40sBsRDDci5Lf6/3iy/Mkn+N3VEuar8/0digGIj4Np2HEE9vTwaZx56QxOfPcEvhGJhGO4nmv12eoq7i3ew+2bt/sO9iur4KdpHwBTSp8lhHzxFMWBjCjy/wEATHqgDqiBjQoAAAAASUVORK5CYII=",
      "cc-by-sa": common + "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",
      "cc-by-nd": common + "grSURBVHja7FpNbBvHFf72R0YdROz6lBZsAQrogczFtB37aFF1AqR1bC1h2Jc0NXUqEKEgmTZqWkimaMupS9ilicJJA7fRojkHWvkH6B/MpRqgNSWLKzgAeSjAPURoe5IipYeKuzs97O5wl1xSFCWljeNnjHa5M/Ptzjdv3nvzxgwhJMAwzKd4KnsuhBCGAUAA4P4f74FlWbAsC47jwLIcOJYFy9lXlgXDsGAZBgzDAAzjoICAgJgEJjFhmlYxDMO6mgYMw4RpGrTOJCZtTwhxPobePwlyfvQCAIABQBxyOY6zCss17znOqmM5m2QGDMO6+bXJsYk1LTINwy7ue8NLsmmalFg30U8SyTwAL7kcD95ztcrd+XsoFosol8vY3Nj0AA0GBnHixAmMfHsEZ86+AsPkwLK6NSEGCwaMPZeu5WMSayXAXkNMd3KXFyuQP5RRrVY9zyORCMRzIo4eP7IrMvYLnwFA/vDg9+B5npLK87xVOB4lZQG5azmsrq72BBgMBjHx0wkMD5+EbhgwDB26bhdDh64bVMP9NLlVi//5j3/hVuEWatUaACAWiyEajQIAVFWFoigAgHAkjPHkOL729ed2RMB+4p8fvWAR/OfSn8BzfJNYfgADPI/M1DTkOZl2EAQBoigiFApheHgYAFAqlaBpGmRZxvr6Om0rxkX8eOJHOPjMQei6joauQ9cb0HXdazIcgk3blruI/mzjMyTHU9jY2IAoisjn8wiFQp5BaJqGdDoNWZYRCARwNXe1ZxL2G58S/OAvDzDgEDvAY4Af8JArCAJSqRSSySQEQegIKEkS0uk0JTocCeM379/GVw4ehK430Gg0qCb7ktxij6feuoRatYZEIoHZ2dnmsrNNi1vTJUnC2NgYwpEwrly73BMBnfA7jW2n+OdHL4AFAM62wTzHgee8mhuNRlGpVJDJZLqSCwCJRAL1ep0usVq1huu5Gx5bztKIhGkW+5+bwOXFCmrVGkRRxMSbb247mEQiAVEUUavWsLxY6cnm7ie+IywAsE5YxnEoKQsecovFYtuy6SaCIKBYLFKS5TkZpdICOI73J5l1wj54SJY/tL4hn88j8vzzrfGlr0PM5/Oevt2kG34n2Qm+h2BLgy0tzl3LUaJmZ2e31dpuJDt9cz/P2bG0TS5jx9SsHWEwaJJsL/9qtYpYLNY2uWNjY1Tzx8bGPHWhUAixWKwtEvATP/xvhYZ8Sz/4Xg22B393/h6NFlKpFNXCfkQQBDrjq6uruHvnHt2wWCR3NhGO+L1fkiTf+259Oklr25deftm39IsPwIqDHW0qFouUnGQySRspioJCoUCdVywWQyaT8a0bHR1FKpWidstxesUHRbxy5rStvbZpMJskOyaC4H+30Xj31+/uOaa10WAYsAyDcrlshViiSJe3oigYGRnxdFIUBYqiIJlMIh6Pt9WtrKxQryyKIiRJQrlctnaArItUNMltRuVNLFVVfZ2No7mJRKKt3q9PJ2lt6zYHbvm7Vu8Ln5oIZ8DODu3w4cO0QTqdpvanXq9Tp3fx4kVks1m6bOr1Oubm5jwxMgB6v7mx2TQH9Orw2m4iIpEIFEWBpmme5+5wqjW00jQNiqIgEolsO3A//FMvvehb+sH3aLDbubTaGWfGEokEQqEQJdpxOI6WOnWiKLY5nmb4Rf9s+2HiORHVmSrS6TTm5uZ6GoyjDOI5sS/8927f3jN8jwb/P8rR40cQjoQhy3JbtNBp8LIsIxwJ95Q32G98L8HEuyty2xlHmyVJwvr6OlRVxdDQELLZbDPWtbfJ7jr3smrGr/RPTx/3k59NIBAIQJIkxONxiuWOgzVNQzwex82bNxEIBDCeHO958J3wW81Ov/jURDgfPBgYxObGJlZWVmiDTCZDX37o0CHPi506VVXb6hxxsAYDgyDEtR0GgTOn9q+2j3s28CwKt27iF2/nIMsyZFlGNBpFNBqFIAhQFIUqQz/JmP3Gp3774aOHOHDgALKXspDnZAiCgLW1tZ7CNFmWUSgUaFt3HQAMDQ1B0zScevEUbuSv4z9bW2g0ttDQG2g0dBhOXsI0YBomTcK37tS+iOlKmuz529JfMTBwAB8tfITkD5N0W+jEs/2KkyABgJm3Z/Dd09/BVmMLW40G9EYDDb2FYJ+Ezxc94c4CoEc6sZFhBINBAEA2m/W1Sb3K+vo69brBYNBOxDupSROmbYsdc/GkCgsAJjFhGNY52pWrlylB8Xjck+PdCbkjIyO078RbE3aC3WiS7EpRUidLnqwjI+rcAZDJzCRZXC4T9XGFvPb91xxXT6LRKKlUKqRXqdfrJBqN0v5iXCTq4wpZXC6Ty1cv0+dfotL8kXojSZYqi0T9WCViXKTPBUEg09PTZG1trSOxa2trZHp6mgiCQPsdP3GcrHyskiV1kUxmJr+M5BKmNSidykxiNC6C53ncyN3AB7/7oO8jo+yVaei6jocPy3j9B6/3v8RcZsN9muHefbb+3im+H5bfe/s2Ee4ylZm0NPlxhbwv/ZYEg8GeZywYDJLCrwpEfVwhS+oieee9d3atBYSQrvfuZ/3ib4fb7zuYTtuq1BtJvPq9V+kphFIs4c78na7H9mfFs4jFhulZ2/z8HcxkZ3bvJLpo0m40109j/a67eQ/Tbd969NgRTGUu4RvfDLpOI9zpRnjiVuc/nqx+8gl+eT2PhdLC3njhLgPdS4Ldk/m5EOzIyeGTOH3mNI69cAxfDQS8OVw7tPp0YwOPlh7h/t37e0bs563B+2GDeyL4qfQvDCHkGYZh/v2Uin3YYBDC/HcArOiX8zGX6zMAAAAASUVORK5CYII=",
      "cc-by-nc": common + "k0SURBVHja7FpdbNvWFf5IysFS1BrztA1yMBt7sQqskZMmy4Ytlta9LJ4TCnaCFkkWuQ812mCTlB+3S+3Iyk8TK/Zkb0iBYVstrCjahwZm/oDNGSLaKzBbTiIZaSM9rJCK2FiHDbArpwVmkbx7EHlF2pIty3axpjnGFX/uvR/J75577jnnmiGEWBmG+RSPZc2FEMIwAAgA3Bi+DpZlwbIsOI4Dy3LgWBYspx1ZFgzDgmUYMAwDMIyOAgICohKoRIWq5ouiKPmjqkBRVKiqQutUotL2hBD9Zej5oyD79u4HADAAiE4ux3H5wnKFc47L17GcRjIDhmGN/GrkaMSqeTIVRSvGc8VMsqqqlFgj0Y8SyRYAZnI5CyymY75cu3Id0WgUsVgMc9k5E1C1tRo7duyA68cuNO/5GRSVA8vK+QFRWDBgtLE0TB+V5GcCtDnELE3u3Yk4xMsiksmk6b7dbofQImDr9oZVkbFe+AwA8pdbf4bFYqGkWiyWfOEsGJFGEboQwvT0dFmANpsNHb/qQGPjLsiKAkWRIctaUWTIskI1vJgmL9TiT/75L1wauIRUMgUAcDqdcDgcAIBEIgFJkgAA9fZ6HPEewTe/9Y0VEbCe+Pv27s8T/NeRm7BwlgKxlipUWSwIdHVDHBJpB57nIQgCamtr0djYCAAYGRlBJpOBKIqYnZ2lbQW3gOMdx7DxiY2QZRk5WYYs5yDLstlk6ASrmi03EP0w+xDeIz5ks1kIgoBwOIza2lrTR2QyGfj9foiiCKvVinOhc2WTsN74lOBbf7uFKp3YKguqLFUmcnmeh8/ng9frBc/zJQEjkQj8fj8lut5ejz+8+Xt8beNGyHIOuVyOanJRkhfY465XTyGVTMHj8WBwcLAw7TTTYtT0SCSCtrY21NvrcebC6bIIKIX/m/5+jI+N4+1331kV/r69+8ECAKfZYAvHwcKZNdfhcCAejyMQCCxJLgB4PB6k02k6xVLJFHpDfSZbzlKPhCkU7c9I4N2JOFLJFARBQMeJE8t+jMfjgSAISCVTuDsRL8vmppIpbG1owA92ft9E7oVQCNdu3MArx09gamqqInxdWABgdbeM4zAijZrIjUaji6bNUsLzPKLRKCVZHBIxMjIKjrMUJ5nV3T6YSBYv598hHA7D/tRTC/3LogtiOBw29V1K9DafP/wMPefPw/nDH+GlF9vh9fvR3t6OkydPItTXi/GxsYrwTQTnNTivxaELIUrU4ODgslq7FMl639D5kOZLa+Qymk/Nah4GgwLJ2vRPJpNwOp2LBretrY1qfltbm6mutrYWTqdzkSdQTHT85uZm7Nu/H1NTU7g5PIzvfLsWn889xMFDB3H/ww/R0tpaEb5Zg7WPv3blOvUWfD4f1cJKhOd5OuLT09O4dvU6DVjyJJc2EboUe34kEil6vlSfUuJwOBDq68X5UA/efvcdtLS24qOPMwj19WLz5s2IvDmI5P37FeNTgnVtikajlByv10sbSZIEt9sNl8sFl8uFYDBYsq6/v99kF3Utjt6KGrS3YBoYpriJ+KLlezt3oqf3Ih48eICOY8fR8N2ncfm999C8uwkHnnseN4eHK8LNBxoMA5ZhEIvF8i6WIFBiJEmCy+UydZIkCZIkwev1wu12L6qbnJykq7IgCIhEIojFYvkI0EAsUCC34JUXsBKJRNHFTNdcj8ezqL5Yn1KysG02m8XN4WH09F6E534bmnc3AQDGx8YwPjaGmpoaMFWWSjQ4/6F6hLZlyxbawO/3U/uTTqfponf48GGqyQ6HA+l0GkNDQyYfGQA9n8vOFcwBPeq8LjYRdrsdkiQhk8mY7hvdKeO57rNKkgS73b7shxfDf+nFdpw7fQZbn96CA889j48+zqCltRU9vRdx4ODBFeGbCDYuLgvtjD7KHo+HGvl0Og2Px0Pr9OBDEARaZ1wYCu4X/Vn2xYQWwTTA5YjeVu+7Uvye3otoe+EFfPKff+Mf6TQGwmG8dqoLLa2tCJ49g4btz5SNbyb4/1C2bm9Avb0eoigu8hZKkSuKIurt9WXlDYrh19TU4LVTXTjmP4rmpib80ueD1WqtCN9MMDFHRUbbpGtzJBLB7OwsEokE6urqEAwGC76uFiYb64zTtuC/0p+yXu6Vkx2wWq2IRCJwu90Uy+gHZzIZuN1u9Pf3w2q14oj3SNkfXwr/2InjNIpbDT5d5PQXrrZWYy47h8nJSdogEAjQh2/atMlEnF6XSCQW1emiY1Vbq0GIIRwGgT6m2tWil3vS+iQGLvWj5/UQRFGEKIpwOBxwOBzgeR6SJFFlqCQZs974dN0evzOODRs2IHgqCHFIBM/zmJmZMXkGAwMDNMfgdDoRCASo9g4MDNC2xjoAqKurQyaTwbM/eRZ94V78d34eudw8cnIOuZwMRc9LqApURaVJ+IWR2pcxXUmTPWO3/46qqg14f/R9eH/hpWGhz+db1UvrCRIAOPv6Wexu+inmc/OYz+Ug53LIyQsILpLw+bIn3FkAdEvH6WqEzWYDAASDwUUu0kpkdnaWrtA2m01LxOupSRWqZot1c/GoCgsAKlGhKPl9tDPnTlOC3G63Kce7EnJdLhft2/Fqh5ZgVwokG1KUdJElj9aWEV3cAZDOQCeZuBsjiXtxcujnh/SlnjgcDhKPx0m5kk6nicPhoP0Ft0AS9+Jk4m6MnD53mt7/CpXChe+ol9yOT5DEBwkiuAV6n+d50t3dTWZmZkoSOzMzQ7q7uwnP87Tf9h3byeQHCXI7MUE6A51fRXIJs9Ap7Qp0Yq9bgMViQV+oD2/96a2Kt4yCZ7ohyzLGx2N4uf3lyqeYwWwYdzOM0efC65Xil8LSn10pNoqx3hXozGvyvTh5M/JHYrPZyh4xm81GBn47QBL34uR2YoK88bs3Vq0FhJAlz433KsVfDrfSZzClwirfUS8OHDxAdyGk6AiuXrm65Lb9HmEPnM5Gutd25cpVnA2eXf0iUUSD10JzF2KUOq5GmKXi1q3bGtAVOIWazTbDboQx3QiT36r/48n01BR+3RvG6Mjo2qzCC6bsWpmG5UzCUs9dE4J12dW4C03NTdj2zDZ83Wo153A11+rTbBZ3bt/BjWs31ozYL1qD18MGl0XwY1mFiSCEPMEwzGePqViHAIMQ5n8DAFb/49reYmyHAAAAAElFTkSuQmCC",
      "cc-by-nc-sa": common + "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",
      "cc-by-nc-nd": common + "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"
    },
    target;

    return {

      _setup: function( options ) {

        var attrib = "",
        license = options.license && licenses[ options.license.toLowerCase() ],
        tar = "target=_blank";

        // make a div to put the information into
        options._container = document.createElement( "div" );
        options._container.style.display = "none";

        // Cache declared target
        target = document.getElementById( options.target );

        if ( options.nameofworkurl ) {
          attrib += "<a href='" + options.nameofworkurl + "' " + tar + ">";
        }
        if ( options.nameofwork ) {
          attrib += options.nameofwork;
        }
        if ( options.nameofworkurl ) {
          attrib += "</a>";
        }
        if ( options.copyrightholderurl ) {
          attrib += "<a href='" + options.copyrightholderurl + "' " + tar + ">";
        }
        if ( options.copyrightholder ) {
          attrib += ", " + options.copyrightholder;
        }
        if ( options.copyrightholderurl ) {
          attrib += "</a>";
        }

        //if the user did not specify any parameters just pull the text from the tag
        if ( attrib === "" ) {
          attrib = options.text;
        }

        if ( options.license ) {
          if ( license ) {
            if ( options.licenseurl ) {
              attrib = "<a href='" + options.licenseurl + "' " + tar + "><img src='"+ license +"' border='0'/></a> " + attrib;
            } else {
              attrib = "<img src='"+ license +"' />" + attrib;
            }
          } else {
            attrib += ", license: ";

            if ( options.licenseurl ) {
              attrib += "<a href='" + options.licenseurl + "' " + tar + ">" + options.license + "</a> ";
            } else {
              attrib += options.license;
            }
          }
        } else if ( options.licenseurl ) {
          attrib += ", <a href='" + options.licenseurl + "' " + tar + ">license</a> ";
        }

        options._container.innerHTML  = attrib;

        if ( !target && Popcorn.plugin.debug ) {
          throw new Error( "target container doesn't exist" );
        }
        target && target.appendChild( options._container );
      },
      /**
       * @member attribution
       * The start function will be executed when the currentTime
       * of the video  reaches the start time provided by the
       * options variable
       */
      start: function( event, options ) {
        options._container.style.display = "inline";
      },
      /**
       * @member attribution
       * The end function will be executed when the currentTime
       * of the video  reaches the end time provided by the
       * options variable
       */
      end: function( event, options ) {
        options._container.style.display = "none";
      },
      _teardown: function( options ) {

        // Cache declared target
        target = document.getElementById( options.target );

        target && target.removeChild( options._container );
      }
    };
  })(),
  {
    about:{
      name: "Popcorn Attribution Plugin",
      version: "0.2",
      author: "@rwaldron",
      website: "github.com/rwldrn"
    },
    options:{
      start: {
       elem: "input",
       type: "text",
       label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      nameofwork: {
        elem: "input",
        type: "text",
        label: "Name of Work"
      },
      nameofworkurl: {
        elem: "input",
        type: "url",
        label: "Url of Work"
      },
      copyrightholder: {
        elem: "input",
        type: "text",
        label: "Copyright Holder"
      },
      copyrightholderurl: {
        elem: "input",
        type: "url",
        label: "Copyright Holder Url"
      },
      license: {
        elem: "input",
        type: "text",
        label: "License type"
       },
      licenseurl: {
        elem: "input",
        type: "url",
        label: "License URL"
      },
      target: "attribution-container"
    }
  });
})( Popcorn );
// PLUGIN: Code

(function ( Popcorn ) {

  /**
   * Code Popcorn Plug-in
   *
   * Adds the ability to run arbitrary code (JavaScript functions) according to video timing.
   *
   * @param {Object} options
   *
   * Required parameters: start, end, template, data, and target.
   * Optional parameter: static.
   *
   *   start: the time in seconds when the mustache template should be rendered
   *          in the target div.
   *
   *   end: the time in seconds when the rendered mustache template should be
   *        removed from the target div.
   *
   *   onStart: the function to be run when the start time is reached.
   *
   *   onFrame: [optional] a function to be run on each paint call
   *            (e.g., called ~60 times per second) between the start and end times.
   *
   *   onEnd: [optional] a function to be run when the end time is reached.
   *
   * Example:
     var p = Popcorn('#video')

        // onStart function only
        .code({
          start: 1,
          end: 4,
          onStart: function( options ) {
            // called on start
          }
        })

        // onStart + onEnd only
        .code({
          start: 6,
          end: 8,
          onStart: function( options ) {
            // called on start
          },
          onEnd: function ( options ) {
            // called on end
          }
        })

        // onStart, onEnd, onFrame
        .code({
          start: 10,
          end: 14,
          onStart: function( options ) {
            // called on start
          },
          onFrame: function ( options ) {
            // called on every paint frame between start and end.
            // uses mozRequestAnimationFrame, webkitRequestAnimationFrame,
            // or setTimeout with 16ms window.
          },
          onEnd: function ( options ) {
            // called on end
          }
        });
  *
  */

  Popcorn.plugin( "code" , function( options ) {
    var running = false;

    // Setup a proper frame interval function (60fps), favouring paint events.
    var step = (function() {

      var buildFrameRunner = function( runner ) {
        return function( f, options ) {

          var _f = function() {
            running && f();
            running && runner( _f );
          };

          _f();
        };
      };

      // Figure out which level of browser support we have for this
      if ( window.webkitRequestAnimationFrame ) {
        return buildFrameRunner( window.webkitRequestAnimationFrame );
      } else if ( window.mozRequestAnimationFrame ) {
        return buildFrameRunner( window.mozRequestAnimationFrame );
      } else {
        return buildFrameRunner( function( f ) {
          window.setTimeout( f, 16 );
        });
      }

    })();

    if ( !options.onStart || typeof options.onStart !== "function" ) {

      if ( Popcorn.plugin.debug ) {
        throw new Error( "Popcorn Code Plugin Error: onStart must be a function." );
      }
      options.onStart = Popcorn.nop;
    }

    if ( options.onEnd && typeof options.onEnd !== "function" ) {

      if ( Popcorn.plugin.debug ) {
        throw new Error( "Popcorn Code Plugin Error: onEnd  must be a function." );
      }
      options.onEnd = undefined;
    }

    if ( options.onFrame && typeof options.onFrame !== "function" ) {

      if ( Popcorn.plugin.debug ) {
        throw new Error( "Popcorn Code Plugin Error: onFrame  must be a function." );
      }
      options.onFrame = undefined;
    }

    return {
      start: function( event, options ) {
        options.onStart( options );

        if ( options.onFrame ) {
          running = true;
          step( options.onFrame, options );
        }
      },

      end: function( event, options ) {
        if ( options.onFrame ) {
          running = false;
        }

        if ( options.onEnd ) {
          options.onEnd( options );
        }
      }
    };
  },
  {
    about: {
      name: "Popcorn Code Plugin",
      version: "0.1",
      author: "David Humphrey (@humphd)",
      website: "http://vocamus.net/dave"
    },
    options: {
      start: {
       elem: "input",
       type: "text",
       label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      onStart: {
        elem: "input",
        type: "function",
        label: "onStart"
      },
      onFrame: {
        elem: "input",
        type: "function",
        label: "onFrame"
      },
      onEnd: {
        elem: "input",
        type: "function",
        label: "onEnd"
      }
    }
  });
})( Popcorn );
// PLUGIN: Flickr
(function (Popcorn) {

  /**
   * Flickr popcorn plug-in
   * Appends a users Flickr images to an element on the page.
   * Options parameter will need a start, end, target and userid or username and api_key.
   * Optional parameters are numberofimages, height, width, padding, and border
   * Start is the time that you want this plug-in to execute (in seconds)
   * End is the time that you want this plug-in to stop executing (in seconds)
   * Userid is the id of who's Flickr images you wish to show
   * Tags is a mutually exclusive list of image descriptor tags
   * Username is the username of who's Flickr images you wish to show
   *  using both userid and username is redundant
   *  an api_key is required when using username
   * Apikey is your own api key provided by Flickr
   * Target is the id of the document element that the images are
   *  appended to, this target element must exist on the DOM
   * Numberofimages specify the number of images to retreive from flickr, defaults to 4
   * Height the height of the image, defaults to '50px'
   * Width the width of the image, defaults to '50px'
   * Padding number of pixels between images, defaults to '5px'
   * Border border size in pixels around images, defaults to '0px'
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .flickr({
          start:          5,                 // seconds, mandatory
          end:            15,                // seconds, mandatory
          userid:         '35034346917@N01', // optional
          tags:           'dogs,cats',       // optional
          numberofimages: '8',               // optional
          height:         '50px',            // optional
          width:          '50px',            // optional
          padding:        '5px',             // optional
          border:         '0px',             // optional
          target:         'flickrdiv'        // mandatory
        } )
   *
   */

  var idx = 0;

  Popcorn.plugin( "flickr" , function( options ) {
    var containerDiv,
        target = document.getElementById( options.target ),
        _userid,
        _uri,
        _link,
        _image,
        _count = options.numberofimages || 4,
        _height = options.height || "50px",
        _width = options.width || "50px",
        _padding = options.padding || "5px",
        _border = options.border || "0px";

    // create a new div this way anything in the target div is left intact
    // this is later populated with Flickr images
    containerDiv = document.createElement( "div" );
    containerDiv.id = "flickr" + idx;
    containerDiv.style.width = "100%";
    containerDiv.style.height = "100%";
    containerDiv.style.display = "none";
    idx++;

    // ensure the target container the user chose exists
    if ( !target && Popcorn.plugin.debug ) {
      throw new Error( "flickr target container doesn't exist" );
    }

    target && target.appendChild( containerDiv );

    // get the userid from Flickr API by using the username and apikey
    var isUserIDReady = function() {
      if ( !_userid ) {

        _uri  = "http://api.flickr.com/services/rest/?method=flickr.people.findByUsername&";
        _uri += "username=" + options.username + "&api_key=" + options.apikey + "&format=json&jsoncallback=flickr";
        Popcorn.getJSONP( _uri, function( data ) {
          _userid = data.user.nsid;
          getFlickrData();
        });

      } else {

        setTimeout(function () {
          isUserIDReady();
        }, 5 );
      }
    };

    // get the photos from Flickr API by using the user_id and/or tags
    var getFlickrData = function() {

      _uri  = "http://api.flickr.com/services/feeds/photos_public.gne?";

      if ( _userid ) {
        _uri += "id=" + _userid + "&";
      }
      if ( options.tags ) {
        _uri += "tags=" + options.tags + "&";
      }

      _uri += "lang=en-us&format=json&jsoncallback=flickr";

      Popcorn.xhr.getJSONP( _uri, function( data ) {

        var fragment = document.createElement( "p" );

        fragment.innerHTML = "<p style='padding:" + _padding + ";'>" + data.title + "<p/>";

        Popcorn.forEach( data.items, function ( item, i ) {
          if ( i < _count ) {

            _link = document.createElement( "a" );
            _link.setAttribute( "href", item.link );
            _link.setAttribute( "target", "_blank" );
            _image = document.createElement( "img" );
            _image.setAttribute( "src", item.media.m );
            _image.setAttribute( "height",_height );
            _image.setAttribute( "width", _width );
            _image.setAttribute( "style", "border:" + _border + ";padding:" + _padding );
            _link.appendChild( _image );
            fragment.appendChild( _link );

          } else {

            return false;
          }
        });

        containerDiv.appendChild( fragment );
      });
    };

    if ( options.username && options.apikey ) {
      isUserIDReady();
    }
    else {
      _userid = options.userid;
      getFlickrData();
    }
    return {
      /**
       * @member flickr
       * The start function will be executed when the currentTime
       * of the video reaches the start time provided by the
       * options variable
       */
      start: function( event, options ) {
        containerDiv.style.display = "inline";
      },
      /**
       * @member flickr
       * The end function will be executed when the currentTime
       * of the video reaches the end time provided by the
       * options variable
       */
      end: function( event, options ) {
        containerDiv.style.display = "none";
      },
      _teardown: function( options ) {
        document.getElementById( options.target ) && document.getElementById( options.target ).removeChild( containerDiv );
      }
    };
  },
  {
    about: {
      name: "Popcorn Flickr Plugin",
      version: "0.2",
      author: "Scott Downe, Steven Weerdenburg, Annasob",
      website: "http://scottdowne.wordpress.com/"
    },
    options: {
      start: {
        elem: "input",
        type: "number",
        label: "In"
      },
      end: {
        elem: "input",
        type: "number",
        label: "Out"
      },
      userid: {
        elem: "input",
        type: "text",
        label: "UserID"
      },
      tags: {
        elem: "input",
        type: "text",
        label: "Tags"
      },
      username: {
        elem: "input",
        type: "text",
        label: "Username"
      },
      apikey: {
        elem: "input",
        type: "text",
        label: "Api_key"
      },
      target: "flickr-container",
      height: {
        elem: "input",
        type: "text",
        label: "Height"
      },
      width: {
        elem: "input",
        type: "text",
        label: "Width"
      },
      padding: {
        elem: "input",
        type: "text",
        label: "Padding"
      },
      border: {
        elem: "input",
        type: "text",
        label: "Border"
      },
      numberofimages: {
        elem: "input",
        type: "text",
        label: "Number of Images"
      }
    }
  });
})( Popcorn );
// PLUGIN: Footnote/Text

(function ( Popcorn ) {

  /**
   * Footnote popcorn plug-in
   * Adds text to an element on the page.
   * Options parameter will need a start, end, target and text.
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Text is the text that you want to appear in the target
   * Target is the id of the document element that the text needs to be
   * attached to, this target element must exist on the DOM
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .footnote({
          start: 5, // seconds
          end: 15, // seconds
          text: 'This video made exclusively for drumbeat.org',
          target: 'footnotediv'
        } )
   *
   */

  Popcorn.forEach( [ "footnote", "text" ], function( name ) {

    Popcorn.plugin( name , {

      manifest: {
        about: {
          name: "Popcorn " + name + " Plugin",
          version: "0.2",
          author: "@annasob, @rwaldron",
          website: "annasob.wordpress.com"
        },
        options: {
          start: {
            elem: "input",
            type: "text",
            label: "In"
          },
          end: {
            elem: "input",
            type: "text",
            label: "Out"
          },
          text: {
            elem: "input",
            type: "text",
            label: "Text"
          },
          target: name + "-container"
        }
      },
    _setup: function( options ) {

      var target = document.getElementById( options.target );

      options._container = document.createElement( "div" );
      options._container.style.display = "none";
      options._container.innerHTML  = options.text;

      if ( !target && Popcorn.plugin.debug ) {
        throw new Error( "target container doesn't exist" );
      }
      target && target.appendChild( options._container );
    },
    /**
     * @member footnote
     * The start function will be executed when the currentTime
     * of the video  reaches the start time provided by the
     * options variable
     */
    start: function( event, options ){
      options._container.style.display = "inline";
    },
    /**
     * @member footnote
     * The end function will be executed when the currentTime
     * of the video  reaches the end time provided by the
     * options variable
     */
    end: function( event, options ){
      options._container.style.display = "none";
    },
    _teardown: function( options ) {
      document.getElementById( options.target ) && document.getElementById( options.target ).removeChild( options._container );
    }
  });
});

})( Popcorn );
//PLUGIN: facebook

(function( Popcorn, global ) {
/**
  * Facebook Popcorn plug-in
  * Places Facebook's "social plugins" inside a div ( http://developers.facebook.com/docs/plugins/ )
  * Sets options according to user input or default values
  * Options parameter will need a target, type, start and end time
  * Type is the name of the plugin in fbxml format. Options: LIKE (default), LIKE-BOX, ACTIVITY, FACEPILE
  * Target is the id of the document element that the text needs to be attached to. This target element must exist on the DOM
  * Start is the time that you want this plug-in to execute
  * End is the time that you want this plug-in to stop executing
  *
  * Other than the mandatory four parameters, there are several optional parameters (Some options are only applicable to certain plugins)
  * Action - like button will either "Like" or "Recommend". Options: recommend / like(default)
  * Always_post_to_friends - live-stream posts will be always be posted on your facebook wall if true. Options: true / false(default)
  * Border_color - border color of the activity feed. Names (i.e: "white") and html color codes are valid
  * Colorscheme - changes the color of almost all plugins. Options: light(default) / dark
  * Event_app_id - an app_id is required for the live-stream plugin
  * Font - the font of the text contained in the plugin. Options: arial / segoe ui / tahoma / trebuchet ms / verdana / lucida grande
  * Header - displays the title of like-box or activity feed. Options: true / false(default)
  * Href - url to apply to the plugin. Default is current page
  * Layout - changes the format of the 'like' count (written in english or a number in a callout).
  *          Options: box_count / button_count / standard(default)
  * Max_rows - number of rows to disperse pictures in facepile. Default is 1
  * Recommendations - shows recommendations, if any, in the bottom half of activity feed. Options: true / false(default)
  * Show_faces - show pictures beside like button and like-box. Options: true / false(default)
  * Site - href for activity feed. No idea why it must be "site". Default is current page
  * Stream - displays a the latest posts from the specified page's wall. Options: true / false(default)
  * Type - determines which plugin to create. Case insensitive
  * Xid - unique identifier if more than one live-streams are on one page
  *
  * @param {Object} options
  *
  * Example:
    var p = Popcorn('#video')
      .facebook({
        type  : "LIKE-BOX",
        target: "likeboxdiv",
        start : 3,
        end   : 10,
        href  : "http://www.facebook.com/senecacollege",
        show_faces: "true",
        header: "false"
      } )
  * This will show how many people "like" Seneca College's Facebook page, and show their profile pictures
  */

  var ranOnce = false;

  Popcorn.plugin( "facebook" , {
    manifest: {
      about: {
        name: "Popcorn Facebook Plugin",
        version: "0.1",
        author: "Dan Ventura, Matthew Schranz: @mjschranz",
        website: "dsventura.blogspot.com, mschranz.wordpress.com"
      },
      options: {
        type: {
          elem: "select",
          options: [ "LIKE", "LIKE-BOX", "ACTIVITY", "FACEPILE", "LIVE-STREAM", "SEND", "COMMENTS" ],
          label: "Type"
        },
        target: "facebook-container",
        start: {
          elem: "input",
          type: "number",
          label: "In"
        },
        end: {
          elem: "input",
          type: "number",
          label: "Out"
        },
        // optional parameters:
        font: {
          elem: "input",
          type: "text",
          label: "font"
        },
        xid: {
          elem: "input",
          type: "text",
          label: "Xid"
        },
        href: {
          elem: "input",
          type: "url",
          label: "Href"
        },
        site: {
          elem: "input",
          type: "url",
          label:"Site"
        },
        height: {
          elem: "input",
          type: "text",
          label: "Height"
        },
        width: {
          elem: "input",
          type: "text",
          label: "Width"
        },
        action: {
          elem: "select",
          options: [ "like", "recommend" ],
          label: "Action"
        },
        stream: {
          elem: "select",
          options: [ "false", "true" ],
          label: "Stream"
        },
        header: {
          elem: "select",
          options: [ "false", "true" ],
          label: "Header"
        },
        layout: {
          elem: "select",
          options: [ "standard", "button_count", "box_count" ],
          label: "Layout"
        },
        max_rows: {
          elem: "input",
          type: "text",
          label: "Max_rows"
        },
        border_color: {
          elem: "input",
          type: "text",
          label: "Border_color"
        },
        event_app_id: {
          elem: "input",
          type: "text",
          label: "Event_app_id"
        },
        colorscheme: {
           elem: "select",
           options: [ "light", "dark" ],
           label: "Colorscheme"
        },
        show_faces: {
           elem: "select",
           options: [ "false", "true" ],
           label: "Showfaces"
        },
        recommendations: {
           elem: "select",
           options: [ "false", "true" ],
           label: "Recommendations"
        },
        always_post_to_friends: {
          elem: "input",
          options: [ "false", "true" ],
          label: "Always_post_to_friends"
        },
        num_posts: {
          elem: "input",
          type: "text",
          label: "Number_of_Comments"
        }
      }
    },

    _setup: function( options ) {

      var target = document.getElementById( options.target ),
          _type = options.type;

      // facebook script requires a div named fb-root
      if ( !document.getElementById( "fb-root" ) ) {
        var fbRoot = document.createElement( "div" );
        fbRoot.setAttribute( "id", "fb-root" );
        document.body.appendChild( fbRoot );
      }

      if ( !ranOnce || options.event_app_id ) {
        ranOnce = true;
        // initialize facebook JS SDK
        Popcorn.getScript( "//connect.facebook.net/en_US/all.js" );

        global.fbAsyncInit = function() {
          FB.init({
            appId: ( options.event_app_id || "" ),
            status: true,
            cookie: true,
            xfbml: true
          });
        };
      }

      // Lowercase to make value consistent no matter what user inputs
      _type = _type.toLowerCase();

      var validType = function( type ) {
        return ( [ "like", "like-box", "activity", "facepile", "live-stream", "send", "comments" ].indexOf( type ) > -1 );
      };

      // Checks if type is valid
      if ( !validType( _type ) ) {
        throw new Error( "Facebook plugin type was invalid." );
      }

      options._container = document.createElement( "div" );
      options._container.id = "facebookdiv-" + Popcorn.guid();
      options._facebookdiv = document.createElement( "fb:" + _type );
      options._container.appendChild( options._facebookdiv );

      // All the the "types" for facebook share largely identical attributes, for loop suffices.
      // ** Credit to Rick Waldron, it's essentially all his code in this function.
      // activity feed uses 'site' rather than 'href'
      var attr = _type === "activity" ? "site" : "href";

      options._facebookdiv.setAttribute( attr, ( options[ attr ] || document.URL ) );

      // create an array of Facebook widget attributes
      var fbAttrs = (
        "width height layout show_faces stream header colorscheme" +
        " maxrows border_color recommendations font always_post_to_friends xid" +
        " num_posts"
      ).split(" ");

      // For Each that loops through all of our attributes adding them to the divs properties
      Popcorn.forEach( fbAttrs, function( attr ) {
        // Test for null/undef. Allows 0, false & ""
        if ( options[ attr ] != null ) {
          options._facebookdiv.setAttribute( attr, options[ attr ] );
        }
      });

      // Checks if the plugins target container exists
      if ( !target && Popcorn.plugin.debug ) {
        throw new Error( "Facebook target container doesn't exist" );
      }
      target && target.appendChild( options._container );
    },
    /**
    * @member facebook
    * The start function will be executed when the currentTime
    * of the video reaches the start time provided by the
    * options variable
    */
    start: function( event, options ){
      options._container.style.display = "";
    },
    /**
    * @member facebook
    * The end function will be executed when the currentTime
    * of the video reaches the end time provided by the
    * options variable
    */
    end: function( event, options ){
      options._container.style.display = "none";
    },
    _teardown: function( options ){
      var target = document.getElementById( options.target );
      target && target.removeChild( options._container );
    }
  });

})( Popcorn, this );

// PLUGIN: Google Maps
var googleCallback;
(function ( Popcorn ) {

  var i = 1,
    _mapFired = false,
    _mapLoaded = false,
    geocoder, loadMaps;
  //google api callback
  googleCallback = function ( data ) {
    // ensure all of the maps functions needed are loaded
    // before setting _maploaded to true
    if ( typeof google !== "undefined" && google.maps && google.maps.Geocoder && google.maps.LatLng ) {
      geocoder = new google.maps.Geocoder();
      _mapLoaded = true;
    } else {
      setTimeout(function () {
        googleCallback( data );
      }, 1);
    }
  };
  // function that loads the google api
  loadMaps = function () {
    // for some reason the Google Map API adds content to the body
    if ( document.body ) {
      _mapFired = true;
      Popcorn.getScript( "//maps.google.com/maps/api/js?sensor=false&callback=googleCallback" );
    } else {
      setTimeout(function () {
        loadMaps();
      }, 1);
    }
  };

  /**
   * googlemap popcorn plug-in
   * Adds a map to the target div centered on the location specified by the user
   * Options parameter will need a start, end, target, type, zoom, lat and lng, and location
   * -Start is the time that you want this plug-in to execute
   * -End is the time that you want this plug-in to stop executing
   * -Target is the id of the DOM element that you want the map to appear in. This element must be in the DOM
   * -Type [optional] either: HYBRID (default), ROADMAP, SATELLITE, TERRAIN, STREETVIEW
   * -Zoom [optional] defaults to 0
   * -Heading [optional] STREETVIEW orientation of camera in degrees relative to true north (0 north, 90 true east, ect)
   * -Pitch [optional] STREETVIEW vertical orientation of the camera (between 1 and 3 is recommended)
   * -Lat and Lng: the coordinates of the map must be present if location is not specified.
   * -Location: the adress you want the map to display, must be present if lat and lng are not specified.
   * Note: using location requires extra loading time, also not specifying both lat/lng and location will
   * cause and error.
   *
   * Tweening works using the following specifications:
   * -location is the start point when using an auto generated route
   * -tween when used in this context is a string which specifies the end location for your route
   * Note that both location and tween must be present when using an auto generated route, or the map will not tween
   * -interval is the speed in which the tween will be executed, a reasonable time is 1000 ( time in milliseconds )
   * Heading, Zoom, and Pitch streetview values are also used in tweening with the autogenerated route
   *
   * -tween is an array of objects, each containing data for one frame of a tween
   * -position is an object with has two paramaters, lat and lng, both which are mandatory for a tween to work
   * -pov is an object which houses heading, pitch, and zoom paramters, which are all optional, if undefined, these values default to 0
   * -interval is the speed in which the tween will be executed, a reasonable time is 1000 ( time in milliseconds )
   *
   * @param {Object} options
   *
   * Example:
   var p = Popcorn("#video")
   .googlemap({
   start: 5, // seconds
   end: 15, // seconds
   type: "ROADMAP",
   target: "map",
   lat: 43.665429,
   lng: -79.403323
   } )
   *
   */
  Popcorn.plugin( "googlemap", function ( options ) {
    var newdiv, map, location,
        target = document.getElementById( options.target );

    // if this is the firest time running the plugins
    // call the function that gets the sctipt
    if ( !_mapFired ) {
      loadMaps();
    }

    // create a new div this way anything in the target div is left intact
    // this is later passed on to the maps api
    newdiv = document.createElement( "div" );
    newdiv.id = "actualmap" + i;
    newdiv.style.width = "100%";
    newdiv.style.height = "100%";
    i++;

    // ensure the target container the user chose exists
    if ( !target && Popcorn.plugin.debug ) {
      throw new Error( "target container doesn't exist" );
    }
    target && target.appendChild( newdiv );

    // ensure that google maps and its functions are loaded
    // before setting up the map parameters
    var isMapReady = function () {
      if ( _mapLoaded ) {
        if ( options.location ) {
          // calls an anonymous google function called on separate thread
          geocoder.geocode({
            "address": options.location
          }, function ( results, status ) {
            if ( status === google.maps.GeocoderStatus.OK ) {
              options.lat = results[ 0 ].geometry.location.lat();
              options.lng = results[ 0 ].geometry.location.lng();
              location = new google.maps.LatLng( options.lat, options.lng );
              map = new google.maps.Map( newdiv, {
                mapTypeId: google.maps.MapTypeId[ options.type ] || google.maps.MapTypeId.HYBRID
              });
              map.getDiv().style.display = "none";
            }
          });
        } else {
          location = new google.maps.LatLng( options.lat, options.lng );
          map = new google.maps.Map( newdiv, {
            mapTypeId: google.maps.MapTypeId[ options.type ] || google.maps.MapTypeId.HYBRID
          });
          map.getDiv().style.display = "none";
        }
      } else {
          setTimeout(function () {
            isMapReady();
          }, 5);
        }
      };

    isMapReady();

    return {
      /**
       * @member webpage
       * The start function will be executed when the currentTime
       * of the video reaches the start time provided by the
       * options variable
       */
      start: function( event, options ) {
        var that = this,
            sView;

        // ensure the map has been initialized in the setup function above
        var isMapSetup = function() {
          if ( map ) {
            map.getDiv().style.display = "block";
            // reset the location and zoom just in case the user plaid with the map
            google.maps.event.trigger( map, "resize" );
            map.setCenter( location );

            // make sure options.zoom is a number
            if ( options.zoom && typeof options.zoom !== "number" ) {
              options.zoom = +options.zoom;
            }

            options.zoom = options.zoom || 8; // default to 8

            map.setZoom( options.zoom );

            //Make sure heading is a number
            if ( options.heading && typeof options.heading !== "number" ) {
              options.heading = +options.heading;
            }
            //Make sure pitch is a number
            if ( options.pitch && typeof options.pitch !== "number" ) {
              options.pitch = +options.pitch;
            }

            if ( options.type === "STREETVIEW" ) {
              // Switch this map into streeview mode
              map.setStreetView(
              // Pass a new StreetViewPanorama instance into our map

                sView = new google.maps.StreetViewPanorama( newdiv, {
                  position: location,
                  pov: {
                    heading: options.heading = options.heading || 0,
                    pitch: options.pitch = options.pitch || 0,
                    zoom: options.zoom
                  }
                })
              );

              //  Function to handle tweening using a set timeout
              var tween = function( rM, t ) {

                var computeHeading = google.maps.geometry.spherical.computeHeading;
                setTimeout(function() {

                  var current_time = that.media.currentTime;

                  //  Checks whether this is a generated route or not
                  if ( typeof options.tween === "object" ) {

                    for ( var i = 0, m = rM.length; i < m; i++ ) {

                      var waypoint = rM[ i ];

                      //  Checks if this position along the tween should be displayed or not
                      if ( current_time >= ( waypoint.interval * ( i + 1 ) ) / 1000 &&
                         ( current_time <= ( waypoint.interval * ( i + 2 ) ) / 1000 ||
                           current_time >= waypoint.interval * ( m ) / 1000 ) ) {

                        sView3.setPosition( new google.maps.LatLng( waypoint.position.lat, waypoint.position.lng ) );

                        sView3.setPov({
                          heading: waypoint.pov.heading || computeHeading( waypoint, rM[ i + 1 ] ) || 0,
                          zoom: waypoint.pov.zoom || 0,
                          pitch: waypoint.pov.pitch || 0
                        });
                      }
                    }

                    //  Calls the tween function again at the interval set by the user
                    tween( rM, rM[ 0 ].interval );
                  } else {

                    for ( var k = 0, l = rM.length; k < l; k++ ) {

                      var interval = options.interval;

                      if( current_time >= (interval * ( k + 1 ) ) / 1000 &&
                        ( current_time <= (interval * ( k + 2 ) ) / 1000 ||
                          current_time >= interval * ( l ) / 1000 ) ) {

                        sView2.setPov({
                          heading: computeHeading( rM[ k ], rM[ k + 1 ] ) || 0,
                          zoom: options.zoom,
                          pitch: options.pitch || 0
                        });
                        sView2.setPosition( checkpoints[ k ] );
                      }
                    }

                    tween( checkpoints, options.interval );
                  }
                }, t );
              };

              //  Determines if we should use hardcoded values ( using options.tween ),
              //  or if we should use a start and end location and let google generate
              //  the route for us
              if ( options.location && typeof options.tween === "string" ) {

              //  Creating another variable to hold the streetview map for tweening,
              //  Doing this because if there was more then one streetview map, the tweening would sometimes appear in other maps
              var sView2 = sView;

                //  Create an array to store all the lat/lang values along our route
                var checkpoints = [];

                //  Creates a new direction service, later used to create a route
                var directionsService = new google.maps.DirectionsService();

                //  Creates a new direction renderer using the current map
                //  This enables us to access all of the route data that is returned to us
                var directionsDisplay = new google.maps.DirectionsRenderer( sView2 );

                var request = {
                  origin: options.location,
                  destination: options.tween,
                  travelMode: google.maps.TravelMode.DRIVING
                };

                //  Create the route using the direction service and renderer
                directionsService.route( request, function( response, status ) {

                  if ( status == google.maps.DirectionsStatus.OK ) {
                    directionsDisplay.setDirections( response );
                    showSteps( response, that );
                  }

                });

                var showSteps = function ( directionResult, that ) {

                  //  Push new google map lat and lng values into an array from our list of lat and lng values
                  var routes = directionResult.routes[ 0 ].overview_path;
                  for ( var j = 0, k = routes.length; j < k; j++ ) {
                    checkpoints.push( new google.maps.LatLng( routes[ j ].lat(), routes[ j ].lng() ) );
                  }

                  //  Check to make sure the interval exists, if not, set to a default of 1000
                  options.interval = options.interval || 1000;
                  tween( checkpoints, 10 );

                };
              } else if ( typeof options.tween === "object" ) {

                //  Same as the above to stop streetview maps from overflowing into one another
                var sView3 = sView;

                for ( var i = 0, l = options.tween.length; i < l; i++ ) {

                  //  Make sure interval exists, if not, set to 1000
                  options.tween[ i ].interval = options.tween[ i ].interval || 1000;
                  tween( options.tween, 10 );
                }
              }
            }
          } else {
            setTimeout(function () {
              isMapSetup();
            }, 13);
          }
        };
        isMapSetup();
      },
      /**
       * @member webpage
       * The end function will be executed when the currentTime
       * of the video reaches the end time provided by the
       * options variable
       */
      end: function ( event, options ) {
        // if the map exists hide it do not delete the map just in
        // case the user seeks back to time b/w start and end
        if ( map ) {
          map.getDiv().style.display = "none";
        }
      },
      _teardown: function ( options ) {

        var target = document.getElementById( options.target );

        // the map must be manually removed
        target && target.removeChild( newdiv );
        newdiv = map = location = null;
      }
    };
  }, {
    about: {
      name: "Popcorn Google Map Plugin",
      version: "0.1",
      author: "@annasob",
      website: "annasob.wordpress.com"
    },
    options: {
      start: {
        elem: "input",
        type: "text",
        label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      target: "map-container",
      type: {
        elem: "select",
        options: [ "ROADMAP", "SATELLITE", "STREETVIEW", "HYBRID", "TERRAIN" ],
        label: "Type"
      },
      zoom: {
        elem: "input",
        type: "text",
        label: "Zoom"
      },
      lat: {
        elem: "input",
        type: "text",
        label: "Lat"
      },
      lng: {
        elem: "input",
        type: "text",
        label: "Lng"
      },
      location: {
        elem: "input",
        type: "text",
        label: "Location"
      },
      heading: {
        elem: "input",
        type: "text",
        label: "Heading"
      },
      pitch: {
        elem: "input",
        type: "text",
        label: "Pitch"
      }
    }
  });
})( Popcorn );

// PLUGIN: IMAGE

(function ( Popcorn ) {

/**
 * Images popcorn plug-in
 * Shows an image element
 * Options parameter will need a start, end, href, target and src.
 * Start is the time that you want this plug-in to execute
 * End is the time that you want this plug-in to stop executing
 * href is the url of the destination of a link - optional
 * Target is the id of the document element that the iframe needs to be attached to,
 * this target element must exist on the DOM
 * Src is the url of the image that you want to display
 * text is the overlayed text on the image - optional
 *
 * @param {Object} options
 *
 * Example:
   var p = Popcorn('#video')
      .image({
        start: 5, // seconds
        end: 15, // seconds
        href: 'http://www.drumbeat.org/',
        src: 'http://www.drumbeat.org/sites/default/files/domain-2/drumbeat_logo.png',
        text: 'DRUMBEAT',
        target: 'imagediv'
      } )
 *
 */
  Popcorn.plugin( "image", {
      manifest: {
        about: {
          name: "Popcorn image Plugin",
          version: "0.1",
          author: "Scott Downe",
          website: "http://scottdowne.wordpress.com/"
        },
        options: {
          start: {
            elem: "input",
            type: "number",
            label: "In"
          },
          end: {
            elem: "input",
            type: "number",
            label: "Out"
          },
          href: {
            elem: "input",
            type: "url",
            label: "Link URL"
          },
          target: "image-container",
          src: {
            elem: "input",
            type: "url",
            label: "Source URL"
          },
          text: {
            elem: "input",
            type: "text",
            label: "TEXT"
          }
        }
      },
      _setup: function( options ) {
        var img = document.createElement( "img" ),
            target = document.getElementById( options.target );

        options.link = document.createElement( "a" );
        options.link.style.position = "relative";
        options.link.style.textDecoration = "none";


        if ( !target && Popcorn.plugin.debug ) {
          throw new Error( "target container doesn't exist" );
        }
        // add the widget's div to the target div
        target && target.appendChild( options.link );

        img.addEventListener( "load", function() {

          // borders look really bad, if someone wants it they can put it on their div target
          img.style.borderStyle = "none";

          if ( options.href ) {
            options.link.href = options.href;
          }

          options.link.target = "_blank";

          var fontHeight = ( img.height / 12 ) + "px",
              divText = document.createElement( "div" );

          Popcorn.extend( divText.style, {

            color: "black",
            fontSize: fontHeight,
            fontWeight: "bold",
            position: "relative",
            textAlign: "center",
            width: img.width + "px",
            zIndex: "10"
          });

          divText.innerHTML = options.text || "";
          options.link.appendChild( divText );
          options.link.appendChild( img );
          divText.style.top = ( img.height / 2 ) - ( divText.offsetHeight / 2 ) + "px";
          options.link.style.display = "none";
        }, false );

        img.src = options.src;
      },

      /**
       * @member image
       * The start function will be executed when the currentTime
       * of the video  reaches the start time provided by the
       * options variable
       */
      start: function( event, options ) {
        options.link.style.display = "block";
      },
      /**
       * @member image
       * The end function will be executed when the currentTime
       * of the video  reaches the end time provided by the
       * options variable
       */
      end: function( event, options ) {
        options.link.style.display = "none";
      },
      _teardown: function( options ) {
        document.getElementById( options.target ) && document.getElementById( options.target ).removeChild( options.link );
      }
  });
})( Popcorn );
// PLUGIN: GML
(function( Popcorn ) {

  var gmlPlayer = function( $p ) {

        var _stroke = 0,
            onPt = 0,
            onStroke = 0,
            x = null,
            y = null,
            rotation = false,
            strokes = 0,
            play = function() {},
            reset = function() {

              $p.background( 0 );
              onPt = onStroke = 0;
              x = y = null;
            },
            drawLine = function( x, y, x2, y2 ) {

              var _x, _y, _x2, _y2;

              if ( rotation ) {

                _x  = y * $p.height;
                _y  = $p.width - ( x * $p.width );
                _x2 = y2 * $p.height;
                _y2 = $p.width - ( x2 * $p.width );
              } else {

                _x  = x * $p.width;
                _y  = y * $p.height;
                _x2 = x2 * $p.width;
                _y2 = y2 * $p.height;
              }

              $p.stroke( 0 );
              $p.strokeWeight( 13 );
              $p.strokeCap( $p.SQUARE );
              $p.line( _x, _y, _x2, _y2 );
              $p.stroke( 255 );
              $p.strokeWeight( 12 );
              $p.strokeCap( $p.ROUND );
              $p.line( _x, _y, _x2, _y2 );
            },
            seek = function( point ) {

              ( point < onPt ) && reset();

              while ( onPt <= point ) {

                if ( !strokes ) {
                  return;
                }

                _stroke = strokes[ onStroke ] || strokes;
                var pt = _stroke.pt[ onPt ],
                    p = onPt;
                x != null && drawLine( x, y, pt.x, pt.y );

                x = pt.x;
                y = pt.y;
                ( onPt === p ) && onPt++;
              }
            };

        $p.draw = function() {

          play();
        };
        $p.setup = function() {};
        $p.construct = function( media, data, options ) {

          var dataReady = function() {

            if ( data ) {

              strokes = data.gml.tag.drawing.stroke;

              var drawingDur = ( options.end - options.start ) / ( strokes.pt || (function( strokes ) {

                var rStrokes = [];

                for ( var i = 0, sl = strokes.length; i < sl; i++ ) {

                  rStrokes = rStrokes.concat( strokes[ i ].pt );
                }

                return rStrokes;
              })( strokes ) ).length;

              var tag = data.gml.tag,
                  app_name =  tag.header && tag.header.client && tag.header.client.name;

              rotation = app_name === "Graffiti Analysis 2.0: DustTag" ||
                         app_name === "DustTag: Graffiti Analysis 2.0" ||
                         app_name === "Fat Tag - Katsu Edition";

              play = function() {

                if ( media.currentTime < options.endDrawing ) {

                  seek( ( media.currentTime - options.start ) / drawingDur );
                }
              };

              return;
            }

            setTimeout( dataReady, 5 );
          };

          $p.size( 640, 640 );
          $p.frameRate( 60 );
          $p.smooth();
          reset();
          $p.noLoop();

          dataReady();
        };
      };

  /**
   * Grafiti markup Language (GML) popcorn plug-in
   * Renders a GML tag inside an HTML element
   * Options parameter will need a mandatory start, end, target, gmltag.
   * Optional parameters: none.
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Target is the id of the document element that you wish to render the grafiti in
   * gmltag is the numerical reference to a gml tag via 000000book.com
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
       .gml({
         start: 0, // seconds
         end: 5, // seconds
         gmltag: '29582',
         target: 'gmldiv'
       });
   *
   */
  Popcorn.plugin( "gml" , {

    _setup: function( options ) {

      var self = this,
          target = document.getElementById( options.target );

      options.endDrawing = options.endDrawing || options.end;

      // create a canvas to put in the target div
      options.container = document.createElement( "canvas" );

      options.container.style.display = "none";
      options.container.setAttribute( "id", "canvas" + options.gmltag );

      if ( !target && Popcorn.plugin.debug ) {
        throw new Error( "target container doesn't exist" );
      }
      target && target.appendChild( options.container );

      var scriptReady = function() {
        Popcorn.getJSONP( "//000000book.com/data/" + options.gmltag + ".json?callback=", function( data ) {

          options.pjsInstance = new Processing( options.container, gmlPlayer );
          options.pjsInstance.construct( self.media, data, options );
          options._running && options.pjsInstance.loop();
        }, false );
      };

      if ( !window.Processing ) {

        Popcorn.getScript( "//processingjs.org/content/download/processing-js-1.3.0/processing-1.3.0.min.js", scriptReady );
      } else {

        scriptReady();
      }

    },
    /**
     * @member gml
     * The start function will be executed when the currentTime
     * of the video  reaches the start time provided by the
     * options variable
     */
    start: function( event, options ) {

      options.pjsInstance && options.pjsInstance.loop();
      options.container.style.display = "block";
    },
    /**
     * @member gml
     * The end function will be executed when the currentTime
     * of the video  reaches the end time provided by the
     * options variable
     */
    end: function( event, options ) {

      options.pjsInstance && options.pjsInstance.noLoop();
      options.container.style.display = "none";
    },
    _teardown: function( options ) {

      options.pjsInstance && options.pjsInstance.exit();
      document.getElementById( options.target ) && document.getElementById( options.target ).removeChild( options.container );
    }
  });
})( Popcorn );
// PLUGIN: LASTFM

(function ( Popcorn ) {

  var _artists = {},
      lastFMcallback = function( data ) {
        if ( data.artist ) {
          var htmlString = "";

          htmlString = "<h3>" + data.artist.name + "</h3>";
          htmlString += "<a href='" + data.artist.url + "' target='_blank' style='float:left;margin:0 10px 0 0;'><img src='" + data.artist.image[ 2 ][ "#text"] + "' alt=''></a>";
          htmlString += "<p>" + data.artist.bio.summary + "</p>";
          htmlString += "<hr /><p><h4>Tags</h4><ul>";

          Popcorn.forEach( data.artist.tags.tag, function( val, i) {
            htmlString += "<li><a href='" + val.url + "'>" + val.name + "</a></li>";
          });

          htmlString += "</ul></p>";
          htmlString += "<hr /><p><h4>Similar</h4><ul>";

          Popcorn.forEach( data.artist.similar.artist, function( val, i) {
            htmlString += "<li><a href='" + val.url + "'>" + val.name + "</a></li>";
          });

          htmlString += "</ul></p>";

          _artists[ data.artist.name.toLowerCase() ].htmlString = htmlString;
        }
      };

  /**
   * LastFM popcorn plug-in
   * Appends information about a LastFM artist to an element on the page.
   * Options parameter will need a start, end, target, artist and apikey.
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Artist is the name of who's LastFM information you wish to show
   * Target is the id of the document element that the images are
   *  appended to, this target element must exist on the DOM
   * ApiKey is the API key registered with LastFM for use with their API
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .lastfm({
          start:          5,                                    // seconds, mandatory
          end:            15,                                   // seconds, mandatory
          artist:         'yacht',                              // mandatory
          target:         'lastfmdiv',                          // mandatory
          apikey:         '1234567890abcdef1234567890abcdef'    // mandatory
        } )
   *
   */
  Popcorn.plugin( "lastfm" , (function(){


    return {

      _setup: function( options ) {
        options._container = document.createElement( "div" );
        options._container.style.display = "none";
        options._container.innerHTML = "";
        options.artist = options.artist && options.artist.toLowerCase() || "";

        var target = document.getElementById( options.target );

        if ( !target && Popcorn.plugin.debug ) {
          throw new Error( "target container doesn't exist" );
        }
        target && target.appendChild( options._container );

        if ( !_artists[ options.artist ] ) {

          _artists[ options.artist ] = {
            count: 0,
            htmlString: "Unknown Artist"
          };
          Popcorn.getJSONP( "//ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist=" + options.artist + "&api_key=" + options.apikey + "&format=json&callback=lastFMcallback", lastFMcallback, false );
        }
        _artists[ options.artist ].count++;

      },
      /**
       * @member LastFM
       * The start function will be executed when the currentTime
       * of the video  reaches the start time provided by the
       * options variable
       */
      start: function( event, options ) {
        options._container.innerHTML = _artists[ options.artist ].htmlString;
        options._container.style.display = "inline";
      },
      /**
       * @member LastFM
       * The end function will be executed when the currentTime
       * of the video  reaches the end time provided by the
       * options variable
       */
      end: function( event, options ) {
        options._container.style.display = "none";
        options._container.innerHTML = "";
      },
      _teardown: function( options ) {
        // cleaning possible reference to _artist array;
        --_artists[ options.artist ].count || delete _artists[ options.artist ];
        document.getElementById( options.target ) && document.getElementById( options.target ).removeChild( options._container );
      }
    };
  })(),
  {
    about:{
      name: "Popcorn LastFM Plugin",
      version: "0.1",
      author: "Steven Weerdenburg",
      website: "http://sweerdenburg.wordpress.com/"
    },
    options: {
      start: {
        elem: "input",
        type: "text",
        label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      target: "lastfm-container",
      artist: {
        elem: "input",
        type: "text",
        label: "Artist"
      }
    }
  });

})( Popcorn );
// PLUGIN: lowerthird
(function ( Popcorn ) {

  /**
   * Lower Third popcorn plug-in
   * Displays information about a speaker over the video, or in the target div
   * Options parameter will need a start, and end.
   * Optional parameters are target, salutation, name and role.
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Target is the id of the document element that the content is
   *  appended to, this target element must exist on the DOM
   * salutation is the speaker's Mr. Ms. Dr. etc.
   * name is the speaker's name.
   * role is information about the speaker, example Engineer.
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .lowerthird({
          start:          5,                 // seconds, mandatory
          end:            15,                // seconds, mandatory
          salutation:     'Mr',              // optional
          name:           'Scott Downe',     // optional
          role:           'Programmer',      // optional
          target:         'subtitlediv'      // optional
        } )
   *
   */

  Popcorn.plugin( "lowerthird", {

      manifest: {
        about:{
          name: "Popcorn lowerthird Plugin",
          version: "0.1",
          author: "Scott Downe",
          website: "http://scottdowne.wordpress.com/"
        },
        options:{
          start: {
            elem: "input",
            type: "text",
            label: "In"
          },
          end: {
            elem: "input",
            type: "text",
            label: "Out"
          },
          target: "lowerthird-container",
          salutation : {
            elem: "input",
            type: "text",
            label: "Text"
          },
          name: {
            elem: "input",
            type: "text",
            label: "Text"
          },
          role: {
            elem: "input",
            type: "text",
            label: "Text"
          }
        }
      },

      _setup: function( options ) {

        var target = document.getElementById( options.target );

        // Creates a div for all Lower Thirds to use
        if ( !this.container ) {
          this.container = document.createElement( "div" );

          this.container.style.position = "absolute";
          this.container.style.color = "white";
          this.container.style.textShadow = "black 2px 2px 6px";
          this.container.style.fontSize = "24px";
          this.container.style.fontWeight = "bold";
          this.container.style.paddingLeft = "40px";

          // the video element must have height and width defined
          this.container.style.width = this.video.offsetWidth + "px";
          this.container.style.left = this.position().left + "px";

          this.video.parentNode.appendChild( this.container );
        }

        // if a target is specified, use that
        if ( options.target && options.target !== "lowerthird-container" ) {
          options.container = document.createElement( "div" );
          if ( !target && Popcorn.plugin.debug ) {
            throw new Error( "target container doesn't exist" );
          }
          target && target.appendChild( options.container );
        // use shared default container
        } else {
          options.container = this.container;
        }

      },
      /**
       * @member lowerthird
       * The start function will be executed when the currentTime
       * of the video reaches the start time provided by the
       * options variable
       */
      start: function(event, options){
        options.container.innerHTML = ( options.salutation ? options.salutation + " " : "" ) + options.name + ( options.role ? "<br />" + options.role : "" );
        this.container.style.top = this.position().top + this.video.offsetHeight - ( 40 + this.container.offsetHeight ) + "px";
      },
      /**
       * @member lowerthird
       * The end function will be executed when the currentTime
       * of the video reaches the end time provided by the
       * options variable
       */
      end: function( event, options ) {
        options.container.innerHTML = "";
      }

  });
})( Popcorn );
// PLUGIN: Google Feed
(function ( Popcorn ) {

  var i = 1,
      scriptLoaded  = false,

  dynamicFeedLoad = function() {
    var dontLoad = false,
        k = 0,
        links = document.getElementsByTagName( "link" ),
        len = links.length,
        head = document.head || document.getElementsByTagName( "head" )[ 0 ],
        css = document.createElement( "link" ),
        resource = "//www.google.com/uds/solutions/dynamicfeed/gfdynamicfeedcontrol.";

    if ( !window.GFdynamicFeedControl ) {

      Popcorn.getScript( resource + "js", function() {
        scriptLoaded = true;
      });

    } else {
      scriptLoaded = true;
    }

    //  Checking if the css file is already included
    for ( ; k < len; k++ ){
      if ( links[ k ].href === resource + "css" ) {
        dontLoad = true;
      }
    }

    if ( !dontLoad ) {
      css.type = "text/css";
      css.rel = "stylesheet";
      css.href =  resource + "css";
      head.insertBefore( css, head.firstChild );
    }
  };

  if ( !window.google ) {

    Popcorn.getScript( "//www.google.com/jsapi", function() {

      google.load( "feeds", "1", {

        callback: function () {

          dynamicFeedLoad();
        }
      });
    });

  } else {
    dynamicFeedLoad();
  }

  /**
   * googlefeed popcorn plug-in
   * Adds a feed from the specified blog url at the target div
   * Options parameter will need a start, end, target, url and title
   * -Start is the time that you want this plug-in to execute
   * -End is the time that you want this plug-in to stop executing
   * -Target is the id of the DOM element that you want the map to appear in. This element must be in the DOM
   * -Url is the url of the blog's feed you are trying to access
   * -Title is the title of the blog you want displayed above the feed
   * -Orientation is the orientation of the blog, accepts either Horizontal or Vertical, defaults to Vertical
   * @param {Object} options
   *
   * Example:
    var p = Popcorn("#video")
      .googlefeed({
       start: 5, // seconds
       end: 15, // seconds
       target: "map",
       url: "http://zenit.senecac.on.ca/~chris.tyler/planet/rss20.xml",
       title: "Planet Feed"
    } )
  *
  */

  Popcorn.plugin( "googlefeed", function( options ) {

    // create a new div and append it to the parent div so nothing
    // that already exists in the parent div gets overwritten
    var newdiv = document.createElement( "div" ),
        target = document.getElementById( options.target ),
    initialize = function() {
      //ensure that the script has been loaded
      if ( !scriptLoaded ) {
        setTimeout( function () {
          initialize();
        }, 5 );
      } else {
        // Create the feed control using the user entered url and title
        options.feed = new GFdynamicFeedControl( options.url, newdiv, {
          vertical: options.orientation.toLowerCase() === "vertical" ? true : false,
          horizontal: options.orientation.toLowerCase() === "horizontal" ? true : false,
          title: options.title = options.title || "Blog"
        });
      }
    };

    // Default to vertical orientation if empty or incorrect input
    if( !options.orientation || ( options.orientation.toLowerCase() !== "vertical" &&
      options.orientation.toLowerCase() !== "horizontal" ) ) {
      options.orientation = "vertical";
    }

    newdiv.style.display = "none";
    newdiv.id = "_feed" + i;
    newdiv.style.width = "100%";
    newdiv.style.height = "100%";
    i++;

    if ( !target && Popcorn.plugin.debug ) {
      throw new Error( "target container doesn't exist" );
    }
    target && target.appendChild( newdiv );

    initialize();

    return {
      /**
       * @member webpage
       * The start function will be executed when the currentTime
       * of the video reaches the start time provided by the
       * options variable
       */
      start: function( event, options ){
        newdiv.setAttribute( "style", "display:inline" );
      },
      /**
       * @member webpage
       * The end function will be executed when the currentTime
       * of the video reaches the end time provided by the
       * options variable
       */
      end: function( event, options ){
        newdiv.setAttribute( "style", "display:none" );
      },
      _teardown: function( options ) {
        document.getElementById( options.target ) && document.getElementById( options.target ).removeChild( newdiv );
        delete options.feed;
      }
    };
  },
  {
    about: {
      name: "Popcorn Google Feed Plugin",
      version: "0.1",
      author: "David Seifried",
      website: "dseifried.wordpress.com"
    },
    options: {
      start: {
        elem: "input",
        type: "text",
        label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      target: "feed-container",
      url: {
        elem: "input",
        type: "url",
        label: "url"
      },
      title: {
        elem: "input",
        type: "text",
        label: "title"
      },
      orientation: {
        elem: "select",
        options: [ "Vertical", "Horizontal" ],
        label: "orientation"
      }
    }
  });
})( Popcorn );
// PLUGIN: Subtitle

(function ( Popcorn ) {

  var i = 0,
      createDefaultContainer = function( context ) {

        var ctxContainer = context.container = document.createElement( "div" ),
            style = ctxContainer.style,
            media = context.media;

        var updatePosition = function() {
          var position = context.position();
          // the video element must have height and width defined
          style.fontSize = "18px";
          style.width = media.offsetWidth + "px";
          style.top = position.top  + media.offsetHeight - ctxContainer.offsetHeight - 40 + "px";
          style.left = position.left + "px";

          setTimeout( updatePosition, 10 );
        };

        ctxContainer.id = Popcorn.guid();
        style.position = "absolute";
        style.color = "white";
        style.textShadow = "black 2px 2px 6px";
        style.fontWeight = "bold";
        style.textAlign = "center";

        updatePosition();

        context.media.parentNode.appendChild( ctxContainer );
      };

  /**
   * Subtitle popcorn plug-in
   * Displays a subtitle over the video, or in the target div
   * Options parameter will need a start, and end.
   * Optional parameters are target and text.
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Target is the id of the document element that the content is
   *  appended to, this target element must exist on the DOM
   * Text is the text of the subtitle you want to display.
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .subtitle({
          start:            5,                 // seconds, mandatory
          end:              15,                // seconds, mandatory
          text:             'Hellow world',    // optional
          target:           'subtitlediv',     // optional
        } )
   *
   */

  Popcorn.plugin( "subtitle" , {

      manifest: {
        about: {
          name: "Popcorn Subtitle Plugin",
          version: "0.1",
          author: "Scott Downe",
          website: "http://scottdowne.wordpress.com/"
        },
        options: {
          start: {
            elem: "input",
            type: "text",
            label: "In"
          },
          end: {
            elem: "input",
            type: "text",
            label: "Out"
          },
          target: "subtitle-container",
          text: {
            elem: "input",
            type: "text",
            label: "Text"
          }
        }
      },

      _setup: function( options ) {
        var newdiv = document.createElement( "div" );

        newdiv.id = "subtitle-" + i++;
        newdiv.style.display = "none";

        // Creates a div for all subtitles to use
        ( !this.container && ( !options.target || options.target === "subtitle-container" ) ) &&
          createDefaultContainer( this );

        // if a target is specified, use that
        if ( options.target && options.target !== "subtitle-container" ) {
          options.container = document.getElementById( options.target );
        } else {
          // use shared default container
          options.container = this.container;
        }

        document.getElementById( options.container.id ) && document.getElementById( options.container.id ).appendChild( newdiv );
        options.innerContainer = newdiv;

        options.showSubtitle = function() {
          options.innerContainer.innerHTML = options.text || "";
        };
      },
      /**
       * @member subtitle
       * The start function will be executed when the currentTime
       * of the video  reaches the start time provided by the
       * options variable
       */
      start: function( event, options ){
        options.innerContainer.style.display = "inline";
        options.showSubtitle( options, options.text );
      },
      /**
       * @member subtitle
       * The end function will be executed when the currentTime
       * of the video  reaches the end time provided by the
       * options variable
       */
      end: function( event, options ) {
        options.innerContainer.style.display = "none";
        options.innerContainer.innerHTML = "";
      },

      _teardown: function ( options ) {
        options.container.removeChild( options.innerContainer );
      }

  });

})( Popcorn );
// PLUGIN: tagthisperson

(function ( Popcorn ) {

  var peopleArray = [];
  // one People object per options.target
  var People = function() {
    this.name = "";
    this.contains = { };
    this.toString = function() {
      var r = [];
      for ( var j in this.contains ) {
        if ( this.contains.hasOwnProperty( j ) ) {
          r.push( " " + this.contains[ j ] );
        }
      }
      return r.toString();
    };
  };

  /**
   * tagthisperson popcorn plug-in
   * Adds people's names to an element on the page.
   * Options parameter will need a start, end, target, image and person.
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Person is the name of the person who you want to tag
   * Image is the url to the image of the person - optional
   * href is the url to the webpage of the person - optional
   * Target is the id of the document element that the text needs to be
   * attached to, this target element must exist on the DOM
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .tagthisperson({
          start: 5, // seconds
          end: 15, // seconds
          person: '@annasob',
          image:  'http://newshour.s3.amazonaws.com/photos%2Fspeeches%2Fguests%2FRichardNSmith_thumbnail.jpg',
          href:   'http://annasob.wordpress.com',
          target: 'tagdiv'
        } )
   *
   */
  Popcorn.plugin( "tagthisperson" , ( function() {

    return {

      _setup: function( options ) {
        var exists = false,
            target = document.getElementById( options.target );

        if ( !target && Popcorn.plugin.debug ) {
          throw new Error( "target container doesn't exist" );
        }

        // loop through the existing objects to ensure no duplicates
        // the idea here is to have one object per unique options.target
        for ( var i = 0; i < peopleArray.length; i++ ) {
          if ( peopleArray[ i ].name === options.target ) {
            options._p = peopleArray[ i ];
            exists = true;
            break;
          }
        }
        if ( !exists ) {
          options._p = new People();
          options._p.name = options.target;
          peopleArray.push( options._p );
        }
      },
      /**
       * @member tagthisperson
       * The start function will be executed when the currentTime
       * of the video  reaches the start time provided by the
       * options variable
       */
      start: function( event, options ){
        options._p.contains[ options.person ] = ( options.image ) ? "<img src='" + options.image + "'/> " : "" ;
        options._p.contains[ options.person ] += ( options.href ) ? "<a href='" + options.href + "' target='_blank'> " + options.person + "</a>" : options.person ;

        document.getElementById( options.target ).innerHTML = options._p.toString();
      },
      /**
       * @member tagthisperson
       * The end function will be executed when the currentTime
       * of the video  reaches the end time provided by the
       * options variable
       */
      end: function( event, options ){
        delete options._p.contains[ options.person ];

        document.getElementById( options.target ).innerHTML = options._p.toString();
      }
   };
  })(),
  {
    about:{
      name: "Popcorn tagthisperson Plugin",
      version: "0.1",
      author: "@annasob",
      website: "annasob.wordpress.com"
    },
    options:{
      start: {
        elem: "input",
        type: "text",
        label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      target : "tagthisperson-container",
      person: {
        elem: "input",
        type: "text",
        label: "Name"
      },
      image: {
        elem: "input",
        type: "url",
        label: "Image Src"
      },
      href: {
        elem: "input",
        type: "url",
        label: "URL"
      }
    }
  });

})( Popcorn );
// PLUGIN: TWITTER

(function ( Popcorn ) {
  var scriptLoading = false;

  /**
   * Twitter popcorn plug-in
   * Appends a Twitter widget to an element on the page.
   * Options parameter will need a start, end, target and source.
   * Optional parameters are height and width.
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Src is the hash tag or twitter user to get tweets from
   * Target is the id of the document element that the images are
   *  appended to, this target element must exist on the DOM
   * Height is the height of the widget, defaults to 200
   * Width is the width of the widget, defaults to 250
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .twitter({
          start:          5,                // seconds, mandatory
          end:            15,               // seconds, mandatory
          src:            '@stevesong',     // mandatory, also accepts hash tags
          height:         200,              // optional
          width:          250,              // optional
          target:         'twitterdiv'      // mandatory
        } )
   *
   */

  Popcorn.plugin( "twitter" , {

      manifest: {
        about: {
          name: "Popcorn Twitter Plugin",
          version: "0.1",
          author: "Scott Downe",
          website: "http://scottdowne.wordpress.com/"
        },
        options:{
          start: {
            elem: "input",
            type: "number",
            label: "In"
          },
          end: {
            elem: "input",
            type: "number",
            label: "Out"
          },
          src: {
            elem: "input",
            type: "text",
            label: "Source"
          },
          target: "twitter-container",
          height: {
            elem: "input",
            type: "number",
            label: "Height"
          },
          width: {
            elem: "input",
            type: "number",
            label: "Width"
          }
        }
      },

      _setup: function( options ) {

        if ( !window.TWTR && !scriptLoading ) {
          scriptLoading = true;
          Popcorn.getScript( "//widgets.twimg.com/j/2/widget.js" );
        }

        var target = document.getElementById( options.target );
        // create the div to store the widget
        // setup widget div that is unique per track
        options.container = document.createElement( "div" );
        // use this id to connect it to the widget
        options.container.setAttribute( "id", Popcorn.guid() );
        // display none by default
        options.container.style.display = "none";

        if ( !target && Popcorn.plugin.debug ) {
          throw new Error( "target container doesn't exist" );
        }
         // add the widget's div to the target div
        target && target.appendChild( options.container );

        // setup info for the widget
        var src = options.src || "",
            width = options.width || 250,
            height = options.height || 200,
            profile = /^@/.test( src ),
            widgetOptions = {
              version: 2,
              // use this id to connect it to the div
              id: options.container.getAttribute( "id" ),
              rpp: 30,
              width: width,
              height: height,
              interval: 6000,
              theme: {
                shell: {
                  background: "#ffffff",
                  color: "#000000"
                },
                tweets: {
                  background: "#ffffff",
                  color: "#444444",
                  links: "#1985b5"
                }
              },
              features: {
                loop: true,
                timestamp: true,
                avatars: true,
                hashtags: true,
                toptweets: true,
                live: true,
                scrollbar: false,
                behavior: 'default'
              }
            };

        // create widget
        var isReady = function( that ) {
          if ( window.TWTR ) {
            if ( profile ) {

              widgetOptions.type = "profile";

              new TWTR.Widget( widgetOptions ).render().setUser( src ).start();

            } else {

              widgetOptions.type = "search";
              widgetOptions.search = src;
              widgetOptions.subject = src;

              new TWTR.Widget( widgetOptions ).render().start();

            }
          } else {
            setTimeout( function() {
              isReady( that );
            }, 1);
          }
        };

        isReady( this );
      },

      /**
       * @member Twitter
       * The start function will be executed when the currentTime
       * of the video  reaches the start time provided by the
       * options variable
       */
      start: function( event, options ) {
        options.container.style.display = "inline";
      },

      /**
       * @member Twitter
       * The end function will be executed when the currentTime
       * of the video  reaches the end time provided by the
       * options variable
       */
      end: function( event, options ) {
        options.container.style.display = "none";
      },
      _teardown: function( options ) {

        document.getElementById( options.target ) && document.getElementById( options.target ).removeChild( options.container );
      }
    });

})( Popcorn );
// PLUGIN: WEBPAGE

(function ( Popcorn ) {

  /**
   * Webpages popcorn plug-in
   * Creates an iframe showing a website specified by the user
   * Options parameter will need a start, end, id, target and src.
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Id is the id that you want assigned to the iframe
   * Target is the id of the document element that the iframe needs to be attached to,
   * this target element must exist on the DOM
   * Src is the url of the website that you want the iframe to display
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .webpage({
          id: "webpages-a",
          start: 5, // seconds
          end: 15, // seconds
          src: 'http://www.webmademovies.org',
          target: 'webpagediv'
        } )
   *
   */
  Popcorn.plugin( "webpage" , {
    manifest: {
      about: {
        name: "Popcorn Webpage Plugin",
        version: "0.1",
        author: "@annasob",
        website: "annasob.wordpress.com"
      },
      options: {
        id: {
          elem: "input",
          type: "text",
          label: "Id"
        },
        start: {
          elem: "input",
          type: "text",
          label: "In"
        },
        end: {
          elem: "input",
          type: "text",
          label: "Out"
        },
        src: {
          elem: "input",
          type: "url",
          label: "Src"
        },
        target: "iframe-container"
      }
    },
    _setup: function( options ) {

      var target = document.getElementById( options.target );

      // make src an iframe acceptable string
      options.src = options.src.replace( /^(https?:)?(\/\/)?/, "//" );

      // make an iframe
      options._iframe = document.createElement( "iframe" );
      options._iframe.setAttribute( "width", "100%" );
      options._iframe.setAttribute( "height", "100%" );
      options._iframe.id = options.id;
      options._iframe.src = options.src;
      options._iframe.style.display = "none";

      if ( !target && Popcorn.plugin.debug ) {
        throw new Error( "target container doesn't exist" );
      }

      // add the hidden iframe to the DOM
      target && target.appendChild( options._iframe );

    },
    /**
     * @member webpage
     * The start function will be executed when the currentTime
     * of the video  reaches the start time provided by the
     * options variable
     */
    start: function( event, options ){
      // make the iframe visible
      options._iframe.src = options.src;
      options._iframe.style.display = "inline";
    },
    /**
     * @member webpage
     * The end function will be executed when the currentTime
     * of the video  reaches the end time provided by the
     * options variable
     */
    end: function( event, options ){
      // make the iframe invisible
      options._iframe.style.display = "none";
    },
    _teardown: function( options ) {

      document.getElementById( options.target ) && document.getElementById( options.target ).removeChild( options._iframe );
    }
  });
})( Popcorn );
// PLUGIN: WIKIPEDIA


var wikiCallback;

(function ( Popcorn ) {

  /**
   * Wikipedia popcorn plug-in
   * Displays a wikipedia aricle in the target specified by the user by using
   * new DOM element instead overwriting them
   * Options parameter will need a start, end, target, lang, src, title and numberofwords.
   * -Start is the time that you want this plug-in to execute
   * -End is the time that you want this plug-in to stop executing
   * -Target is the id of the document element that the text from the article needs to be
   * attached to, this target element must exist on the DOM
   * -Lang (optional, defaults to english) is the language in which the article is in.
   * -Src is the url of the article
   * -Title (optional) is the title of the article
   * -numberofwords (optional, defaults to 200) is  the number of words you want displaid.
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn("#video")
        .wikipedia({
          start: 5, // seconds
          end: 15, // seconds
          src: "http://en.wikipedia.org/wiki/Cape_Town",
          target: "wikidiv"
        } )
   *
   */
  Popcorn.plugin( "wikipedia" , {

    manifest: {
      about:{
        name: "Popcorn Wikipedia Plugin",
        version: "0.1",
        author: "@annasob",
        website: "annasob.wordpress.com"
      },
      options:{
        start: {
          elem: "input",
          type: "text",
          label: "In"
        },
        end: {
          elem: "input",
          type: "text",
          label: "Out"
        },
        lang: {
          elem: "input",
          type: "text",
          label: "Language"
        },
        src: {
          elem: "input",
          type: "url",
          label: "Src"
        },
        title: {
          elem: "input",
          type: "text",
          label: "Title"
        },
        numberofwords: {
          elem: "input",
          type: "text",
          label: "Num Of Words"
        },
        target: "wikipedia-container"
      }
    },
    /**
     * @member wikipedia
     * The setup function will get all of the needed
     * items in place before the start function is called.
     * This includes getting data from wikipedia, if the data
     * is not received and processed before start is called start
     * will not do anything
     */
    _setup : function( options ) {
      // declare needed variables
      // get a guid to use for the global wikicallback function
      var  _text, _guid = Popcorn.guid();

      // if the user didn't specify a language default to english
      if ( !options.lang ) {
        options.lang = "en";
      }

      // if the user didn't specify number of words to use default to 200
      options.numberofwords  = options.numberofwords || 200;

      // wiki global callback function with a unique id
      // function gets the needed information from wikipedia
      // and stores it by appending values to the options object
      window[ "wikiCallback" + _guid ]  = function ( data ) {

        options._link = document.createElement( "a" );
        options._link.setAttribute( "href", options.src );
        options._link.setAttribute( "target", "_blank" );

        // add the title of the article to the link
        options._link.innerHTML = options.title || data.parse.displaytitle;

        // get the content of the wiki article
        options._desc = document.createElement( "p" );

        // get the article text and remove any special characters
        _text = data.parse.text[ "*" ].substr( data.parse.text[ "*" ].indexOf( "<p>" ) );
        _text = _text.replace( /((<(.|\n)+?>)|(\((.*?)\) )|(\[(.*?)\]))/g, "" );

        _text = _text.split( " " );
        options._desc.innerHTML = ( _text.slice( 0, ( _text.length >= options.numberofwords ? options.numberofwords : _text.length ) ).join (" ") + " ..." ) ;

        options._fired = true;
      };

      if ( options.src ) {
        Popcorn.getScript( "//" + options.lang + ".wikipedia.org/w/api.php?action=parse&props=text&page=" +
          options.src.slice( options.src.lastIndexOf( "/" ) + 1 )  + "&format=json&callback=wikiCallback" + _guid );
      } else if ( Popcorn.plugin.debug ) {
        throw new Error( "Wikipedia plugin needs a 'src'" );
      }

    },
    /**
     * @member wikipedia
     * The start function will be executed when the currentTime
     * of the video  reaches the start time provided by the
     * options variable
     */
    start: function( event, options ){
      // dont do anything if the information didn't come back from wiki
      var isReady = function () {

        if ( !options._fired ) {
          setTimeout( function () {
            isReady();
          }, 13);
        } else {

          if ( options._link && options._desc ) {
            if ( document.getElementById( options.target ) ) {
              document.getElementById( options.target ).appendChild( options._link );
              document.getElementById( options.target ).appendChild( options._desc );
              options._added = true;
            }
          }
        }
      };

      isReady();
    },
    /**
     * @member wikipedia
     * The end function will be executed when the currentTime
     * of the video  reaches the end time provided by the
     * options variable
     */
    end: function( event, options ){
      // ensure that the data was actually added to the
      // DOM before removal
      if ( options._added ) {
        document.getElementById( options.target ).removeChild( options._link );
        document.getElementById( options.target ).removeChild( options._desc );
      }
    },

    _teardown: function( options ){

      if ( options._added ) {
        options._link.parentNode && document.getElementById( options.target ).removeChild( options._link );
        options._desc.parentNode && document.getElementById( options.target ).removeChild( options._desc );
        delete options.target;
      }
    }
  });

})( Popcorn );
//PLUGIN: linkedin

(function ( Popcorn ){

  /**
   * LinkedIn Popcorn plug-in
   * Places a  LinkedIn plugin inside a div ( http://developers.facebook.com/docs/plugins/ )
   * Options parameter will need a start, end, target, type, and an api key
   * Optional parameters are url, counter, format, companyid, and productid
   * Start is the time that you want this plug-in to execute
   * End is the time that you want this plug-in to stop executing
   * Target is the id of the document element that the plugin needs to be attached to, this target element must exist on the DOM
   * Type is the name of the plugin, options are share, memberprofile, companyinsider, companyprofile, or recommendproduct
   * Apikey is your own api key from obtained from https://www.linkedin.com/secure/developer
   * Url is the desired url to share via LinkedIn. Defaults to the current page if no url is specified
   * Counter is the position where the counter will be positioned. This is used if the type is "share" or "recommendproduct"
   *  The options are right and top (don't include this option if you do not want a counter)
   * Format is the data format of the member and company profile plugins. The options are inlined, hover, and click. Defaults to inline
   * Companyid must be specified if the type is "companyprofile," "companyinsider," or "recommendproduct"
   * Productid must be specified if the type is "recommendproduct"
   *
   * @param {Object} options
   *
   * Example:
   * <script src="popcorn.linkedin.js"></script>
   * ...
   * var p = Popcorn("#video")
   *     .linkedin({
   *       type: "share",
   *       url: "http://www.google.ca",
   *       counter: "right",
   *       target: "sharediv"
   *       apikey: "ZOLRI2rzQS_oaXELpPF0aksxwFFEvoxAFZRLfHjaAhcGPfOX0Ds4snkJpWwKs8gk",
   *       start: 1,
   *       end: 3
   *     })
   *
   * This plugin will be displayed between 1 and 3 seconds, inclusive, in the video. This will show how many people have "shared" Google via LinkedIn,
   * with the number of people (counter) displayed to the right of the share plugin.
   */
  Popcorn.plugin( "linkedin", {
    manifest: {
      about: {
        name: "Popcorn LinkedIn Plugin",
        version: "0.1",
        author: "Dan Ventura",
        website: "dsventura.blogspot.com"
      },
      options: {
        type: {
          elem: "input",
          type: "text",
          label: "Type"
        },
        url: {
          elem: "input",
          type: "text",
          label: "URL"
        },
        apikey: {
          elem: "input",
          type: "text",
          label: "API Key"
        },
        counter: {
          elem: "input",
          type: "text",
          label: "Counter"
        },
        memberid: {
          elem: "input",
          type: "text",
          label: "Member ID"
        },
        format: {
          elem: "input",
          type: "text",
          label: "Format"
        },
        companyid: {
          elem: "input",
          type: "text",
          label: "Company ID"
        },
        modules: {
          elem: "input",
          type: "text",
          label: "Modules"
        },
        productid: {
          elem: "input",
          type: "text",
          label: "productid"
        },
        related: {
          elem: "input",
          type: "text",
          label: "related"
        },
        start: {
          elem: "input",
          type: "text",
          label: "In"
        },
        end: {
          elem: "input",
          type: "text",
          label: "Out"
        },

        target: "linkedin-container"
      }
    },
    _setup: function( options ) {

      var apikey = options.apikey,
          target = document.getElementById( options.target ),
          script = document.createElement( "script" );

      Popcorn.getScript( "//platform.linkedin.com/in.js" );

      options._container = document.createElement( "div" );
      options._container.appendChild( script );

      if ( apikey ) {
        script.innerHTML = "api_key: " + apikey;
      }

      options.type = options.type && options.type.toLowerCase() || "";

      // Replace the LinkedIn plugin's error message to something more helpful
      var errorMsg = function() {
        options._container = document.createElement( "p" );
        options._container.innerHTML = "Plugin requires a valid <a href='https://www.linkedin.com/secure/developer'>apikey</a>";
        if ( !target && Popcorn.plugin.debug ) {
          throw ( "target container doesn't exist" );
        }
        target && target.appendChild( options._container );
      };

      var setOptions = (function ( options ) {

        return {
          share: function () {

            script.setAttribute( "type", "IN/Share" );

            if ( options.counter ) {
              script.setAttribute( "data-counter", options.counter );
            }
            if ( options.url ) {
              script.setAttribute( "data-url", options.url );
            }
          },
          memberprofile: function () {

            script.setAttribute( "type", "IN/MemberProfile" );
            script.setAttribute( "data-id", ( options.memberid ) );
            script.setAttribute( "data-format", ( options.format || "inline" ) );

            if ( options.text && options.format.toLowerCase() !== "inline" ) {
              script.setAttribute( "data-text", options.text );
            }
          },
          companyinsider: function () {

            script.setAttribute( "type", "IN/CompanyInsider" );
            script.setAttribute( "data-id", options.companyid );

            if( options.modules ) {
              options._container.setAttribute( "data-modules", options.modules );
            }
          },
          companyprofile: function () {

            script.setAttribute( "type", "IN/CompanyProfile" );
            script.setAttribute( "data-id", ( options.companyid ) );
            script.setAttribute( "data-format", ( options.format || "inline" ) );

            if ( options.text && options.format.toLowerCase() !== "inline" ) {
              script.setAttribute( "data-text", options.text );
            }
            if ( options.related !== undefined ) {
              script.setAttribute( "data-related", options.related );
            }
          },
          recommendproduct: function () {

            script.setAttribute( "type", "IN/RecommendProduct" );
            script.setAttribute( "data-company", ( options.companyid || "LinkedIn" ) );
            script.setAttribute( "data-product", ( options.productid || "201714" ) );

            if ( options.counter ) {
              script.setAttribute( "data-counter", options.counter );
            }
          }
        };
      })( options );

      if ( !apikey ) {
        errorMsg();
      } else {
        setOptions[ options.type ] && setOptions[ options.type ]();
      }

      if ( !target && Popcorn.plugin.debug ) {
        throw new Error( "target container doesn't exist" );
      }
      target && target.appendChild( options._container );

      options._container.style.display = "none";
    },
    /**
     * @member linkedin
     * The start function will be executed when the currentTime
     * of the video reaches the start time provided by the
     * options variable
     */
    start: function( event, options ) {
      options._container.style.display = "block";
    },
    /**
     * @member linkedin
     * The end function will be executed when the currentTime
     * of the video reaches the end time provided by the
     * options variable
     */
    end: function( event, options ) {
      options._container.style.display = "none";
    },
    _teardown: function( options ) {
      var tar = document.getElementById( options.target );
      tar && tar.removeChild( options._container );
    }
  });
})( Popcorn );
// PLUGIN: Mustache

(function ( Popcorn ) {

  /**
   * Mustache Popcorn Plug-in
   *
   * Adds the ability to render JSON using templates via the Mustache templating library.
   *
   * @param {Object} options
   *
   * Required parameters: start, end, template, data, and target.
   * Optional parameter: static.
   *
   *   start: the time in seconds when the mustache template should be rendered
   *          in the target div.
   *
   *   end: the time in seconds when the rendered mustache template should be
   *        removed from the target div.
   *
   *   target: a String -- the target div's id.
   *
   *   template: the mustache template for the plugin to use when rendering.  This can be
   *             a String containing the template, or a Function that returns the template's
   *             String.
   *
   *   data: the data to be rendered using the mustache template.  This can be a JSON String,
   *         a JavaScript Object literal, or a Function returning a String or Literal.
   *
   *   dynamic: an optional argument indicating that the template and json data are dynamic
   *            and need to be loaded dynamically on every use.  Defaults to True.
   *
   * Example:
     var p = Popcorn('#video')

        // Example using template and JSON strings.
        .mustache({
          start: 5, // seconds
          end:  15,  // seconds
          target: 'mustache',
          template: '<h1>{{header}}</h1>'                         +
                    '{{#bug}}'                                    +
                    '{{/bug}}'                                    +
                    ''                                            +
                    '{{#items}}'                                  +
                    '  {{#first}}'                                +
                    '    <li><strong>{{name}}</strong></li>'      +
                    '  {{/first}}'                                +
                    '  {{#link}}'                                 +
                    '    <li><a href="{{url}}">{{name}}</a></li>' +
                    '  {{/link}}'                                 +
                    '{{/items}}'                                  +
                    ''                                            +
                    '{{#empty}}'                                  +
                    '  <p>The list is empty.</p>'                 +
                    '{{/empty}}'                                  ,

          data:     '{'                                                        +
                    '  "header": "Colors", '                                   +
                    '  "items": [ '                                            +
                    '      {"name": "red", "first": true, "url": "#Red"}, '    +
                    '      {"name": "green", "link": true, "url": "#Green"}, ' +
                    '      {"name": "blue", "link": true, "url": "#Blue"} '    +
                    '  ],'                                                     +
                    '  'empty': false'                                         +
                    '}',
          dynamic: false // The json is not going to change, load it early.
        } )

        // Example showing Functions instead of Strings.
        .mustache({
          start: 20,  // seconds
          end:   25,  // seconds
          target: 'mustache',
          template: function(instance, options) {
                      var template = // load your template file here...
                      return template;
                    },
          data:     function(instance, options) {
                      var json = // load your json here...
                      return json;
                    }
        } );
  *
  */

  Popcorn.plugin( "mustache" , function( options ){

    var getData, data, getTemplate, template;

    Popcorn.getScript( "https://github.com/janl/mustache.js/raw/master/mustache.js" );

    var shouldReload = !!options.dynamic,
        typeOfTemplate = typeof options.template,
        typeOfData = typeof options.data,
        target = document.getElementById( options.target );

    if ( !target && Popcorn.plugin.debug ) {
      throw new Error( "target container doesn't exist" );
    }
    options.container = target || document.createElement( "div" );

    if ( typeOfTemplate === "function" ) {
      if ( !shouldReload ) {
        template = options.template( options );
      } else {
        getTemplate = options.template;
      }
    } else if ( typeOfTemplate === "string" ) {
      template = options.template;
    } else if ( Popcorn.plugin.debug ) {
      throw new Error( "Mustache Plugin Error: options.template must be a String or a Function." );
    } else {
      template = "";
    }

    if ( typeOfData === "function" ) {
      if ( !shouldReload ) {
        data = options.data( options );
      } else {
        getData = options.data;
      }
    } else if ( typeOfData === "string" ) {
      data = JSON.parse( options.data );
    } else if ( typeOfData === "object" ) {
      data = options.data;
    } else if ( Popcorn.plugin.debug ) {
      throw new Error( "Mustache Plugin Error: options.data must be a String, Object, or Function." );
    } else {
      data = "";
    }

    return {
      start: function( event, options ) {

        var interval = function() {

          if( !window.Mustache ) {
            setTimeout( function() {
              interval();
            }, 10 );
          } else {

            // if dynamic, freshen json data on every call to start, just in case.
            if ( getData ) {
              data = getData( options );
            }

            if ( getTemplate ) {
              template = getTemplate( options );
            }

            var html = Mustache.to_html( template,
                                         data
                                       ).replace( /^\s*/mg, "" );
            options.container.innerHTML = html;
          }
        };

        interval();

      },

      end: function( event, options ) {
        options.container.innerHTML = "";
      },
      _teardown: function( options ) {
        getData = data = getTemplate = template = null;
      }
    };
  },
  {
    about: {
      name: "Popcorn Mustache Plugin",
      version: "0.1",
      author: "David Humphrey (@humphd)",
      website: "http://vocamus.net/dave"
    },
    options: {
      start: {
        elem: "input",
        type: "text",
        label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      target: "mustache-container",
      template: {
        elem: "input",
        type: "text",
        label: "Template"
      },
      data: {
        elem: "input",
        type: "text",
        label: "Data"
      },
      /* TODO: how to show a checkbox/boolean? */
      dynamic: {
        elem: "input",
        type: "text",
        label: "Dynamic"
      }
    }
  });
})( Popcorn );
// PLUGIN: OPENMAP
( function ( Popcorn ) {

  /**
   * openmap popcorn plug-in
   * Adds an OpenLayers map and open map tiles (OpenStreetMap [default], NASA WorldWind, or USGS Topographic)
   * Based on the googlemap popcorn plug-in. No StreetView support
   * Options parameter will need a start, end, target, type, zoom, lat and lng
   * -Start is the time that you want this plug-in to execute
   * -End is the time that you want this plug-in to stop executing
   * -Target is the id of the DOM element that you want the map to appear in. This element must be in the DOM
   * -Type [optional] either: ROADMAP (OpenStreetMap), SATELLITE (NASA WorldWind / LandSat), or TERRAIN (USGS).  ROADMAP/OpenStreetMap is the default.
   * -Zoom [optional] defaults to 2
   * -Lat and Lng are the coordinates of the map if location is not named
   * -Location is a name of a place to center the map, geocoded to coordinates using TinyGeocoder.com
   * -Markers [optional] is an array of map marker objects, with the following properties:
   * --Icon is the URL of a map marker image
   * --Size [optional] is the radius in pixels of the scaled marker image (default is 14)
   * --Text [optional] is the HTML content of the map marker -- if your popcorn instance is named 'popped', use <script>popped.currentTime(10);</script> to control the video
   * --Lat and Lng are coordinates of the map marker if location is not specified
   * --Location is a name of a place for the map marker, geocoded to coordinates using TinyGeocoder.com
   *  Note: using location requires extra loading time, also not specifying both lat/lng and location will
   * cause a JavaScript error.
   * @param {Object} options
   *
   * Example:
     var p = Popcorn( '#video' )
        .openmap({
          start: 5,
          end: 15,
          type: 'ROADMAP',
          target: 'map',
          lat: 43.665429,
          lng: -79.403323
        })
   *
   */
  var newdiv,
      i = 1;

  function toggle( container, display ) {
    if ( container.map ) {

      container.map.div.style.display = display;
      return;
    }

    setTimeout(function() {
      toggle( container, display );
    }, 10 );
  }

  Popcorn.plugin( "openmap", function( options ){
    var newdiv,
        centerlonlat,
        projection,
        displayProjection,
        pointLayer,
        selectControl,
        popup,
        isGeoReady,
        target = document.getElementById( options.target );

    // create a new div within the target div
    // this is later passed on to the maps api
    newdiv = document.createElement( "div" );
    newdiv.id = "openmapdiv" + i;
    newdiv.style.width = "100%";
    newdiv.style.height = "100%";
    i++;

    if ( !target && Popcorn.plugin.debug ) {
      throw new Error( "target container doesn't exist" );
    }

    target && target.appendChild( newdiv );

    // callback function fires when the script is run
    isGeoReady = function() {
      if ( !window.OpenLayers ) {
        setTimeout(function() {
          isGeoReady();
        }, 50);
      } else {
        if ( options.location ) {
          // set a dummy center at start
          location = new OpenLayers.LonLat( 0, 0 );
          // query TinyGeocoder and re-center in callback
          Popcorn.getJSONP(
            "//tinygeocoder.com/create-api.php?q=" + options.location + "&callback=jsonp",
            function( latlng ) {
              centerlonlat = new OpenLayers.LonLat( latlng[ 1 ], latlng[ 0 ] );
              options.map.setCenter( centerlonlat );
            }
          );
        } else {
          centerlonlat = new OpenLayers.LonLat( options.lng, options.lat );
        }
        options.type = options.type || "ROADMAP";
        if ( options.type === "SATELLITE" ) {
          // add NASA WorldWind / LANDSAT map
          options.map = new OpenLayers.Map( { div: newdiv, "maxResolution": 0.28125, tileSize: new OpenLayers.Size( 512, 512 ) } );
          var worldwind = new OpenLayers.Layer.WorldWind( "LANDSAT", "//worldwind25.arc.nasa.gov/tile/tile.aspx", 2.25, 4, { T: "105" } );
          options.map.addLayer( worldwind );
          displayProjection = new OpenLayers.Projection( "EPSG:4326" );
          projection = new OpenLayers.Projection( "EPSG:4326" );
        }
        else if ( options.type === "TERRAIN" ) {
          // add terrain map ( USGS )
          displayProjection = new OpenLayers.Projection( "EPSG:4326" );
          projection = new OpenLayers.Projection( "EPSG:4326" );
          options.map = new OpenLayers.Map( {div: newdiv, projection: projection } );
          var relief = new OpenLayers.Layer.WMS( "USGS Terraserver", "//terraserver-usa.org/ogcmap.ashx?", { layers: "DRG" } );
          options.map.addLayer( relief );
        } else {
          // add OpenStreetMap layer
          projection = new OpenLayers.Projection( 'EPSG:900913' );
          displayProjection = new OpenLayers.Projection( 'EPSG:4326' );
          centerlonlat = centerlonlat.transform( displayProjection, projection );
          options.map = new OpenLayers.Map( { div: newdiv, projection: projection, "displayProjection": displayProjection } );
          var osm = new OpenLayers.Layer.OSM();
          options.map.addLayer( osm );
        }
        if ( options.map ) {
          options.map.div.style.display = "none";
        }
      }
    };

    isGeoReady();

    return {

      /**
       * @member openmap
       * The setup function will be executed when the plug-in is instantiated
       */
      _setup: function( options ) {

        // insert openlayers api script once
        if ( !window.OpenLayers ) {
          Popcorn.getScript( "//openlayers.org/api/OpenLayers.js" );
        }

        var isReady = function() {
          // wait until OpenLayers has been loaded, and the start function is run, before adding map
          if ( !options.map ) {
            setTimeout(function() {
              isReady();
            }, 13 );
          } else {

            // default zoom is 2
            options.zoom = options.zoom || 2;

            // make sure options.zoom is a number
            if ( options.zoom && typeof options.zoom !== "number" ) {
              options.zoom = +options.zoom;
            }

            // reset the location and zoom just in case the user played with the map
            options.map.setCenter( centerlonlat, options.zoom );
            if ( options.markers ) {
              var layerStyle = OpenLayers.Util.extend( {} , OpenLayers.Feature.Vector.style[ "default" ] ),
                  featureSelected = function( clickInfo ) {
                    clickedFeature = clickInfo.feature;
                    if ( !clickedFeature.attributes.text ) {
                      return;
                    }
                    popup = new OpenLayers.Popup.FramedCloud(
                      "featurePopup",
                      clickedFeature.geometry.getBounds().getCenterLonLat(),
                      new OpenLayers.Size( 120, 250 ),
                      clickedFeature.attributes.text,
                      null,
                      true,
                      function( closeInfo ) {
                        selectControl.unselect( this.feature );
                      }
                    );
                    clickedFeature.popup = popup;
                    popup.feature = clickedFeature;
                    options.map.addPopup( popup );
                  },
                  featureUnSelected = function( clickInfo ) {
                    feature = clickInfo.feature;
                    if ( feature.popup ) {
                      popup.feature = null;
                      options.map.removePopup( feature.popup );
                      feature.popup.destroy();
                      feature.popup = null;
                    }
                  },
                  gcThenPlotMarker = function( myMarker ) {
                    Popcorn.getJSONP(
                      "//tinygeocoder.com/create-api.php?q=" + myMarker.location + "&callback=jsonp",
                      function( latlng ) {
                        var myPoint = new OpenLayers.Geometry.Point( latlng[1], latlng[0] ).transform( displayProjection, projection ),
                            myPointStyle = OpenLayers.Util.extend( {}, layerStyle );
                        if ( !myMarker.size || isNaN( myMarker.size ) ) {
                          myMarker.size = 14;
                        }
                        myPointStyle.pointRadius = myMarker.size;
                        myPointStyle.graphicOpacity = 1;
                        myPointStyle.externalGraphic = myMarker.icon;
                        var myPointFeature = new OpenLayers.Feature.Vector( myPoint, null, myPointStyle );
                        if ( myMarker.text ) {
                          myPointFeature.attributes = {
                            text: myMarker.text
                          };
                        }
                        pointLayer.addFeatures( [ myPointFeature ] );
                      }
                    );
                  };
              pointLayer = new OpenLayers.Layer.Vector( "Point Layer", { style: layerStyle } );
              options.map.addLayer( pointLayer );
              for ( var m = 0, l = options.markers.length; m < l ; m++ ) {
                var myMarker = options.markers[ m ];
                if( myMarker.text ){
                  if( !selectControl ){
                    selectControl = new OpenLayers.Control.SelectFeature( pointLayer );
                    options.map.addControl( selectControl );
                    selectControl.activate();
                    pointLayer.events.on({
                      "featureselected": featureSelected,
                      "featureunselected": featureUnSelected
                    });
                  }
                }
                if ( myMarker.location ) {
                  var geocodeThenPlotMarker = gcThenPlotMarker;
                  geocodeThenPlotMarker( myMarker );
                } else {
                  var myPoint = new OpenLayers.Geometry.Point( myMarker.lng, myMarker.lat ).transform( displayProjection, projection ),
                      myPointStyle = OpenLayers.Util.extend( {}, layerStyle );
                  if ( !myMarker.size || isNaN( myMarker.size ) ) {
                    myMarker.size = 14;
                  }
                  myPointStyle.pointRadius = myMarker.size;
                  myPointStyle.graphicOpacity = 1;
                  myPointStyle.externalGraphic = myMarker.icon;
                  var myPointFeature = new OpenLayers.Feature.Vector( myPoint, null, myPointStyle );
                  if ( myMarker.text ) {
                    myPointFeature.attributes = {
                      text: myMarker.text
                    };
                  }
                  pointLayer.addFeatures( [ myPointFeature ] );
                }
              }
            }
          }
        };

        isReady();
      },

      /**
       * @member openmap
       * The start function will be executed when the currentTime
       * of the video  reaches the start time provided by the
       * options variable
       */
      start: function( event, options ) {
        toggle( options, "block" );
      },

      /**
       * @member openmap
       * The end function will be executed when the currentTime
       * of the video reaches the end time provided by the
       * options variable
       */
      end: function( event, options ) {
          toggle( options, "none" );
      },

      _teardown: function( options ) {

        target && target.removeChild( newdiv );
        newdiv = map = centerlonlat = projection = displayProjection = pointLayer = selectControl = popup = null;
      }
    };
  },
  {
    about:{
      name: "Popcorn OpenMap Plugin",
      version: "0.3",
      author: "@mapmeld",
      website: "mapadelsur.blogspot.com"
    },
    options:{
      start: {
        elem: "input",
        type: "text",
        label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      target: "map-container",
      type: {
        elem: "select",
        options: [ "ROADMAP", "SATELLITE", "TERRAIN" ],
        label: "Type"
      },
      zoom: {
        elem: "input",
        type: "text",
        label: "Zoom"
      },
      lat: {
        elem: "input",
        type: "text",
        label: "Lat"
      },
      lng: {
        elem: "input",
        type: "text",
        label: "Lng"
      },
      location: {
        elem: "input",
        type: "text",
        label: "Location"
      },
      markers: {
        elem: "input",
        type: "text",
        label: "List Markers"
      }
    }
  });
}) ( Popcorn );
/**
* Pause Popcorn Plug-in
*
* When this plugin is used, links on the webpage, when clicked, will pause
* popcorn videos that especified 'pauseOnLinkClicked' as an option. Links may
* cause a new page to display on a new window, or may cause a new page to
* display in the current window, in which case the videos won't be available
* anymore. It only affects anchor tags. It does not affect objects with click
* events that act as anchors.
*
* Example:
 var p = Popcorn('#video', { pauseOnLinkClicked : true } )
   .play();
*
*/

document.addEventListener( "click", function( event ) {

  var targetElement = event.target;

  //Some browsers use an element as the target, some use the text node inside
  if ( targetElement.nodeName === "A" || targetElement.parentNode && targetElement.parentNode.nodeName === "A" ) {
    Popcorn.instances.forEach( function( video ) {
      if ( video.options.pauseOnLinkClicked ) {
        video.pause();
      }
    });
  }
}, false );
// PLUGIN: Wordriver

(function ( Popcorn ) {

  var container = {},
      spanLocation = 0,
      setupContainer = function( target ) {

        container[ target ] = document.createElement( "div" );

        var t = document.getElementById( target );
        t && t.appendChild( container[ target ] );

        container[ target ].style.height = "100%";
        container[ target ].style.position = "relative";

        return container[ target ];
      },
      // creates an object of supported, cross platform css transitions
      span = document.createElement( "span" ),
      prefixes = [ "webkit", "Moz", "ms", "O", "" ],
      specProp = [ "Transform", "TransitionDuration", "TransitionTimingFunction" ],
      supports = {},
      prop;

  document.getElementsByTagName( "head" )[ 0 ].appendChild( span );

  for ( var sIdx = 0, sLen = specProp.length; sIdx < sLen; sIdx++ ) {

    for ( var pIdx = 0, pLen = prefixes.length; pIdx < pLen; pIdx++ ) {

      prop = prefixes[ pIdx ] + specProp[ sIdx ];

      if ( prop in span.style ) {

        supports[ specProp[ sIdx ].toLowerCase() ] = prop;
        break;
      }
    }
  }

  // Garbage collect support test span
  document.getElementsByTagName( "head" )[ 0 ].appendChild( span );

  /**
   * Word River popcorn plug-in
   * Displays a string of text, fading it in and out
   * while transitioning across the height of the parent container
   * for the duration of the instance  (duration = end - start)
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn( '#video' )
        .wordriver({
          start: 5,                      // When to begin the Word River animation
          end: 15,                       // When to finish the Word River animation
          text: 'Hello World',           // The text you want to be displayed by Word River
          target: 'wordRiverDiv',        // The target div to append the text to
          color: "blue"                  // The color of the text. (can be Hex value i.e. #FFFFFF )
        } )
   *
   */

  Popcorn.plugin( "wordriver" , {

      manifest: {
        about:{
          name: "Popcorn WordRiver Plugin"
        },
        options: {
          start: {
            elem: "input",
            type: "text",
            label: "In"
          },
          end: {
            elem: "input",
            type: "text",
            label: "Out"
          },
          target: "wordriver-container",
          text: {
            elem: "input",
            type: "text",
            label: "Text"
          },
          color: {
            elem: "input",
            type: "text",
            label: "Color"
          }
        }
      },

      _setup: function( options ) {

        if ( !document.getElementById( options.target ) && Popcorn.plugin.debug ) {
          throw new Error( "target container doesn't exist" );
        }

        options._duration = options.end - options.start;
        options._container = container[ options.target ] || setupContainer( options.target );

        options.word = document.createElement( "span" );
        options.word.style.position = "absolute";

        options.word.style.whiteSpace = "nowrap";
        options.word.style.opacity = 0;

        options.word.style.MozTransitionProperty = "opacity, -moz-transform";
        options.word.style.webkitTransitionProperty = "opacity, -webkit-transform";
        options.word.style.OTransitionProperty = "opacity, -o-transform";
        options.word.style.transitionProperty = "opacity, transform";

        options.word.style[ supports.transitionduration ] = 1 + "s, " + options._duration + "s";
        options.word.style[ supports.transitiontimingfunction ] = "linear";

        options.word.innerHTML = options.text;
        options.word.style.color = options.color || "black";
      },
      start: function( event, options ){

        options._container.appendChild( options.word );

        // Resets the transform when changing to a new currentTime before the end event occurred.
        options.word.style[ supports.transform ] = "";

        options.word.style.fontSize = ~~( 30 + 20 * Math.random() ) + "px";
        spanLocation = spanLocation % ( options._container.offsetWidth - options.word.offsetWidth );
        options.word.style.left = spanLocation + "px";
        spanLocation += options.word.offsetWidth + 10;
        options.word.style[ supports.transform ] = "translateY(" +
          ( options._container.offsetHeight - options.word.offsetHeight ) + "px)";

        options.word.style.opacity = 1;

        // automatically clears the word based on time
        setTimeout( function() {

		      options.word.style.opacity = 0;
        // ensures at least one second exists, because the fade animation is 1 second
		    }, ( ( (options.end - options.start) - 1 ) || 1 ) * 1000 );
      },
      end: function( event, options ){

        // manually clears the word based on user interaction
        options.word.style.opacity = 0;
      },
      _teardown: function( options ) {

        var target = document.getElementById( options.target );
        // removes word span from generated container
        options.word.parentNode && options._container.removeChild( options.word );

        // if no more word spans exist in container, remove container
        container[ options.target ] &&
          !container[ options.target ].childElementCount &&
          target && target.removeChild( container[ options.target ] ) &&
          delete container[ options.target ];
      }
  });

})( Popcorn );
/**
 * Processing Popcorn Plug-In
 *
 * This plugin adds a Processing.js sketch to be added to a target div or canvas.
 *
 * Options parameter needs to specify start, end, target and  sketch attributes
 * -Start is the time [in seconds] that you want the sketch to display and start looping.
 * -End is the time [in seconds] you want the sketch to become hidden and stop looping.
 * -Target is the id of the div or canvas you want the target sketch to be displayed in. ( a target that is a div will have a canvas created and placed inside of it. )
 * -Sketch specifies the filename of the Procesing code to be loaded into Processing.js
 * -noLoop [optional] specifies whether a sketch should continue to loop when the video is paused or seeking.
 *
 * @param {Object} options
 *
 * Example:
 var p = Popcorn( "#video" )
 .processing({
   start: 5,
   end: 10,
   target: "processing-div",
   sketch: "processingSketch.pjs",
   noLoop: true
 });
 *
 */

(function( Popcorn ) {

  Popcorn.plugin( "processing", function( options ) {

    var init = function( context ) {

      function scriptReady( options ) {
        var addListeners = function() {
          context.listen( "pause", function() {
            if ( options.canvas.style.display === "inline" ) {
              options.pjsInstance.noLoop();
            }
          });
          context.listen( "play", function() {
            if ( options.canvas.style.display === "inline" ) {
              options.pjsInstance.loop();
            }
          });
        };

        if ( options.sketch ) {

          Popcorn.xhr({
            url: options.sketch,
            dataType: "text",
            success: function( responseCode ) {

              options.codeReady = false;

              var s = Processing.compile( responseCode );
              options.pjsInstance = new Processing( options.canvas, s );
              options.seeking = false;
              ( options._running && !context.media.paused && options.pjsInstance.loop() ) || options.pjsInstance.noLoop();

              context.listen( "seeking", function() {
                 options._running && options.canvas.style.display === "inline" && options.noPause && options.pjsInstance.loop();
              });

              options.noPause = options.noPause || false;
              !options.noPause && addListeners();
              options.codeReady = true;
            }
          });
        } else if ( Popcorn.plugin.debug ) {

          throw new Error( "Popcorn.Processing: options.sketch is undefined" );
        }
      }

      if ( !window.Processing ) {
        Popcorn.getScript( "//wac.1237.edgecastcdn.net/801237/cdn.processingjs.org/content/download/processing-js-1.3.6/processing-1.3.6.min.js", function() {
          scriptReady( options );
        });
      } else {
        scriptReady( options );
      }

    };

    return {

      _setup: function( options ) {

        options.codeReady = false;

        options.parentTarget = document.getElementById( options.target );

        if ( !options.parentTarget && Popcorn.plugin.debug ) {
          throw new Error( "target container doesn't exist" );
        }

        var canvas = document.createElement( "canvas" );
        canvas.id = Popcorn.guid( options.target + "-sketch" );
        canvas.style.display = "none";
        options.canvas = canvas;

        options.parentTarget && options.parentTarget.appendChild( options.canvas );

        init( this );
      },

      start: function( event, options ) {

        options.codeReady && !this.media.paused && options.pjsInstance.loop();
        options.canvas.style.display = "inline";

      },

      end: function( event, options ) {

        options.pjsInstance && options.pjsInstance.noLoop();
        options.canvas.style.display = "none";
      },

      _teardown: function( options ) {
        options.pjsInstance && options.pjsInstance.exit();
        options.parentTarget && options.parentTarget.removeChild( options.canvas );
      }
    };
  },
  {
    about: {
      name: "Popcorn Processing Plugin",
      version: "0.1",
      author: "Christopher De Cairos, Benjamin Chalovich",
      website: "cadecairos.blogspot.com, ben1amin.wordpress.org"
    },
    options: {
      start: {
        elem: "input",
        type: "text",
        label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      target: {
        elem: "input",
        type: "text",
        label: "Target"
      },
      sketch: {
        elem: "input",
        type: "url",
        label: "Sketch"
      },
      noPause: {
        elem: "select",
        options: [ "TRUE", "FALSE" ],
        label: "No Loop"
      }
    }
  });
}( Popcorn ));
// PLUGIN: Timeline
(function ( Popcorn ) {

  /**
     * timeline popcorn plug-in
     * Adds data associated with a certain time in the video, which creates a scrolling view of each item as the video progresses
     * Options parameter will need a start, target, title, and text
     * -Start is the time that you want this plug-in to execute
     * -End is the time that you want this plug-in to stop executing, tho for this plugin an end time may not be needed ( optional )
     * -Target is the id of the DOM element that you want the timeline to appear in. This element must be in the DOM
     * -Title is the title of the current timeline box
     * -Text is text is simply related text that will be displayed
     * -innerHTML gives the user the option to add things such as links, buttons and so on
     * -direction specifies whether the timeline will grow from the top or the bottom, receives input as "UP" or "DOWN"
     * @param {Object} options
     *
     * Example:
      var p = Popcorn("#video")
        .timeline( {
         start: 5, // seconds
         target: "timeline",
         title: "Seneca",
         text: "Welcome to seneca",
         innerHTML: "Click this link <a href='http://www.google.ca'>Google</a>"
      } )
    *
  */

  var i = 1,
      head = document.getElementsByTagName( "head" )[ 0 ],
      css = document.createElement( "link" );

  css.type = "text/css";
  css.rel = "stylesheet";
  css.href = "//popcornjs.org/code/plugins/timeline/popcorn.timeline.css";
  head.insertBefore( css, head.firstChild );

  Popcorn.plugin( "timeline" , function( options ) {

    var target = document.getElementById( options.target ),
        contentDiv = document.createElement( "div" ),
        container,
        goingUp = true;

    if ( target && !target.firstChild ) {
      target.appendChild ( container = document.createElement( "div" ) );
      container.style.width = "inherit";
      container.style.height = "inherit";
      container.style.overflow = "auto";
    } else {
      container = target.firstChild;
    }

    contentDiv.style.display = "none";
    contentDiv.id = "timelineDiv" + i;

    //  Default to up if options.direction is non-existant or not up or down
    options.direction = options.direction || "up";
    if ( options.direction.toLowerCase() === "down" ) {

      goingUp = false;
    }

    if ( target && container ) {
      // if this isnt the first div added to the target div
      if( goingUp ){
        // insert the current div before the previous div inserted
        container.insertBefore( contentDiv, container.firstChild );
      }
      else {

        container.appendChild( contentDiv );
      }

    } else if ( Popcorn.plugin.debug ) {
      throw new Error( "target container doesn't exist" );
    }

    i++;

    //  Default to empty if not used
    //options.innerHTML = options.innerHTML || "";

    contentDiv.innerHTML = "<p><span id='big'>" + options.title + "</span><br />" +
    "<span id='mid'>" + options.text + "</span><br />" + options.innerHTML;

    return {

      start: function( event, options ) {
        contentDiv.style.display = "block";

        if( options.direction === "down" ) {
          container.scrollTop = container.scrollHeight;
        }
      },

      end: function( event, options ) {
        contentDiv.style.display = "none";
      },

      _teardown: function( options ) {

        ( container && contentDiv ) && container.removeChild( contentDiv ) && !container.firstChild && target.removeChild( container );
      }
    };
  },
  {

    about: {
      name: "Popcorn Timeline Plugin",
      version: "0.1",
      author: "David Seifried @dcseifried",
      website: "dseifried.wordpress.com"
    },

    options: {
      start: {
        elem: "input",
        type: "text",
        label: "In"
      },
      end: {
        elem: "input",
        type: "text",
        label: "Out"
      },
      target: "feed-container",
      title: {
        elem: "input",
        type: "text",
        label: "title"
      },
      text: {
        elem: "input",
        type: "text",
        label: "text"
      },
      innerHTML: {
        elem: "input",
        type: "text",
        label: "innerHTML"
      },
      direction: {
        elem: "input",
        type: "text",
        label: "direction"
      }
    }
  });

})( Popcorn );
// PARSER: 0.3 JSON

(function (Popcorn) {
  Popcorn.parser( "parseJSON", "JSON", function( data ) {

    // declare needed variables
    var retObj = {
          title: "",
          remote: "",
          data: []
        },
        manifestData = {},
        dataObj = data;


    /*
      TODO: add support for filling in source children of the video element


      remote: [
        {
          src: "whatever.mp4",
          type: 'video/mp4; codecs="avc1, mp4a"'
        },
        {
          src: "whatever.ogv",
          type: 'video/ogg; codecs="theora, vorbis"'
        }
      ]

    */


    Popcorn.forEach( dataObj.data, function ( obj, key ) {
      retObj.data.push( obj );
    });

    return retObj;
  });

})( Popcorn );
// PARSER: 0.1 SBV

(function (Popcorn) {

  /**
   * SBV popcorn parser plug-in
   * Parses subtitle files in the SBV format.
   * Times are expected in H:MM:SS.MIL format, with hours optional
   * Subtitles which don't match expected format are ignored
   * Data parameter is given by Popcorn, will need a text.
   * Text is the file contents to be parsed
   *
   * @param {Object} data
   *
   * Example:
    0:00:02.400,0:00:07.200
    Senator, we're making our final approach into Coruscant.
   */
  Popcorn.parser( "parseSBV", function( data ) {

    // declare needed variables
    var retObj = {
          title: "",
          remote: "",
          data: []
        },
        subs = [],
        lines,
        i = 0,
        len = 0,
        idx = 0;

    // [H:]MM:SS.MIL string to SS.MIL
    // Will thrown exception on bad time format
    var toSeconds = function( t_in ) {
      var t = t_in.split( ":" ),
          l = t.length-1,
          time;

      try {
        time = parseInt( t[l-1], 10 )*60 + parseFloat( t[l], 10 );

        // Hours optionally given
        if ( l === 2 ) {
          time += parseInt( t[0], 10 )*3600;
        }
      } catch ( e ) {
        throw "Bad cue";
      }

      return time;
    };

    var createTrack = function( name, attributes ) {
      var track = {};
      track[name] = attributes;
      return track;
    };

    // Here is where the magic happens
    // Split on line breaks
    lines = data.text.split( /(?:\r\n|\r|\n)/gm );
    len = lines.length;

    while ( i < len ) {
      var sub = {},
          text = [],
          time = lines[i++].split( "," );

      try {
        sub.start = toSeconds( time[0] );
        sub.end = toSeconds( time[1] );

        // Gather all lines of text
        while ( i < len && lines[i] ) {
          text.push( lines[i++] );
        }

        // Join line breaks in text
        sub.text = text.join( "<br />" );
        subs.push( createTrack( "subtitle", sub ) );
      } catch ( e ) {
        // Bad cue, advance to end of cue
        while ( i < len && lines[i] ) {
          i++;
        }
      }

      // Consume empty whitespace
      while ( i < len && !lines[i] ) {
        i++;
      }
    }

    retObj.data = subs;

    return retObj;
  });

})( Popcorn );
// PARSER: 0.3 SRT

(function (Popcorn) {
  /**
   * SRT popcorn parser plug-in
   * Parses subtitle files in the SRT format.
   * Times are expected in HH:MM:SS,MIL format, though HH:MM:SS.MIL also supported
   * Ignore styling, which may occur after the end time or in-text
   * While not part of the "official" spec, majority of players support HTML and SSA styling tags
   * SSA-style tags are stripped, HTML style tags are left for the browser to handle:
   *    HTML: <font>, <b>, <i>, <u>, <s>
   *    SSA:  \N or \n, {\cmdArg1}, {\cmd(arg1, arg2, ...)}

   * Data parameter is given by Popcorn, will need a text.
   * Text is the file contents to be parsed
   *
   * @param {Object} data
   *
   * Example:
    1
    00:00:25,712 --> 00:00:30.399
    This text is <font color="red">RED</font> and has not been {\pos(142,120)} positioned.
    This takes \Nup three \nentire lines.
    This contains nested <b>bold, <i>italic, <u>underline</u> and <s>strike-through</s></u></i></b> HTML tags
    Unclosed but <b>supported tags are left in
    <ggg>Unsupported</ggg> HTML tags are left in, even if <hhh>not closed.
    SSA tags with {\i1} would open and close italicize {\i0}, but are stripped
    Multiple {\pos(142,120)\b1}SSA tags are stripped
   */
  Popcorn.parser( "parseSRT", function( data ) {

    // declare needed variables
    var retObj = {
          title: "",
          remote: "",
          data: []
        },
        subs = [],
        i = 0,
        len = 0,
        idx = 0,
        lines,
        time,
        text,
        sub;

    // Simple function to convert HH:MM:SS,MMM or HH:MM:SS.MMM to SS.MMM
    // Assume valid, returns 0 on error
    var toSeconds = function( t_in ) {
      var t = t_in.split( ':' );

      try {
        var s = t[2].split( ',' );

        // Just in case a . is decimal seperator
        if ( s.length === 1 ) {
          s = t[2].split( '.' );
        }

        return parseFloat( t[0], 10 )*3600 + parseFloat( t[1], 10 )*60 + parseFloat( s[0], 10 ) + parseFloat( s[1], 10 )/1000;
      } catch ( e ) {
        return 0;
      }
    };

    var createTrack = function( name, attributes ) {
      var track = {};
      track[name] = attributes;
      return track;
    };

    // Here is where the magic happens
    // Split on line breaks
    lines = data.text.split( /(?:\r\n|\r|\n)/gm );
    len = lines.length;

    for( i=0; i < len; i++ ) {
      sub = {};
      text = [];

      sub.id = parseInt( lines[i++], 10 );

      // Split on '-->' delimiter, trimming spaces as well
      time = lines[i++].split( /[\t ]*-->[\t ]*/ );

      sub.start = toSeconds( time[0] );

      // So as to trim positioning information from end
      idx = time[1].indexOf( " " );
      if ( idx !== -1) {
        time[1] = time[1].substr( 0, idx );
      }
      sub.end = toSeconds( time[1] );

      // Build single line of text from multi-line subtitle in file
      while ( i < len && lines[i] ) {
        text.push( lines[i++] );
      }

      // Join into 1 line, SSA-style linebreaks
      // Strip out other SSA-style tags
      sub.text = text.join( "\\N" ).replace( /\{(\\[\w]+\(?([\w\d]+,?)+\)?)+\}/gi, "" );

      // Escape HTML entities
      sub.text = sub.text.replace( /</g, "&lt;" ).replace( />/g, "&gt;" );

      // Unescape great than and less than when it makes a valid html tag of a supported style (font, b, u, s, i)
      // Modified version of regex from Phil Haack's blog: http://haacked.com/archive/2004/10/25/usingregularexpressionstomatchhtml.aspx
      // Later modified by kev: http://kevin.deldycke.com/2007/03/ultimate-regular-expression-for-html-tag-parsing-with-php/
      sub.text = sub.text.replace( /&lt;(\/?(font|b|u|i|s))((\s+(\w|\w[\w\-]*\w)(\s*=\s*(?:\".*?\"|'.*?'|[^'\">\s]+))?)+\s*|\s*)(\/?)&gt;/gi, "<$1$3$7>" );
      sub.text = sub.text.replace( /\\N/gi, "<br />" );
      subs.push( createTrack( "subtitle", sub ) );
    }

    retObj.data = subs;
    return retObj;
  });

})( Popcorn );
// PARSER: 0.3 SSA/ASS

(function ( Popcorn ) {
  /**
   * SSA/ASS popcorn parser plug-in
   * Parses subtitle files in the identical SSA and ASS formats.
   * Style information is ignored, and may be found in these
   * formats: (\N    \n    {\pos(400,570)}     {\kf89})
   * Out of the [Script Info], [V4 Styles], [Events], [Pictures],
   * and [Fonts] sections, only [Events] is processed.
   * Data parameter is given by Popcorn, will need a text.
   * Text is the file contents to be parsed
   *
   * @param {Object} data
   *
   * Example:
     [Script Info]
      Title: Testing subtitles for the SSA Format
      [V4 Styles]
      Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding
      Style: Default,Arial,20,65535,65535,65535,-2147483640,-1,0,1,3,0,2,30,30,30,0,0
      [Events]
      Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
      Dialogue: 0,0:00:02.40,0:00:07.20,Default,,0000,0000,0000,,Senator, {\kf89}we're \Nmaking our final \napproach into Coruscant.
      Dialogue: 0,0:00:09.71,0:00:13.39,Default,,0000,0000,0000,,{\pos(400,570)}Very good, Lieutenant.
      Dialogue: 0,0:00:15.04,0:00:18.04,Default,,0000,0000,0000,,It's \Na \ntrap!
   *
   */

  // Register for SSA extensions
  Popcorn.parser( "parseSSA", function( data ) {
    // declare needed variables
    var retObj = {
          title: "",
          remote: "",
          data: [  ]
        },
        rNewLineFile = /(?:\r\n|\r|\n)/gm,
        subs = [  ],
        lines,
        headers,
        i = 0,
        len;

    // Here is where the magic happens
    // Split on line breaks
    lines = data.text.split( rNewLineFile );
    len = lines.length;

    // Ignore non-textual info
    while ( i < len && lines[ i ] !== "[Events]" ) {
      i++;
    }

    headers = parseFieldHeaders( lines[ ++i ] );

    while ( ++i < len && lines[ i ] && lines[ i ][ 0 ] !== "[" ) {
      try {
        subs.push( createTrack( "subtitle", parseSub( lines[ i ], headers ) ) );
      } catch ( e ) {}
    }

    retObj.data = subs;
    return retObj;
  });

  function parseSub( line, headers ) {
    // Trim beginning 'Dialogue: ' and split on delim
    var fields = line.substr( 10 ).split( "," ),
        rAdvancedStyles = /\{(\\[\w]+\(?([\w\d]+,?)+\)?)+\}/gi,
        rNewLineSSA = /\\N/gi,
        sub;

    sub = {
      start: toSeconds( fields[ headers.start ] ),
      end: toSeconds( fields[ headers.end ] )
    };

    // Invalid time, skip
    if ( sub.start === -1 || sub.end === -1 ) {
      throw "Invalid time";
    }

    // Eliminate advanced styles and convert forced line breaks
    sub.text = getTextFromFields( fields, headers.text ).replace( rAdvancedStyles, "" ).replace( rNewLineSSA, "<br />" );

    return sub;
  }

  // h:mm:ss.cc (centisec) string to SS.mmm
  // Returns -1 if invalid
  function toSeconds( t_in ) {
    var t = t_in.split( ":" );

    // Not all there
    if ( t_in.length !== 10 || t.length < 3 ) {
      return -1;
    }

    return parseInt( t[ 0 ], 10 ) * 3600 + parseInt( t[ 1 ], 10 ) * 60 + parseFloat( t[ 2 ], 10 );
  }

  function getTextFromFields( fields, startIdx ) {
    var fieldLen = fields.length,
        text = [  ],
        i = startIdx;

    // There may be commas in the text which were split, append back together into one line
    for( ; i < fieldLen; i++ ) {
      text.push( fields[ i ] );
    }

    return text.join( "," );
  }

  function createTrack( name, attributes ) {
    var track = {};
    track[ name ] = attributes;
    return track;
  }

  function parseFieldHeaders( line ) {
    // Trim 'Format: ' off front, split on delim
    var fields = line.substr( 8 ).split( ", " ),
        result = {},
        len,
        i;

     //Find where in Dialogue string the start, end and text info is
    for ( i = 0, len = fields.length; i < len; i++ ) {
      if ( fields[ i ] === "Start" ) {
        result.start = i;
      } else if ( fields[ i ] === "End" ) {
        result.end = i;
      } else if ( fields[ i ] === "Text" ) {
        result.text = i;
      }
    }

    return result;
  }
})( Popcorn );
// PARSER: 0.3 TTML

(function (Popcorn) {

  /**
   * TTML popcorn parser plug-in
   * Parses subtitle files in the TTML format.
   * Times may be absolute to the timeline or relative
   *   Absolute times are ISO 8601 format (hh:mm:ss[.mmm])
   *   Relative times are a fraction followed by a unit metric (d.ddu)
   *     Relative times are relative to the time given on the parent node
   * Styling information is ignored
   * Data parameter is given by Popcorn, will need an xml.
   * Xml is the file contents to be processed
   *
   * @param {Object} data
   *
   * Example:
    <tt xmlns:tts="http://www.w3.org/2006/04/ttaf1#styling" xmlns="http://www.w3.org/2006/04/ttaf1">
      <body region="subtitleArea">
        <div>
          <p xml:id="subtitle1" begin="0.76s" end="3.45s">
            It seems a paradox, does it not,
          </p>
        </div>
      </body>
    </tt>
   */
  Popcorn.parser( "parseTTML", function( data ) {

    // declare needed variables
    var returnData = {
          title: "",
          remote: "",
          data: []
        },
        node,
        numTracks = 0,
        region;

    // Convert time expression to SS.mmm
    // Expression may be absolute to timeline (hh:mm:ss.ms)
    //   or relative ( fraction followedd by metric ) ex: 3.4s, 5.7m
    // Returns -1 if invalid
    var toSeconds = function ( t_in, offset ) {
      if ( !t_in ) {
        return -1;
      }

      var t = t_in.split( ":" ),
          l = t.length - 1,
          metric,
          multiplier,
          i;

      // Try clock time
      if ( l >= 2 ) {
        return parseInt( t[0], 10 )*3600 + parseInt( t[l-1], 10 )*60 + parseFloat( t[l], 10 );
      }

      // Was not clock time, assume relative time
      // Take metric from end of string (may not be single character)
      // First find metric
      for( i = t_in.length - 1; i >= 0; i-- ) {
        if ( t_in[i] <= "9" && t_in[i] >= "0" ) {
          break;
        }
      }

      // Point i at metric and normalize offsete time
      i++;
      metric = t_in.substr( i );
      offset = offset || 0;

      // Determine multiplier for metric relative to seconds
      if ( metric === "h" ) {
        multiplier = 3600;
      } else if ( metric === "m" ) {
        multiplier = 60;
      } else if ( metric === "s" ) {
        multiplier = 1;
      } else if ( metric === "ms" ) {
        multiplier = 0.001;
      } else {
        return -1;
      }

      // Valid multiplier
      return parseFloat( t_in.substr( 0, i ) ) * multiplier + offset;
    };

    // creates an object of all atrributes keyd by name
    var createTrack = function( name, attributes ) {
      var track = {};
      track[name] = attributes;
      return track;
    };

    // Parse a node for text content
    var parseNode = function( node, timeOffset ) {
      var sub = {};

      // Trim left and right whitespace from text and change non-explicit line breaks to spaces
      sub.text = node.textContent.replace(/^[\s]+|[\s]+$/gm, "").replace(/(?:\r\n|\r|\n)/gm, "<br />");
      sub.id = node.getAttribute( "xml:id" ) || node.getAttribute( "id" );
      sub.start = toSeconds ( node.getAttribute( "begin" ), timeOffset );
      sub.end = toSeconds( node.getAttribute( "end" ), timeOffset );
      sub.target = region;

      if ( sub.end < 0 ) {
        // No end given, infer duration if possible
        // Otherwise, give end as MAX_VALUE
        sub.end = toSeconds( node.getAttribute( "duration" ), 0 );

        if ( sub.end >= 0 ) {
          sub.end += sub.start;
        } else {
          sub.end = Number.MAX_VALUE;
        }
      }

      return sub;
    };

    // Parse the children of the given node
    var parseChildren = function( node, timeOffset ) {
      var currNode = node.firstChild,
          sub,
          newOffset;

      while ( currNode ) {
        if ( currNode.nodeType === 1 ) {
          if ( currNode.nodeName === "p" ) {
            // p is a teextual node, process contents as subtitle
            sub = parseNode( currNode, timeOffset );
            returnData.data.push( createTrack( "subtitle", sub ) );
            numTracks++;
          } else if ( currNode.nodeName === "div" ) {
            // div is container for subtitles, recurse
            newOffset = toSeconds( currNode.getAttribute("begin") );

            if (newOffset < 0 ) {
              newOffset = timeOffset;
            }

            parseChildren( currNode, newOffset );
          }
        }

        currNode = currNode.nextSibling;
      }
    };

    // Null checks
    if ( !data.xml || !data.xml.documentElement || !( node = data.xml.documentElement.firstChild ) ) {
      return returnData;
    }

    // Find body tag
    while ( node.nodeName !== "body" ) {
      node = node.nextSibling;
    }

    region = "";
    parseChildren( node, 0 );

    return returnData;
  });

})( Popcorn );
// PARSER: 0.1 TTXT

(function (Popcorn) {

  /**
   * TTXT popcorn parser plug-in
   * Parses subtitle files in the TTXT format.
   * Style information is ignored.
   * Data parameter is given by Popcorn, will need an xml.
   * Xml is the file contents to be parsed as a DOM tree
   *
   * @param {Object} data
   *
   * Example:
     <TextSample sampleTime="00:00:00.000" text=""></TextSample>
   */
  Popcorn.parser( "parseTTXT", function( data ) {

    // declare needed variables
    var returnData = {
          title: "",
          remote: "",
          data: []
        };

    // Simple function to convert HH:MM:SS.MMM to SS.MMM
    // Assume valid, returns 0 on error
    var toSeconds = function(t_in) {
      var t = t_in.split(":");
      var time = 0;

      try {
        return parseFloat(t[0], 10)*60*60 + parseFloat(t[1], 10)*60 + parseFloat(t[2], 10);
      } catch (e) { time = 0; }

      return time;
    };

    // creates an object of all atrributes keyed by name
    var createTrack = function( name, attributes ) {
      var track = {};
      track[name] = attributes;
      return track;
    };

    // this is where things actually start
    var node = data.xml.lastChild.lastChild; // Last Child of TextStreamHeader
    var lastStart = Number.MAX_VALUE;
    var cmds = [];

    // Work backwards through DOM, processing TextSample nodes
    while (node) {
      if ( node.nodeType === 1 && node.nodeName === "TextSample") {
        var sub = {};
        sub.start = toSeconds(node.getAttribute('sampleTime'));
        sub.text = node.getAttribute('text');

        if (sub.text) { // Only process if text to display
          // Infer end time from prior element, ms accuracy
          sub.end = lastStart - 0.001;
          cmds.push( createTrack("subtitle", sub) );
        }
        lastStart = sub.start;
      }
      node = node.previousSibling;
    }

    returnData.data = cmds.reverse();

    return returnData;
  });

})( Popcorn );
// PARSER: 0.3 WebSRT/VTT

(function ( Popcorn ) {
  /**
   * WebVTT popcorn parser plug-in
   * Parses subtitle files in the WebVTT format.
   * Specification here: http://www.whatwg.org/specs/web-apps/current-work/webvtt.html
   * Styles which appear after timing information are presently ignored.
   * Inline styling tags follow HTML conventions and are left in for the browser to handle (or ignore if VTT-specific)
   * Data parameter is given by Popcorn, text property holds file contents.
   * Text is the file contents to be parsed
   *
   * @param {Object} data
   *
   * Example:
    00:32.500 --> 00:00:33.500 A:start S:50% D:vertical L:98%
    <v Neil DeGrass Tyson><i>Laughs</i>
   */
  Popcorn.parser( "parseVTT", function( data ) {

    // declare needed variables
    var retObj = {
          title: "",
          remote: "",
          data: []
        },
        subs = [],
        i = 0,
        len = 0,
        lines,
        text,
        sub,
        rNewLine = /(?:\r\n|\r|\n)/gm;

    // Here is where the magic happens
    // Split on line breaks
    lines = data.text.split( rNewLine );
    len = lines.length;

    // Check for BOF token
    if ( len === 0 || lines[ 0 ] !== "WEBVTT" ) {
      return retObj;
    }

    i++;

    while ( i < len ) {
      text = [];

      try {
        i = skipWhitespace( lines, len, i );
        sub = parseCueHeader( lines[ i++ ] );

        // Build single line of text from multi-line subtitle in file
        while ( i < len && lines[ i ] ) {
          text.push( lines[ i++ ] );
        }

        // Join lines together to one and build subtitle text
        sub.text = text.join( "<br />" );
        subs.push( createTrack( "subtitle", sub ) );
      } catch ( e ) {
        i = skipNonWhitespace( lines, len, i );
      }
    }

    retObj.data = subs;
    return retObj;
  });

  // [HH:]MM:SS.mmm string to SS.mmm float
  // Throws exception if invalid
  function toSeconds ( t_in ) {
    var t = t_in.split( ":" ),
        l = t_in.length,
        time;

    // Invalid time string provided
    if ( l !== 12 && l !== 9 ) {
      throw "Bad cue";
    }

    l = t.length - 1;

    try {
      time = parseInt( t[ l-1 ], 10 ) * 60 + parseFloat( t[ l ], 10 );

      // Hours were given
      if ( l === 2 ) {
        time += parseInt( t[ 0 ], 10 ) * 3600;
      }
    } catch ( e ) {
      throw "Bad cue";
    }

    return time;
  }

  function createTrack( name, attributes ) {
    var track = {};
    track[ name ] = attributes;
    return track;
  }

  function parseCueHeader ( line ) {
    var lineSegments,
        args,
        sub = {},
        rToken = /-->/,
        rWhitespace = /[\t ]+/;

    if ( !line || line.indexOf( "-->" ) === -1 ) {
      throw "Bad cue";
    }

    lineSegments = line.replace( rToken, " --> " ).split( rWhitespace );

    if ( lineSegments.length < 2 ) {
      throw "Bad cue";
    }

    sub.id = line;
    sub.start = toSeconds( lineSegments[ 0 ] );
    sub.end = toSeconds( lineSegments[ 2 ] );

    return sub;
  }

  function skipWhitespace ( lines, len, i ) {
    while ( i < len && !lines[ i ] ) {
      i++;
    }

    return i;
  }

  function skipNonWhitespace ( lines, len, i ) {
    while ( i < len && lines[ i ] ) {
      i++;
    }

    return i;
  }
})( Popcorn );
// PARSER: 0.1 XML

(function (Popcorn) {

  /**
   *
   *
   */
  Popcorn.parser( "parseXML", "XML", function( data ) {

    // declare needed variables
    var returnData = {
          title: "",
          remote: "",
          data: []
        },
        manifestData = {};

    // Simple function to convert 0:05 to 0.5 in seconds
    // acceptable formats are HH:MM:SS:MM, MM:SS:MM, SS:MM, SS
    var toSeconds = function(time) {
      var t = time.split(":");
      if (t.length === 1) {
        return parseFloat(t[0], 10);
      } else if (t.length === 2) {
        return parseFloat(t[0], 10) + parseFloat(t[1] / 12, 10);
      } else if (t.length === 3) {
        return parseInt(t[0] * 60, 10) + parseFloat(t[1], 10) + parseFloat(t[2] / 12, 10);
      } else if (t.length === 4) {
        return parseInt(t[0] * 3600, 10) + parseInt(t[1] * 60, 10) + parseFloat(t[2], 10) + parseFloat(t[3] / 12, 10);
      }
    };

    // turns a node tree element into a straight up javascript object
    // also converts in and out to start and end
    // also links manifest data with ids
    var objectifyAttributes = function ( nodeAttributes ) {

      var returnObject = {};

      for ( var i = 0, nal = nodeAttributes.length; i < nal; i++ ) {

        var key  = nodeAttributes.item(i).nodeName,
            data = nodeAttributes.item(i).nodeValue;

        // converts in into start
        if (key === "in") {
          returnObject.start = toSeconds( data );
        // converts out into end
        } else if ( key === "out" ){
          returnObject.end = toSeconds( data );
        // this is where ids in the manifest are linked
        } else if ( key === "resourceid" ) {
          Popcorn.extend( returnObject, manifestData[data] );
        // everything else
        } else {
          returnObject[key] = data;
        }

      }

      return returnObject;
    };

    // creates an object of all atrributes keyd by name
    var createTrack = function( name, attributes ) {
      var track = {};
      track[name] = attributes;
      return track;
    };

    // recursive function to process a node, or process the next child node
    var parseNode = function ( node, allAttributes, manifest ) {
      var attributes = {};
      Popcorn.extend( attributes, allAttributes, objectifyAttributes( node.attributes ), { text: node.textContent } );

      var childNodes = node.childNodes;

      // processes the node
      if ( childNodes.length < 1 || ( childNodes.length === 1 && childNodes[0].nodeType === 3 ) ) {

        if ( !manifest ) {
          returnData.data.push( createTrack( node.nodeName, attributes ) );
        } else {
          manifestData[attributes.id] = attributes;
        }

      // process the next child node
      } else {

        for ( var i = 0; i < childNodes.length; i++ ) {

          if ( childNodes[i].nodeType === 1 ) {
            parseNode( childNodes[i], attributes, manifest );
          }

        }
      }
    };

    // this is where things actually start
    var x = data.documentElement.childNodes;

    for ( var i = 0, xl = x.length; i < xl; i++ ) {

      if ( x[i].nodeType === 1 ) {

        // start the process of each main node type, manifest or timeline
        if ( x[i].nodeName === "manifest" ) {
          parseNode( x[i], {}, true );
        } else { // timeline
          parseNode( x[i], {}, false );
        }

      }
    }

    return returnData;
  });

})( Popcorn );
// Popcorn Soundcloud Player Wrapper
( function( Popcorn, global ) {
  /**
  * Soundcloud wrapper for Popcorn.
  * This player adds enables Popcorn.js to handle Soundcloud audio. It does so by masking an embedded Soundcloud Flash object
  * as a video and implementing the HTML5 Media Element interface.
  *
  * You can configure the video source and dimensions in two ways:
  *  1. Use the embed code path supplied by Soundcloud the id of the desired location into a new Popcorn.soundcloud object.
  *     Width and height can be configured throughh CSS.
  *
  *    <div id="player_1" style="width: 500px; height: 81px"></div>
  *    <script type="text/javascript">
  *      document.addEventListener("DOMContentLoaded", function() {
  *        var popcorn = Popcorn( Popcorn.soundcloud( "player_1", "http://soundcloud.com/forss/flickermood" ));
  *      }, false);
  *    </script>
  *
  *  2. Width and height may also be configured directly with the player; this will override any CSS. This is useful for
  *     when different sizes are desired. for multiple players within the same parent container.
  *
  *     <div id="player_1"></div>
  *     <script type="text/javascript">
  *       document.addEventListener("DOMContentLoaded", function() {
  *       var popcorn = Popcorn( Popcorn.soundcloud( "player_1", "http://soundcloud.com/forss/flickermood", {
  *         width: "500",                                     // Optional, will default to CSS values
  *         height: "81"                                      // Optional, will default to CSS values
  *       }));
  *       }, false);
  *     </script>
  *
  * The player can be further configured to integrate with the SoundCloud API:
  *
  * var popcorn = Popcorn( Popcorn.soundcloud( "player_1", "http://soundcloud.com/forss/flickermood", {
  *   width: "100%",                                    // Optional, the width for the player. May also be as '##px'
  *                                                     //           Defaults to the maximum possible width
  *   height: "81px",                                   // Optional, the height for the player. May also be as '###%'
  *                                                     //           Defaults to 81px
  *   api: {                                            // Optional, information for Soundcloud API interaction
  *     key: "abcdefsdfsdf",                            // Required for API interaction. The Soundcloud API key
  *     commentdiv: "divId_for_output",                 // Required for comment retrieval, the Div Id for outputting comments.
  *     commentformat: function( comment ) {}           // Optional, a function to format a comment. Returns HTML string
  *   }
  * }));
  *
  * Comments are retrieved from Soundcloud when the player is registered with Popcorn by calling the registerWithPopcorn()
  * function. For this to work, the api_key and commentdiv attributes must be set. Comments are output by default similar to
  * how Soundcloud formats them in-player, but a custom formatting function may be supplied. It receives a comment object and
  * the current date. A comment object has:
  *
  * var comment = {
  *   start: 0,                           // Required. Start time in ms.
  *   date: new Date(),                   // Required. Date comment wasa posted.
  *   text: "",                           // Required. Comment text
  *   user: {                             // Required. Describes the user who posted the comment
  *     name: "",                         // Required. User name
  *     profile: "",                      // Required. User profile link
  *     avatar: ""                        // Required. User avatar link
  *   }
  * }
  *
  * These events are completely custom-implemented and may be subscribed to at any time:
  *   canplaythrough
  *   durationchange
  *   load
  *   loadedmetadata
  *   loadstart
  *   play
  *   readystatechange
  *   volumechange
  *
  * These events are related to player functionality and must be subscribed to during or after the load event:
  *   canplay
  *   ended
  *   error
  *   pause
  *   playing
  *   progress
  *   seeked
  *   timeupdate
  *
  * These events are not supported:
  *   abort
  *   emptied
  *   loadeddata
  *   ratechange
  *   seeking
  *   stalled
  *   suspend
  *   waiting
  *
  * Supported media attributes:
  *   autoplay ( via Popcorn )
  *   currentTime
  *   defaultPlaybackRate ( get only )
  *   duration ( get only )
  *   ended ( get only )
  *   initialTime ( get only, always 0 )
  *   loop ( get only, set by calling setLoop() )
  *   muted ( get only )
  *   paused ( get only )
  *   playbackRate ( get only )
  *   played ( get only, 0/1 only )
  *   readyState ( get only )
  *   src ( get only )
  *   volume
  *
  *   load() function
  *   mute() function ( toggles on/off )
  *   play() function
  *   pause() function
  *
  * Unsupported media attributes:
  *   buffered
  *   networkState
  *   preload
  *   seekable
  *   seeking
  *   startOffsetTime
  *
  *   canPlayType() function
  */

  // Trackers
  var timeupdateInterval = 33,
      timeCheckInterval = 0.25,
      abs = Math.abs,
      floor = Math.floor,
      round = Math.round,
      registry = {};

  function hasAllDependencies() {
    return global.swfobject && global.soundcloud;
  }

  // Borrowed from: http://www.quirksmode.org/dom/getstyles.html
  // Gets the style for the given element
  function getStyle( elem, styleProp ) {
    if ( elem.currentStyle ) {
      // IE way
      return elem.currentStyle[styleProp];
    } else if ( global.getComputedStyle ) {
      // Firefox, Chrome, et. al
      return document.defaultView.getComputedStyle( elem, null ).getPropertyValue( styleProp );
    }
  }

  function formatComment( comment ) {
    // Calclate the difference between d and now, express as "n units ago"
    function ago( d ) {
      var diff = ( ( new Date() ).getTime() - d.getTime() )/1000;

      function pluralize( value, unit ) {
        return value + " " + unit + ( value > 1 ? "s" : "") + " ago";
      }

      if ( diff < 60 ) {
        return pluralize( round( diff ), "second" );
      }
      diff /= 60;

      if ( diff < 60 ) {
        return pluralize( round( diff ), "minute" );
      }
      diff /= 60;

      if ( diff < 24 ) {
        return pluralize( round( diff ), "hour" );
      }
      diff /= 24;

      // Rough approximation of months
      if ( diff < 30 ) {
        return pluralize( round( diff ), "day" );
      }

      if ( diff < 365 ) {
        return pluralize( round( diff/30 ), "month" );
      }

      return pluralize( round( diff/365 ), "year" );
    }

    // Converts sec to min.sec
    function timeToFraction ( totalSec ) {
      var min = floor( totalSec / 60 ),
          sec = round( totalSec % 60 );

      return min + "." + ( sec < 10 ? "0" : "" ) + sec;
    }

    return '<div><a href="' + comment.user.profile + '">' +
           '<img width="16px height="16px" src="' + comment.user.avatar + '"></img>' +
           comment.user.name + '</a> at ' + timeToFraction( comment.start ) + ' '  +
           ago( comment.date )  +
           '<br />' + comment.text + '</span>';
  }

  function isReady( self ) {
    if ( !hasAllDependencies() ) {
      setTimeout( function() {
        isReady( self );
      }, 15 );
      return;
    }

    var flashvars = {
      enable_api: true,
      object_id: self._playerId,
      url: self.src,
      // Hide comments in player if showing them elsewhere
      show_comments: !self._options.api.key && !self._options.api.commentdiv
    },
    params = {
      allowscriptaccess: "always",
      // This is so we can overlay html ontop of Flash
      wmode: 'transparent'
    },
    attributes = {
      id: self._playerId,
      name: self._playerId
    },
    actualTarget = document.createElement( 'div' );

    actualTarget.setAttribute( "id", self._playerId );
    self._container.appendChild( actualTarget );

    swfobject.embedSWF( "http://player.soundcloud.com/player.swf", self._playerId, self.offsetWidth, self.height, "9.0.0", "expressInstall.swf", flashvars, params, attributes );
  }

  Popcorn.getScript( "http://ajax.googleapis.com/ajax/libs/swfobject/2.2/swfobject.js" );

  // Source file originally from 'https://github.com/soundcloud/Widget-JS-API/raw/master/soundcloud.player.api.js'
  Popcorn.getScript( "http://popcornjs.org/code/players/soundcloud/lib/soundcloud.player.api.js", function() {
    // Play event is fired twice when player is first started. Ignore second one
    var ignorePlayEvt = 1;

    // Register the wrapper's load event with the player
    soundcloud.addEventListener( 'onPlayerReady', function( object, data ) {
      var wrapper = registry[object.api_getFlashId()];

      wrapper.swfObj = object;
      wrapper.duration = object.api_getTrackDuration();
      wrapper.currentTime = object.api_getTrackPosition();
      // This eliminates volumechangee event from firing on load
      wrapper.volume = wrapper.previousVolume =  object.api_getVolume()/100;

      // The numeric id of the track for use with Soundcloud API
      wrapper._mediaId = data.mediaId;

      wrapper.dispatchEvent( 'load' );
      wrapper.dispatchEvent( 'canplay' );
      wrapper.dispatchEvent( 'durationchange' );

      wrapper.timeupdate();
    });

    // Register events for when the flash player plays a track for the first time
    soundcloud.addEventListener( 'onMediaStart', function( object, data ) {
      var wrapper = registry[object.api_getFlashId()];
      wrapper.played = 1;
      wrapper.dispatchEvent( 'playing' );
    });

    // Register events for when the flash player plays a track
    soundcloud.addEventListener( 'onMediaPlay', function( object, data ) {
      if ( ignorePlayEvt ) {
        ignorePlayEvt = 0;
        return;
      }

      var wrapper = registry[object.api_getFlashId()];
      wrapper.dispatchEvent( 'play' );
    });

    // Register events for when the flash player pauses a track
    soundcloud.addEventListener( 'onMediaPause', function( object, data ) {
      var wrapper = registry[object.api_getFlashId()];
      wrapper.dispatchEvent( 'pause' );
    });

    // Register events for when the flash player is buffering
    soundcloud.addEventListener( 'onMediaBuffering', function( object, data ) {
      var wrapper = registry[object.api_getFlashId()];

      wrapper.dispatchEvent( 'progress' );

      if ( wrapper.readyState === 0 ) {
        wrapper.readyState = 3;
        wrapper.dispatchEvent( "readystatechange" );
      }
    });

    // Register events for when the flash player is done buffering
    soundcloud.addEventListener( 'onMediaDoneBuffering', function( object, data ) {
      var wrapper = registry[object.api_getFlashId()];
      wrapper.dispatchEvent( 'canplaythrough' );
    });

    // Register events for when the flash player has finished playing
    soundcloud.addEventListener( 'onMediaEnd', function( object, data ) {
      var wrapper = registry[object.api_getFlashId()];
      wrapper.paused = 1;
      //wrapper.pause();
      wrapper.dispatchEvent( 'ended' );
    });

    // Register events for when the flash player has seeked
    soundcloud.addEventListener( 'onMediaSeek', function( object, data ) {
      var wrapper = registry[object.api_getFlashId()];

      wrapper.setCurrentTime( object.api_getTrackPosition() );

      if ( wrapper.paused ) {
        wrapper.dispatchEvent( "timeupdate" );
      }
    });

    // Register events for when the flash player has errored
    soundcloud.addEventListener( 'onPlayerError', function( object, data ) {
      var wrapper = registry[object.api_getFlashId()];
      wrapper.dispatchEvent( 'error' );
    });
  });

  Popcorn.soundcloud = function( containerId, src, options ) {
    return new Popcorn.soundcloud.init( containerId, src, options );
  };

  // A constructor, but we need to wrap it to allow for "static" functions
  Popcorn.soundcloud.init = (function() {
    function pullFromContainer( that ) {
      var options = that._options,
          container = that._container,
          bounds = container.getBoundingClientRect(),
          tmp,
          undef;

      that.width = options.width || getStyle( container, "width" ) || "100%";
      that.height = options.height || getStyle( container, "height" ) || "81px";
      that.src = options.src;
      that.autoplay = options.autoplay;

      if ( parseFloat( that.height, 10 ) !== 81 ) {
        that.height = "81px";
      }

      that.offsetLeft = bounds.left;
      that.offsetTop = bounds.top;
      that.offsetHeight = parseFloat( that.height, 10 );
      that.offsetWidth = parseFloat( that.width, 10 );

      // Width and height may've been specified as a %, find the value now in case a plugin needs it (like subtitle)
      if ( /[\d]+%/.test( that.width ) ) {
        tmp = getStyle( container, "width" );
        that._container.style.width = that.width;
        that.offsetWidth = that._container.offsetWidth;
        that._container.style.width = tmp;
      }

      if ( /[\d]+%/.test( that.height ) ) {
        tmp = getStyle( container, "height" );
        that._container.style.height = that.height;
        that.offsetHeight = that._container.offsetHeight;
        that._container.style.height = tmp;
      }
    }

    // If container id is not supplied, assumed to be same as player id
    var ctor = function ( containerId, src, options ) {
      if ( !containerId ) {
        throw "Must supply an id!";
      } else if ( !src ) {
        throw "Must supply a source!";
      } else if ( /file/.test( location.protocol ) ) {
        throw "Must run from a web server!";
      }

      var container = this._container = document.getElementById( containerId );

      if ( !container ) {
        throw "Could not find that container in the DOM!";
      }

      options = options || {};
      options.api = options.api || {};
      options.target = containerId;
      options.src = src;
      options.api.commentformat = options.api.commentformat || formatComment;

      this._mediaId = 0;
      this._listeners = {};
      this._playerId = Popcorn.guid( options.target );
      this._containerId = options.target;
      this._options = options;
      this._comments = [];
      this._popcorn = null;

      pullFromContainer( this );

      this.duration = 0;
      this.volume = 1;
      this.currentTime = 0;
      this.ended = 0;
      this.paused = 1;
      this.readyState = 0;
      this.playbackRate = 1;

      this.top = 0;
      this.left = 0;

      this.autoplay = null;
      this.played = 0;

      this.addEventListener( "load", function() {
        var boundRect = this.getBoundingClientRect();

        this.top = boundRect.top;
        this.left = boundRect.left;

        this.offsetWidth = this.swfObj.offsetWidth;
        this.offsetHeight = this.swfObj.offsetHeight;
        this.offsetLeft = this.swfObj.offsetLeft;
        this.offsetTop = this.swfObj.offsetTop;
      });

      registry[ this._playerId ] = this;
      isReady( this );
    };
    return ctor;
  })();

  Popcorn.soundcloud.init.prototype = Popcorn.soundcloud.prototype;

  // Sequence object prototype
  Popcorn.extend( Popcorn.soundcloud.prototype, {
    // Set the volume as a value between 0 and 1
    setVolume: function( val ) {
      if ( !val && val !== 0 ) {
        return;
      }

      // Normalize in case outside range of expected values of 0 .. 1
      if ( val < 0 ) {
        val = -val;
      }

      if ( val > 1 ) {
        val %= 1;
      }

      // HTML video expects to be 0.0 -> 1.0, Flash object expects 0-100
      this.volume = this.previousVolume = val;
      this.swfObj.api_setVolume( val*100 );
      this.dispatchEvent( "volumechange" );
    },
    // Seeks the video
    setCurrentTime: function ( time ) {
      if ( !time && time !== 0 ) {
        return;
      }

      this.currentTime = this.previousCurrentTime = time;
      this.ended = time >= this.duration;

      // Fire events for seeking and time change
      this.dispatchEvent( "seeked" );
    },
    // Play the video
    play: function() {
      // In case someone is cheeky enough to try this before loaded
      if ( !this.swfObj ) {
        this.addEventListener( "load", this.play );
        return;
      } else if ( !this.paused ) {
        // No need to process if already playing
        return;
      }

      this.paused = 0;
      this.swfObj.api_play();
    },
    // Pause the video
    pause: function() {
      // In case someone is cheeky enough to try this before loaded
      if ( !this.swfObj ) {
        this.addEventListener( "load", this.pause );
        return;
      } else if ( this.paused ) {
        // No need to process if already playing
        return;
      }

      this.paused = 1;
      this.swfObj.api_pause();
    },
    // Toggle video muting
    // Unmuting will leave it at the old value
    mute: function() {
      // In case someone is cheeky enough to try this before loaded
      if ( !this.swfObj ) {
        this.addEventListener( "load", this.mute );
        return;
      }

      if ( !this.muted() ) {
        this.oldVol = this.volume;

        if ( this.paused ) {
          this.setVolume( 0 );
        } else {
          this.volume = 0;
        }
      } else {
        if ( this.paused ) {
          this.setVolume( this.oldVol );
        } else {
          this.volume = this.oldVol;
        }
      }
    },
    muted: function() {
      return this.volume === 0;
    },
    // Force loading by playing the player. Pause afterwards
    load: function() {
      // In case someone is cheeky enough to try this before loaded
      if ( !this.swfObj ) {
        this.addEventListener( "load", this.load );
        return;
      }

      this.play();
      this.pause();
    },
    // Hook an event listener for the player event into internal event system
    // Stick to HTML conventions of add event listener and keep lowercase, without prepending "on"
    addEventListener: function( evt, fn ) {
      if ( !this._listeners[evt] ) {
        this._listeners[evt] = [];
      }

      this._listeners[evt].push( fn );
      return fn;
    },
    dispatchEvent: function( evt ) {
      var self = this,
          evtName = evt.type || evt;

      // Manually triggered a UI event, have it invoke rather than just the event handlers
      if ( evtName === "play" && this.paused || evtName === "pause" && !this.paused ) {
        this[evtName]();
        return;
      }

      Popcorn.forEach( this._listeners[evtName], function( fn ) {
        fn.call( self );
      });
    },
    timeupdate: function() {
      var self = this,
          checkedVolume = this.swfObj.api_getVolume()/100,
          seeked = 0;

      // If has been changed through setting currentTime attribute
      if ( abs( this.currentTime - this.previousCurrentTime ) > timeCheckInterval ) {
        // Has programatically set the currentTime
        this.swfObj.api_seekTo( this.currentTime );
        seeked = 1;
      } else {
        this.previousCurrentTime = this.currentTime = this.swfObj.api_getTrackPosition();
      }

      // If has been changed throughh volume attribute
      if ( checkedVolume !== this.previousVolume ) {
        this.setVolume( checkedVolume );
      } else if ( this.volume !== this.previousVolume ) {
        this.setVolume( this.volume );
      }

      if ( !this.paused ) {
        this.dispatchEvent( 'timeupdate' );
      }

      if( !self.ended ) {
        setTimeout( function() {
          self.timeupdate.call( self );
        }, timeupdateInterval);
      }
    },

    getBoundingClientRect: function() {
      var b,
          self = this;

      if ( this.swfObj ) {
        b = this.swfObj.getBoundingClientRect();

        return {
          bottom: b.bottom,
          left: b.left,
          right: b.right,
          top: b.top,

          //  These not guaranteed to be in there
          width: b.width || ( b.right - b.left ),
          height: b.height || ( b.bottom - b.top )
        };
      } else {
        //container = document.getElementById( this.playerId );
        tmp = this._container.getBoundingClientRect();

        // Update bottom, right for expected values once the container loads
        return {
          left: tmp.left,
          top: tmp.top,
          width: self.offsetWidth,
          height: self.offsetHeight,
          bottom: tmp.top + this.width,
          right: tmp.top + this.height
        };
      }
    },

    registerPopcornWithPlayer: function( popcorn ) {
      if ( !this.swfObj ) {
        this.addEventListener( "load", function() {
          this.registerPopcornWithPlayer( popcorn );
        });
        return;
      }

      this._popcorn = popcorn;

      var api = this._options.api;

      if ( api.key && api.commentdiv ) {
        var self = this;

        Popcorn.xhr({
          url: "http://api.soundcloud.com/tracks/" + self._mediaId + "/comments.js?consumer_key=" + api.key,
          success: function( data ) {
            Popcorn.forEach( data.json, function ( obj ) {
              self.addComment({
                start: obj.timestamp/1000,
                date: new Date( obj.created_at ),
                text: obj.body,
                user: {
                  name: obj.user.username,
                  profile: obj.user.permalink_url,
                  avatar: obj.user.avatar_url
                }
              });
            });
          }
        });
      }
    }
  });

  Popcorn.extend( Popcorn.soundcloud.prototype, {
    addComment: function( obj, displayFn ) {
      var self = this,
          comment = {
            start: obj.start || 0,
            date: obj.date || new Date(),
            text: obj.text || "",
            user: {
              name: obj.user.name || "",
              profile: obj.user.profile || "",
              avatar: obj.user.avatar || ""
            },
            display: function() {
              return ( displayFn || self._options.api.commentformat )( comment );
            }
          };

      this._comments.push( comment );

      if ( !this._popcorn ) {
        return;
      }

      this._popcorn.subtitle({
        start: comment.start,
        target: this._options.api.commentdiv,
        display: 'inline',
        language: 'en',
        text: comment.display()
      });
    }
  });
})( Popcorn, window );(function() {

  // global callback for vimeo.. yuck.
  vimeo_player_loaded = function( playerId ) {
    vimeo_player_loaded[ playerId ] && vimeo_player_loaded[ playerId ]();
  };
  vimeo_player_loaded.seek = {};
  vimeo_player_loaded.loadProgress = {};
  vimeo_player_loaded.play = {};
  vimeo_player_loaded.pause = {};

  Popcorn.player( "vimeo", {
    _setup: function( options ) {

      var media = this,
          vimeoObject,
          vimeoContainer = document.createElement( "div" ),
          currentTime = 0,
          seekTime = 0,
          seeking = false,
          volumeChanged = false,
          lastMuted = false,
          lastVolume = 0,
          height,
          width;

      vimeoContainer.id = media.id + Popcorn.guid();

      media.appendChild( vimeoContainer );

      // setting vimeo player's height and width, default to 560 x 315
      width = media.style.width ? ""+media.offsetWidth : "560";
      height = media.style.height ? ""+media.offsetHeight : "315";

      var vimeoInit = function() {

        var flashvars,
            params,
            attributes = {},
            src = media.src,
            toggleMuteVolume = 0,
            loadStarted = false;

        vimeo_player_loaded[ vimeoContainer.id ] = function() {
          vimeoObject = document.getElementById( vimeoContainer.id );

          vimeo_player_loaded.seek[ vimeoContainer.id ] = function( time ) {
            if( time !== currentTime ) {
              currentTime = time;
              media.dispatchEvent( "seeked" );
              media.dispatchEvent( "timeupdate" );
            }
          };

          vimeo_player_loaded.play[ vimeoContainer.id ] = function() {
            if ( media.paused ) {
              media.paused = false;
              media.dispatchEvent( "play" );

              media.dispatchEvent( "playing" );
              timeUpdate();
            }
          };

          vimeo_player_loaded.pause[ vimeoContainer.id ] = function() {
            if ( !media.paused ) {
              media.paused = true;
              media.dispatchEvent( "pause" );
            }
          };

          vimeo_player_loaded.loadProgress[ vimeoContainer.id ] = function( progress ) {

            if ( !loadStarted ) {
              loadStarted = true;
              media.dispatchEvent( "loadstart" );
            }

            if ( progress.percent === 100 ) {
              media.dispatchEvent( "canplaythrough" );
            }
          };

          vimeoObject.api_addEventListener( "seek", "vimeo_player_loaded.seek." + vimeoContainer.id );
          vimeoObject.api_addEventListener( "loadProgress", "vimeo_player_loaded.loadProgress." + vimeoContainer.id );
          vimeoObject.api_addEventListener( "play", "vimeo_player_loaded.play." + vimeoContainer.id );
          vimeoObject.api_addEventListener( "pause", "vimeo_player_loaded.pause." + vimeoContainer.id );

          var timeUpdate = function() {
            if ( !media.paused ) {
              currentTime = vimeoObject.api_getCurrentTime();
              media.dispatchEvent( "timeupdate" );
              setTimeout( timeUpdate, 10 );
            }
          },

          isMuted = function() {

            return vimeoObject.api_getVolume() === 0;
          };

          var volumeUpdate = function() {

            var muted = isMuted(),
            vol = vimeoObject.api_getVolume();
            if ( lastMuted !== muted ) {
              lastMuted = muted;
              media.dispatchEvent( "volumechange" );
            }

            if ( lastVolume !== vol ) {
              lastVolume = vol;
              media.dispatchEvent( "volumechange" );
            }

            setTimeout( volumeUpdate, 250 );
          };

          media.play = function() {
            media.paused = false;
            media.dispatchEvent( "play" );

            media.dispatchEvent( "playing" );
            timeUpdate();
            vimeoObject.api_play();
          };

          media.pause = function() {

            if ( !media.paused ) {

              media.paused = true;
              media.dispatchEvent( "pause" );
              vimeoObject.api_pause();
            }
          };

          Popcorn.player.defineProperty( media, "currentTime", {

            set: function( val ) {

              if ( !val ) {
                return currentTime;
              }

              currentTime = seekTime = +val;
              seeking = true;

              media.dispatchEvent( "seeked" );
              media.dispatchEvent( "timeupdate" );
              vimeoObject.api_seekTo( currentTime );

              return currentTime;
            },

            get: function() {

              return currentTime;
            }
          });

          Popcorn.player.defineProperty( media, "muted", {

            set: function( val ) {

              if ( isMuted() !== val ) {

                if ( val ) {
                  toggleMuteVolume = vimeoObject.api_getVolume();
                  vimeoObject.api_setVolume( 0 );
                } else {

                  vimeoObject.api_setVolume( toggleMuteVolume );
                }
              }
            },
            get: function() {

              return isMuted();
            }
          });

          Popcorn.player.defineProperty( media, "volume", {

            set: function( val ) {

              if ( !val || typeof val !== "number" || ( val < 0 || val > 1 ) ) {
                return vimeoObject.api_getVolume() / 100;
              }

              if ( vimeoObject.api_getVolume() !== val ) {
                vimeoObject.api_setVolume( val * 100 );
                lastVolume = vimeoObject.api_getVolume();
                media.dispatchEvent( "volumechange" );
              }

              return vimeoObject.api_getVolume() / 100;
            },
            get: function() {

              return vimeoObject.api_getVolume() / 100;
            }
          });

          media.readyState = 4;
          media.dispatchEvent( "canplaythrough" );
          media.dispatchEvent( "load" );
          media.duration = vimeoObject.api_getDuration();
          media.dispatchEvent( "durationchange" );
          volumeUpdate();

          media.dispatchEvent( "loadeddata" );
        };

        function extractId( videoUrl ) {

          if ( !videoUrl ) {
            return;
          }

          var rPlayerUri = /^http:\/\/player\.vimeo\.com\/video\/[\d]+/i,
              rWebUrl = /vimeo\.com\/[\d]+/;

          var matches = videoUrl.match( rPlayerUri ) ? videoUrl.match( rPlayerUri )[ 0 ].substr( 30 ) : "";
          return matches ? matches : videoUrl.match( rWebUrl ) ? videoUrl.match( rWebUrl )[ 0 ].substr( 10 ) : "";
        }

        if ( !( src = extractId( src ) ) ) {

          throw "Invalid Video Id";
        }

        flashvars = {
          clip_id: src,
          js_api: 1,
          js_swf_id: vimeoContainer.id
        };

        //  extend options from user to flashvars. NOTE: Videos owned by Plus Vimeo users may override these options
        Popcorn.extend( flashvars, options );

        params = {
          allowscriptaccess: "always",
          allowfullscreen: "true",
          wmode: "transparent"
        };

        swfobject.embedSWF( "//vimeo.com/moogaloop.swf", vimeoContainer.id,
                            width, height, "9.0.0", "expressInstall.swf",
                            flashvars, params, attributes );

      };

      if ( !window.swfobject ) {

        Popcorn.getScript( "//ajax.googleapis.com/ajax/libs/swfobject/2.2/swfobject.js", vimeoInit );
      } else {

        vimeoInit();
      }
    }
  });
})();// A global callback for youtube... that makes me angry
var onYouTubePlayerReady = function( containerId ) {

  onYouTubePlayerReady[ containerId ] && onYouTubePlayerReady[ containerId ]();
};
onYouTubePlayerReady.stateChangeEventHandler = {};

Popcorn.player( "youtube", {
  _setup: function( options ) {

    var media = this,
        youtubeObject,
        container = document.createElement( "div" ),
        currentTime = 0,
        seekTime = 0,
        seeking = false,

        // state code for volume changed polling
        volumeChanged = false,
        lastMuted = false,
        lastVolume = 100;

    container.id = media.id + Popcorn.guid();

    media.appendChild( container );

    var youtubeInit = function() {

      var flashvars,
          params,
          attributes,
          src,
          width,
          height,
          query;

      // expose a callback to this scope, that is called from the global callback youtube calls
      onYouTubePlayerReady[ container.id ] = function() {

        youtubeObject = document.getElementById( container.id );

        // more youtube callback nonsense
        onYouTubePlayerReady.stateChangeEventHandler[ container.id ] = function( state ) {

          // playing is state 1
          // paused is state 2
          if ( state === 1 ) {

            media.paused && media.play();
          // youtube fires paused events while seeking
          // this is the only way to get seeking events
          } else if ( state === 2 ) {

            // silly logic forced on me by the youtube API
            // calling youtube.seekTo triggers multiple events
            // with the second events getCurrentTime being the old time
            if ( seeking && seekTime === currentTime && seekTime !== youtubeObject.getCurrentTime() ) {

              seeking = false;
              youtubeObject.seekTo( currentTime );
              return;
            }

            currentTime = youtubeObject.getCurrentTime();
            media.dispatchEvent( "timeupdate" );
            !media.paused && media.pause();
          }
        };

        // youtube requires callbacks to be a string to a function path from the global scope
        youtubeObject.addEventListener( "onStateChange", "onYouTubePlayerReady.stateChangeEventHandler." + container.id );

        var timeupdate = function() {

          if ( !media.paused ) {

            currentTime = youtubeObject.getCurrentTime();
            media.dispatchEvent( "timeupdate" );
            setTimeout( timeupdate, 10 );
          }
        };

        var volumeupdate = function() {

          if ( lastMuted !== youtubeObject.isMuted() ) {

            lastMuted = youtubeObject.isMuted();
            media.dispatchEvent( "volumechange" );
          }

          if ( lastVolume !== youtubeObject.getVolume() ) {

            lastVolume = youtubeObject.getVolume();
            media.dispatchEvent( "volumechange" );
          }

          setTimeout( volumeupdate, 250 );
        };

        media.play = function() {

          media.paused = false;
          media.dispatchEvent( "play" );

          media.dispatchEvent( "playing" );
          timeupdate();
          youtubeObject.playVideo();
        };

        media.pause = function() {

          if ( !media.paused ) {

            media.paused = true;
            media.dispatchEvent( "pause" );
            youtubeObject.pauseVideo();
          }
        };

        Popcorn.player.defineProperty( media, "currentTime", {
          set: function( val ) {

            // make sure val is a number
            currentTime = seekTime = +val;
            seeking = true;
            media.dispatchEvent( "seeked" );
            media.dispatchEvent( "timeupdate" );
            youtubeObject.seekTo( currentTime );
            return currentTime;
          },
          get: function() {

            return currentTime;
          }
        });

        Popcorn.player.defineProperty( media, "muted", {
          set: function( val ) {

            if ( youtubeObject.isMuted() !== val ) {

              if ( val ) {

                youtubeObject.mute();
              } else {

                youtubeObject.unMute();
              }

              lastMuted = youtubeObject.isMuted();
              media.dispatchEvent( "volumechange" );
            }

            return youtubeObject.isMuted();
          },
          get: function() {

            return youtubeObject.isMuted();
          }
        });

        Popcorn.player.defineProperty( media, "volume", {
          set: function( val ) {

            if ( youtubeObject.getVolume() / 100 !== val ) {

              youtubeObject.setVolume( val * 100 );
              lastVolume = youtubeObject.getVolume();
              media.dispatchEvent( "volumechange" );
            }

            return youtubeObject.getVolume() / 100;
          },
          get: function() {

            return youtubeObject.getVolume() / 100;
          }
        });

        media.readyState = 4;
        media.dispatchEvent( "canplaythrough" );
        media.dispatchEvent( "load" );
        media.duration = youtubeObject.getDuration();
        media.dispatchEvent( "durationchange" );
        volumeupdate();

        media.dispatchEvent( "loadeddata" );
      };

      options.controls = +options.controls === 0 || +options.controls === 1 ? options.controls : 1;
      options.annotations = +options.annotations === 1 || +options.annotations === 3 ? options.annotations : 1;

      flashvars = {
        playerapiid: container.id
      };

      params = {
        wmode: "transparent",
        allowScriptAccess: "always"
      };

      attributes = {
        id: container.id
      };

      src = /^.*(?:\/|v=)(.{11})/.exec( media.src )[ 1 ];
      query = ( media.src.split( "?" )[ 1 ] || "" ).replace( /v=.{11}/, "" );

      // setting youtube player's height and width, default to 560 x 315
      width = media.style.width ? ""+media.offsetWidth : "560";
      height = media.style.height ? ""+media.offsetHeight : "315";

      swfobject.embedSWF( "//www.youtube.com/e/" + src + "?" + query + "&enablejsapi=1&playerapiid=" + container.id + "&version=3",
                          container.id, width, height, "8", null, flashvars, params, attributes );
    };

    if ( !window.swfobject ) {

      Popcorn.getScript( "//ajax.googleapis.com/ajax/libs/swfobject/2.2/swfobject.js", youtubeInit );
    } else {

      youtubeInit();
    }
  }
});

/*!
 * Popcorn.sequence
 *
 * Copyright 2011, Rick Waldron
 * Licensed under MIT license.
 *
 */

/* jslint forin: true, maxerr: 50, indent: 4, es5: true  */
/* global Popcorn: true */

// Requires Popcorn.js
(function( global, Popcorn ) {

  // TODO: as support increases, migrate to element.dataset 
  var doc = global.document, 
      location = global.location,
      rprotocol = /:\/\//, 
      // TODO: better solution to this sucky stop-gap
      lochref = location.href.replace( location.href.split("/").slice(-1)[0], "" ), 
      // privately held
      range = function(start, stop, step) {

        start = start || 0;
        stop = ( stop || start || 0 ) + 1;
        step = step || 1;
            
        var len = Math.ceil((stop - start) / step) || 0,
            idx = 0,
            range = [];

        range.length = len;

        while (idx < len) {
         range[idx++] = start;
         start += step;
        }
        return range;
      };

  Popcorn.sequence = function( parent, list ) {
    return new Popcorn.sequence.init( parent, list );
  };

  Popcorn.sequence.init = function( parent, list ) {
    
    // Video element
    this.parent = doc.getElementById( parent );
    
    // Store ref to a special ID
    this.seqId = Popcorn.guid( "__sequenced" );

    // List of HTMLVideoElements 
    this.queue = [];

    // List of Popcorn objects
    this.playlist = [];

    // Lists of in/out points
    this.inOuts = {

      // Stores the video in/out times for each video in sequence
      ofVideos: [], 

      // Stores the clip in/out times for each clip in sequences
      ofClips: []

    };

    // Store first video dimensions
    this.dims = {
      width: 0, //this.video.videoWidth,
      height: 0 //this.video.videoHeight
    };

    this.active = 0;
    this.cycling = false;
    this.playing = false;

    this.times = {
      last: 0
    };

    // Store event pointers and queues
    this.events = {

    };

    var self = this, 
        clipOffset = 0;

    // Create `video` elements
    Popcorn.forEach( list, function( media, idx ) {

      var video = doc.createElement( "video" );

      video.preload = "auto";

      // Setup newly created video element
      video.controls = true;

      // If the first, show it, if the after, hide it
      video.style.display = ( idx && "none" ) || "" ;

      // Seta registered sequence id
      video.id = self.seqId + "-" + idx ;

      // Push this video into the sequence queue
      self.queue.push( video );

      var //satisfy lint
       mIn = media["in"], 
       mOut = media["out"];
       
      // Push the in/out points into sequence ioVideos
      self.inOuts.ofVideos.push({ 
        "in": ( mIn !== undefined && mIn ) || 1,
        "out": ( mOut !== undefined && mOut ) || 0
      });

      self.inOuts.ofVideos[ idx ]["out"] = self.inOuts.ofVideos[ idx ]["out"] || self.inOuts.ofVideos[ idx ]["in"] + 2;
      
      // Set the sources
      video.src = !rprotocol.test( media.src ) ? lochref + media.src : media.src;

      // Set some squence specific data vars
      video.setAttribute("data-sequence-owner", parent );
      video.setAttribute("data-sequence-guid", self.seqId );
      video.setAttribute("data-sequence-id", idx );
      video.setAttribute("data-sequence-clip", [ self.inOuts.ofVideos[ idx ]["in"], self.inOuts.ofVideos[ idx ]["out"] ].join(":") );

      // Append the video to the parent element
      self.parent.appendChild( video );
      

      self.playlist.push( Popcorn("#" + video.id ) );      

    });

    self.inOuts.ofVideos.forEach(function( obj ) {

      var clipDuration = obj["out"] - obj["in"], 
          offs = {
            "in": clipOffset,
            "out": clipOffset + clipDuration
          };

      self.inOuts.ofClips.push( offs );
      
      clipOffset = offs["out"] + 1;
    });

    Popcorn.forEach( this.queue, function( media, idx ) {

      function canPlayThrough( event ) {

        // If this is idx zero, use it as dimension for all
        if ( !idx ) {
          self.dims.width = media.videoWidth;
          self.dims.height = media.videoHeight;
        }
        
        media.currentTime = self.inOuts.ofVideos[ idx ]["in"] - 0.5;

        media.removeEventListener( "canplaythrough", canPlayThrough, false );

        return true;
      }

      // Hook up event listeners for managing special playback 
      media.addEventListener( "canplaythrough", canPlayThrough, false );

      // TODO: consolidate & DRY
      media.addEventListener( "play", function( event ) {

        self.playing = true;

      }, false );

      media.addEventListener( "pause", function( event ) {

        self.playing = false;

      }, false );

      media.addEventListener( "timeupdate", function( event ) {

        var target = event.srcElement || event.target, 
            seqIdx = +(  (target.dataset && target.dataset.sequenceId) || target.getAttribute("data-sequence-id") ), 
            floor = Math.floor( media.currentTime );

        if ( self.times.last !== floor && 
              seqIdx === self.active ) {

          self.times.last = floor;
          
          if ( floor === self.inOuts.ofVideos[ seqIdx ]["out"] ) {

            Popcorn.sequence.cycle.call( self, seqIdx );
          }
        }
      }, false );
    });

    return this;
  };

  Popcorn.sequence.init.prototype = Popcorn.sequence.prototype;

  //  
  Popcorn.sequence.cycle = function( idx ) {

    if ( !this.queue ) {
      Popcorn.error("Popcorn.sequence.cycle is not a public method");
    }

    var // Localize references
    queue = this.queue, 
    ioVideos = this.inOuts.ofVideos, 
    current = queue[ idx ], 
    nextIdx = 0, 
    next, clip;

    
    var // Popcorn instances
    $popnext, 
    $popprev;


    if ( queue[ idx + 1 ] ) {
      nextIdx = idx + 1;
    }

    // Reset queue
    if ( !queue[ idx + 1 ] ) {

      nextIdx = 0;
      this.playlist[ idx ].pause();
      
    } else {
    
      next = queue[ nextIdx ];
      clip = ioVideos[ nextIdx ];

      // Constrain dimentions
      Popcorn.extend( next, {
        width: this.dims.width, 
        height: this.dims.height
      });

      $popnext = this.playlist[ nextIdx ];
      $popprev = this.playlist[ idx ];

      // When not resetting to 0
      current.pause();

      this.active = nextIdx;
      this.times.last = clip["in"] - 1;

      // Play the next video in the sequence
      $popnext.currentTime( clip["in"] );

      $popnext[ nextIdx ? "play" : "pause" ]();

      // Trigger custom cycling event hook
      this.trigger( "cycle", { 

        position: {
          previous: idx, 
          current: nextIdx
        }
        
      });
      
      // Set the previous back to it's beginning time
      // $popprev.currentTime( ioVideos[ idx ].in );

      if ( nextIdx ) {
        // Hide the currently ending video
        current.style.display = "none";
        // Show the next video in the sequence    
        next.style.display = "";    
      }

      this.cycling = false;
    }

    return this;
  };

  var excludes = [ "timeupdate", "play", "pause" ];
  
  // Sequence object prototype
  Popcorn.extend( Popcorn.sequence.prototype, {

    // Returns Popcorn object from sequence at index
    eq: function( idx ) {
      return this.playlist[ idx ];
    }, 
    // Remove a sequence from it's playback display container
    remove: function() {
      this.parent.innerHTML = null;
    },
    // Returns Clip object from sequence at index
    clip: function( idx ) {
      return this.inOuts.ofVideos[ idx ];
    },
    // Returns sum duration for all videos in sequence
    duration: function() {

      var ret = 0, 
          seq = this.inOuts.ofClips, 
          idx = 0;

      for ( ; idx < seq.length; idx++ ) {
        ret += seq[ idx ]["out"] - seq[ idx ]["in"] + 1;
      }

      return ret - 1;
    },

    play: function() {

      this.playlist[ this.active ].play();

      return this;
    },
    // Attach an event to a single point in time
    exec: function ( time, fn ) {

      var index = this.active;
      
      this.inOuts.ofClips.forEach(function( off, idx ) {
        if ( time >= off["in"] && time <= off["out"] ) {
          index = idx;
        }
      });

      //offsetBy = time - self.inOuts.ofVideos[ index ].in;
      
      time += this.inOuts.ofVideos[ index ]["in"] - this.inOuts.ofClips[ index ]["in"];

      // Creating a one second track event with an empty end
      Popcorn.addTrackEvent( this.playlist[ index ], {
        start: time - 1,
        end: time,
        _running: false,
        _natives: {
          start: fn || Popcorn.nop,
          end: Popcorn.nop,
          type: "exec"
        }
      });

      return this;
    },
    // Binds event handlers that fire only when all 
    // videos in sequence have heard the event
    listen: function( type, callback ) {

      var self = this, 
          seq = this.playlist,
          total = seq.length, 
          count = 0, 
          fnName;

      if ( !callback ) {
        callback = Popcorn.nop;
      }

      // Handling for DOM and Media events
      if ( Popcorn.Events.Natives.indexOf( type ) > -1 ) {
        Popcorn.forEach( seq, function( video ) {

          video.listen( type, function( event ) {

            event.active = self;
            
            if ( excludes.indexOf( type ) > -1 ) {

              callback.call( video, event );

            } else {
              if ( ++count === total ) {
                callback.call( video, event );
              }
            }
          });
        });

      } else {

        // If no events registered with this name, create a cache
        if ( !this.events[ type ] ) {
          this.events[ type ] = {};
        }

        // Normalize a callback name key
        fnName = callback.name || Popcorn.guid( "__" + type );

        // Store in event cache
        this.events[ type ][ fnName ] = callback;
      }

      // Return the sequence object
      return this;
    }, 
    unlisten: function( type, name ) {
      // TODO: finish implementation
    },
    trigger: function( type, data ) {
      var self = this;

      // Handling for DOM and Media events
      if ( Popcorn.Events.Natives.indexOf( type ) > -1 ) {

        //  find the active video and trigger api events on that video.
        return;

      } else {

        // Only proceed if there are events of this type
        // currently registered on the sequence
        if ( this.events[ type ] ) {

          Popcorn.forEach( this.events[ type ], function( callback, name ) {
            callback.call( self, { type: type }, data );
          });

        }
      }

      return this;
    }
  });


  Popcorn.forEach( Popcorn.manifest, function( obj, plugin ) {

    // Implement passthrough methods to plugins
    Popcorn.sequence.prototype[ plugin ] = function( options ) {

      // console.log( this, options );
      var videos = {}, assignTo = [], 
      idx, off, inOuts, inIdx, outIdx, keys, clip, clipInOut, clipRange;

      for ( idx = 0; idx < this.inOuts.ofClips.length; idx++  ) {
        // store reference 
        off = this.inOuts.ofClips[ idx ];
        // array to test against
        inOuts = range( off["in"], off["out"] );

        inIdx = inOuts.indexOf( options.start );
        outIdx = inOuts.indexOf( options.end );

        if ( inIdx > -1 ) {
          videos[ idx ] = Popcorn.extend( {}, off, {
            start: inOuts[ inIdx ],
            clipIdx: inIdx
          });
        }

        if ( outIdx > -1 ) {
          videos[ idx ] = Popcorn.extend( {}, off, {
            end: inOuts[ outIdx ], 
            clipIdx: outIdx
          });
        }
      }

      keys = Object.keys( videos ).map(function( val ) {
                return +val;
              });

      assignTo = range( keys[ 0 ], keys[ 1 ] );

      //console.log( "PLUGIN CALL MAPS: ", videos, keys, assignTo );
      for ( idx = 0; idx < assignTo.length; idx++ ) {

        var compile = {},
        play = assignTo[ idx ], 
        vClip = videos[ play ];

        if ( vClip ) {

          // has instructions
          clip = this.inOuts.ofVideos[ play ];
          clipInOut = vClip.clipIdx;
          clipRange = range( clip["in"], clip["out"] );

          if ( vClip.start ) {
            compile.start = clipRange[ clipInOut ];
            compile.end = clipRange[ clipRange.length - 1 ];
          }

          if ( vClip.end ) {
            compile.start = clipRange[ 0 ];
            compile.end = clipRange[ clipInOut ];
          }

          //compile.start += 0.1;
          //compile.end += 0.9;
          
        } else {

          compile.start = this.inOuts.ofVideos[ play ]["in"];
          compile.end = this.inOuts.ofVideos[ play ]["out"];

          //compile.start += 0.1;
          //compile.end += 0.9;
          
        }

        // Handling full clip persistance 
        //if ( compile.start === compile.end ) {
          //compile.start -= 0.1;
          //compile.end += 0.9;
        //}

        // Call the plugin on the appropriate Popcorn object in the playlist
        // Merge original options object & compiled (start/end) object into
        // a new fresh object
        this.playlist[ play ][ plugin ]( 

          Popcorn.extend( {}, options, compile )

        );
        
      }

      // Return the sequence object
      return this;
    };
    
  });
})( this, Popcorn );
// EFFECT: applyclass

(function (Popcorn) {

  /**
   * apply css class to jquery selector
   * selector is relative to plugin target's id
   * so .overlay is actually jQuery( "#target .overlay")
   *
   * @param {Object} options
   *
   * Example:
     var p = Popcorn('#video')
        .footnote({
          start: 5, // seconds
          end: 15, // seconds
          text: 'This video made exclusively for drumbeat.org',
          target: 'footnotediv',
          effect: 'applyclass',
          applyclass: 'selector: class'
        })
   *
   */

  var toggleClass = function( event, options ) {

    var idx = 0, len = 0, elements;

    Popcorn.forEach( options.classes, function( key, val ) {

      elements = [];

      if ( key === "parent" ) {

        elements[ 0 ] = document.querySelectorAll("#" + options.target )[ 0 ].parentNode;
      } else {

        elements = document.querySelectorAll("#" + options.target + " " + key );
      }

      for ( idx = 0, len = elements.length; idx < len; idx++ ) {

        elements[ idx ].classList.toggle( val );
      }
    });
  };

  Popcorn.compose( "applyclass", {

    manifest: {
      about: {
        name: "Popcorn applyclass Effect",
        version: "0.1",
        author: "@scottdowne",
        website: "scottdowne.wordpress.com"
      },
      options: {}
    },
    _setup: function( options ) {

      options.classes = {};
      options.applyclass = options.applyclass || "";

      var classes = options.applyclass.replace( /\s/g, "" ).split( "," ),
          item = [],
          idx = 0, len = classes.length;

      for ( ; idx < len; idx++ ) {

        item = classes[ idx ].split( ":" );

        if ( item[ 0 ] ) {
          options.classes[ item[ 0 ] ] = item[ 1 ] || "";
        }
      }
    },
    start: toggleClass,
    end: toggleClass
  });
})( Popcorn );

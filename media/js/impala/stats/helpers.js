// Web Worker Pool
// size is the max number of arguments
function WorkerPool(size) {
    var workers = 0,
        jobs    = [];

    // url: the url of the worker's js
    // msg: the initial message to pass to the worker
    // cb : the callback to recieve messages from postMessage.
    //      return true from cb to dismiss the worker and advance the queue.
    // ctx: the context for cb.apply
    this.queueJob = function(url, msg, cb, ctx) {
        var job = {
            "url": url,
            "msg": msg,
            "cb" : cb,
            "ctx": ctx
        };
        jobs.push(job);
        if (workers < size) nextJob();
    };

    function nextJob() {
        if (jobs.length) {
            (function() {
                var job    = jobs.shift(),
                    worker = new Worker(job.url);
                workers++;
                worker.addEventListener('message', function(e) {
                    if (job.cb.call(job.ctx, e.data, worker)) {
                        worker.terminate();
                        delete worker;
                        workers--;
                        nextJob();
                    };
                }, false);
                worker.postMessage(job.msg);
            })();
        }
    }
}

// Simple Asynchronous Cache
// miss: a function that computes the value for the given key.
//       Takes two parameters:
//       * key: the key passed to AsyncCache.get()
//       * set: a callback that sets the value for key
// hash: an optional function that generates a hash string for a given key.
//       Takes one parameter:
//       * key
function AsyncCache(miss, hash) {
    var cache = {},
        self  = this;

    hash = hash || function(key) {
        return key.toString();
    };

    // key: the key to lookup in the cache
    // cb : the method to call with the value
    //      Takes one parameter:
    //      val: the value in the cache for key
    // ctx: context for cb.call
    this.get = function(key, cb, ctx) {
        var k = hash(key);
        if (k in cache) {
            cb.call(ctx, cache[k]);
        } else {
            miss.call(ctx, key, function(val) {
                self.set(key, val);
                self.get(key, cb, ctx);
            });
        }
    };

    // sets value for key in cache
    this.set = function(key, val) {
        cache[hash(key)] = val;
    };
}

function hashObj(o) {
    var hash = [];
    for (var i in o) {
        if (o.hasOwnProperty(i)) {
            hash.push(o[i].toString());
        }
    }
    return hash.join('_');
}

/* cfg takes:
 * start: the initial value
 * end: the (non-inclusive) max value
 * step: value to iterate by
 * chunk-size: how many iterations before setTimeout
 * inner: function to perform each iteration
 * callback: function to perform when finished
 * ctx: context from which to run all functions
 */
function chunkfor(cfg) {
    var position = cfg.start;

    function nextchunk() {
        if (position < cfg.end) {

            for (var iterator = position;
                 iterator < position+(cfg.chunk_size*cfg.step) && iterator < cfg.end;
                 iterator += cfg.step) {

                cfg.inner.call(cfg.ctx, iterator);
            }

            position += cfg.chunk_size * cfg.step;

            setTimeout( function () {
                nextchunk.call(this);
            }, 0);

        } else {
            cfg.callback.call(cfg.ctx);
        }
    }
    nextchunk();
}

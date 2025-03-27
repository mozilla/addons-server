import 'jquery.cookie';

import $ from 'jquery';

import { capabilities } from '../zamboni/capabilities';

/**
 * storage.js - Simple namespaced browser storage.
 *
 * Creates a window.Storage function that gives you an easy API to access
 * localStorage, with fallback to cookie storage. Each Storage object is
 * namespaced:
 *   let foo = Storage('foo'),
 *       bar = Storage('bar');
 *   foo.set('test', 'A');
 *   bar.set('test', 'B');
 *   foo.get('test');    // 'A'
 *   bar.remove('test');
 *   foo.get('test');    // still 'A'
 *
 * Requires jQuery and jQuery Cookie plugin.
 */
export function Storage(namespace) {
  let cookieStorage = {
    expires: 30,
    getItem: function (key) {
      return $.cookie(key);
    },
    setItem: function (key, value) {
      return $.cookie(key, value, { path: '/', expires: this.expires });
    },
    removeItem: function (key) {
      return $.cookie(key, null);
    },
  };
  let engine = capabilities.localStorage ? localStorage : cookieStorage;
  namespace = namespace ? namespace + '-' : '';
  return {
    get: function (key) {
      return engine.getItem(namespace + key);
    },
    set: function (key, value) {
      return engine.setItem(namespace + key, value);
    },
    remove: function (key) {
      return engine.removeItem(namespace + key);
    },
  };
}

export function SessionStorage(namespace) {
  let cookieStorage = {
    getItem: function (key) {
      return $.cookie(key);
    },
    setItem: function (key, value) {
      return $.cookie(key, value, { path: '/' });
    },
    removeItem: function (key) {
      return $.cookie(key, null);
    },
  };
  let engine = capabilities.localStorage ? sessionStorage : cookieStorage;
  namespace = namespace ? namespace + '-' : '';
  return {
    get: function (key) {
      return engine.getItem(namespace + key);
    },
    set: function (key, value) {
      return engine.setItem(namespace + key, value);
    },
    remove: function (key) {
      return engine.removeItem(namespace + key);
    },
  };
}

import { defineConfig } from 'vite';
import { resolve, join } from 'path';

// TODO: vite is clearing the cwd on every build. that is wrong and annoying.
// also it's having trouble matching the manifest.json here and the one in the settings_base.py file.
export default defineConfig((_) => {

  const INPUT_DIR = './static';
  const OUTPUT_DIR = './static-build';

  return {
    root: resolve(INPUT_DIR),
    base: '/static/',
    server: {
      host: true,
      port: 5173,
    },
    build: {
      manifest: 'manifest.json',
      emptyOutDir: false,
      copyPublicDir: false,
      outDir: resolve(OUTPUT_DIR),
      rollupOptions: {
        input: {
          'common': join(INPUT_DIR, 'js/common/index.js'),
          'blue_js': join(INPUT_DIR, 'js/blue.js'),
        },
      },
    },
  };
});

/*
{"Timestamp": 1734876156142280960, "Type": "django.request", "Logger": "http_app_addons", "Hostname": "4bd613fee1b8", "EnvVersion": "2.0", "Severity": 3, "Pid": 35, "Fields": {"status_code": 500, "request": "<WSGIRequest: GET '/en-US/developers/'>", "uid": "", "remoteAddressChain": "", "msg": "Internal Server Error: /en-US/developers/", "error": "DjangoViteAssetNotFoundError('Cannot find js/blue.js for app=default in Vite manifest at /data/olympia/src/olympia/../../static-build/manifest.json')", "traceback": "Uncaught exception:\n  File \"/deps/lib/python3.12/site-packages/django/core/handlers/exception.py\", line 55, in inner\n    response = get_response(request)\n               ^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django/core/handlers/base.py\", line 220, in _get_response\n    response = response.render()\n               ^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/sentry_sdk/integrations/django/views.py\", line 38, in sentry_patched_render\n    return old_render(self)\n           ^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django/template/response.py\", line 114, in render\n    self.content = self.rendered_content\n                   ^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/sentry_sdk/integrations/django/templates.py\", line 75, in rendered_content\n    return real_rendered_content.fget(self)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django/template/response.py\", line 92, in rendered_content\n    return template.render(context, self._request)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django_jinja/backend.py\", line 59, in render\n    return mark_safe(self._process_template(self.template.render, context, request))\n                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django_jinja/backend.py\", line 105, in _process_template\n    return handler(context)\n           ^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/jinja2/environment.py\", line 1304, in render\n    self.environment.handle_exception()\n  File \"/deps/lib/python3.12/site-packages/jinja2/environment.py\", line 939, in handle_exception\n    raise rewrite_traceback_stack(source=source)\n  File \"/data/olympia/src/olympia/devhub/templates/devhub/index.html\", line 8, in top-level template code\n    {{ vite_asset('js/blue.js') }}\n    ^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django/utils/safestring.py\", line 53, in wrapper\n    return safety_marker(func(*args, **kwargs))\n                         ^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django_vite/templatetags/django_vite.py\", line 67, in vite_asset\n    return DjangoViteAssetLoader.instance().generate_vite_asset(path, app, **kwargs)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django_vite/core/asset_loader.py\", line 802, in generate_vite_asset\n    return app_client.generate_vite_asset(path, **kwargs)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django_vite/core/asset_loader.py\", line 312, in generate_vite_asset\n    manifest_entry = self.manifest.get(path)\n                     ^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/deps/lib/python3.12/site-packages/django_vite/core/asset_loader.py\", line 201, in get\n    raise DjangoViteAssetNotFoundError(\n<class 'django_vite.core.exceptions.DjangoViteAssetNotFoundError'>\nDjangoViteAssetNotFoundError('Cannot find js/blue.js for app=default in Vite manifest at /data/olympia/src/olympia/../../static-build/manifest.json')\n"}, "severity": 500}
*/

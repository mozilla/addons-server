# Building Docs

To simply build the docs:

```
docker compose run web make docs
```

If you're working on the docs, use _make loop_ to keep your built pages
up-to-date:

```
make shell
cd docs
make loop
```

Open _docs/_build/html/index.html_ in a web browser.

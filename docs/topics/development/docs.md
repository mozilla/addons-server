# Building Docs

To simply build the docs:

```bash
docker compose run web make docs
```

If you're working on the docs, use `make loop` to keep your built pages
up-to-date:

```bash
make shell
cd docs
make loop
```

Open `docs/_build/html/index.html` in a web browser.

(amo-search-explainer)=

# How does search on AMO work?

## High-level overview

AMO add-ons are indexed in our Elasticsearch cluster. For each search query
someone makes on AMO, we run a custom set of full-text queries against that
cluster.

Our autocomplete (that you can see when starting to type a few characters in
the search field) uses the exact same implementation as a regular search
underneath.

### Rules

For each search query, we apply a number of rules that attempt to find the
search terms in each add-on name, summary and description. Each rule generates
a score that depends on:

> - The frequency of the terms in the field we're looking at
> - The importance of each term in the overall index (the more common the term is across all add-ons, the less it impacts the score)
> - The length of the field (shorter fields give a higher score as the search term is considered more relevant if they make up a larger part of the field)

Each rule is also given a specific boost affecting its score, making matches
against the add-on name more important and matches against the summary or
description.

Add-on names receive special treatment: Partial or misspelled matches are
accepted to some extent while exact matches receive a significantly higher
score.

### Scoring

Each score for each rule is combined into a final score which we modify
depending on the add-on popularity on a logarithm scale. "Recommended" and
"By Firefox" add-ons get an additional, significant boost to their score.

Finally, results are returned according to their score in descending order.

## Technical overview

We store two kinds of data in the _addons_ index: indexed fields that are used for search purposes, and non-indexed fields that are meant to be returned (often as-is with no transformations) by the search API (allowing us to return search results data without hitting the database). The latter is not relevant to this document.

Our search can be reached either via the API through {ref}`/api/v5/addons/search/ <addon-search>` or {ref}`/api/v5/addons/autocomplete/ <addon-autocomplete>` which are used by our frontend.

### Indexing

The key fields we search against are `name`, `summary` and `description`. Because all can be translated, we index them multiple times:

> - Once with the translation in the default locale of the add-on, under `{field}`, analyzed with just the `snowball` analyzer for `description` and `summary`, and a custom analyzer for `name` that applies the following filters: `standard`, `word_delimiter` (a custom version with `preserve_original` set to `true`), `lowercase`, `stop`, and `dictionary_decompounder` (with a specific word list) and `unique`.
> - Once for every translation that exists for that field, using Elasticsearch language-specific analyzer if supported, under `{field}_l10n_{analyzer}`.

**In addition, for the name, we also have:**

- For all fields described above also contains a subfield called `raw` that holds a non-analyzed variant for exact matches in the corresponding language (stored as a `keyword`, with a `lowercase` normalizer).
- A `name.trigram` variant for the field in the default language, which is using a custom analyzer that depends on a `ngram` tokenizer (with `min_gram=3`, `max_gram=3` and `token_chars=["letter", "digit"]`).

### Flow of a search query through AMO

Let's assume we search on addons-frontend (not legacy) the search query hits the API and gets handled by `AddonSearchView`, which directly queries ElasticSearch and doesn't involve the database at all.

There are a few filters that are described in the {ref}`/api/v5/addons/search/ docs <addon-search>` but most of them are not very relevant for text search queries. Examples are filters by guid, platform, category, add-on type or appversion (application version compatibility). Those filters are applied using a `filter` clause and shouldn't affect scoring.

Much more relevant for text searches (and this is primarily used when you use the search on the frontend) is `SearchQueryFilter`.

It composes various rules to define a more or less usable ranking:

#### Primary rules

These are the ones using the strongest boosts, so they are only applied to the add-on name.

**Applied rules** (merged via `should`):

1. A `dis_max` query with `term` matches on `name_l10n_{analyzer}.raw` and `name.raw` if the language of the request matches a known language-specific analyzer, or just a `term` query on `name.raw` (`boost=100.0`) otherwise - our attempt to implement exact matches
2. If we have a matching language-specific analyzer, we add a `match` query to `name_l10n_{analyzer}` (`boost=5.0`, `operator=and`)
3. A `phrase` match on `name` that allows swapped terms (`boost=8.0`, `slop=1`)
4. A `match` on `name`, using the standard text analyzer (`boost=6.0`, `analyzer=standard`, `operator=and`)
5. A `prefix` match on `name` (`boost=3.0`)
6. If a query is \< 20 characters long, a `dis_max` query (`boost=4.0`) composed of a fuzzy match on `name` (`boost=4.0`, `prefix_length=2`, `fuzziness=AUTO`, `minimum_should_match=2<2 3<-25%`) and a `match` query on `name.trigram`, with a `minimum_should_match=66%` to avoid noise

#### Secondary rules

These are the ones using the weakest boosts, they are applied to fields containing more text like description, summary and tags.

**Applied rules** (merged via `should`):

1. Look for matches inside the summary (`boost=3.0`, `operator=and`)
2. Look for matches inside the description (`boost=2.0`, `operator=and`)

If the language of the request matches a known language-specific analyzer, those are made using a `multi_match` query using `summary` or `description` and the corresponding `{field}_l10n_{analyzer}`, similar to how exact name matches are performed above, in order to support potential translations.

#### Scoring

We combine scores through a `function_score` query that multiplies the score by several factors:

> - A first multiplier is always applied through the `field_value_factor` function on `average_daily_users` with a `log2p` modifier
> - An additional `4.0` weight is applied if the add-on is public & non-experimental.
> - Finally, `5.0` weight is applied to By Firefox and Recommended add-ons.

On top of the two sets of rules above, a `rescore` query is applied with a `window_size` of `10`. In production, we have 5 shards, so that should re-adjust the score of the top 50 results returned only. The rules used for rescoring are the same used in the secondary rules above, with just one difference: it's using `match_phrase` instead of `match`, with a slop of `10`.

#### General query flow

> 1. Fetch current translation
> 2. Fetch locale specific analyzer ([List of analyzers](https://github.com/mozilla/addons-server/blob/f099b20fa0f27989009082c1f58da0f1d0a341a3/src/olympia/constants/search.py#L13-L52))
> 3. Apply primary and secondary *should* rules
> 4. Determine the score
> 5. Rescore the top 10 results per shard

#### See also

> - [addons-server search ranking tests](https://github.com/mozilla/addons-server/blob/master/src/olympia/search/tests/test_search_ranking.py)
> - [Elasticsearch relevancy algorithm](https://www.elastic.co/blog/practical-bm25-part-2-the-bm25-algorithm-and-its-variables)

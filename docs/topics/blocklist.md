# AMO Blocklist

(blocklist-doc)=

This is a high-level overview of the addons-server implementation of the addons blocklist.

## Full-Stack Overview

(blocklist-doc-overview)=

Firefox determines which add-ons are unsafe to allow to continue to be enabled by checking a blocklist:

- With v1 and v2 blocklist this is literally a list of addon guids, plus other metadata, that should be blocked from executing (v1 is XML format, v2 is JSON format);
- With v3 blocklist this is a bloomfilter that is queried - if the addon guid and xpi version is present then it's in the blocklist so should be blocked by Firefox. The v3 system supports both **Hard Blocks** (add-on is completely disabled) and **Soft Blocks** (add-on is disabled but user can re-enable).

**The blocklists are all served via Firefox Remote Settings (the current implementation is Kinto):**

<https://github.com/mozilla-extensions/remote-settings-devtools>

- the v3 blocklist bloomfilter files are attachments in the records of <https://firefox.settings.services.mozilla.com/v1/buckets/blocklists/collections/addons-bloomfilters/records>
- the v2 blocklist is the full output of <https://firefox.settings.services.mozilla.com/v1/buckets/blocklists/collections/addons/records>
- the v1 blocklist is a (server-side) wrapper around the v2 blocklist that rewrites the JSON into XML

```{admonition} legacy
v2/v1 are referred to as "legacy" blocklist in these docs.
```

AMO holds the addon blocklist records (`Block`) defining blocks for the **v3 system** (including hard/soft type) and generates the v3 bloomfilters and stashes as needed, which are then uploaded to the `addons-bloomfilters` collection on Remote Settings. The `Block` records are managed via the admin tools on addons-server.

```{admonition} legacy
If any changes are needed to the contents of the legacy blocklist it must be made via the Firefox Remote Settings web admin tool - there is no longer any way to import or export changes between the legacy blocklist and the v3 blocklist.
```

## Admin Tool

(blocklist-doc-admin)=

_Block_ records aren't created and changed directly via the admin tool; instead _BlockSubmission_ records are created that hold details of the submission of (potentially many) blocks that will be created, updated, or deleted.
If the add-ons that the Block affects are used by a significant number of users (see _DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD_ setting - currently 100k) then the BlockSubmission must be signed off (approved) by another admin user first.

An admin user can select a block type, addon and a number of versions to block, or all versions.

Once the submission is approved - or immediately after saving if the average daily user counts are under the threshold - a task is started to asynchronously create, update, or delete, Block records.

A block can be hardened or softened via the admin tool which results in a new BlockSubmission record.

Ultimately, Each "block" in the blocklist is a unique pair of the addon guid and the version string allowing for fine grained control over which versions of an add-on are blocked or soft blocked or not blocked.

## Bloomfilter Generation

(blocklist-doc-bloomfilter)=

Generating a bloomfilter for the **v3 blocklist** can be quite slow, so a new one is only generated every 6 hours via a cron job (`upload_mlbf_to_remote_settings`) handling **both hard and soft blocks**. The cron job checks if an update is needed by comparing the current state (hard-blocked, soft-blocked, not-blocked items) against the previously generated filter/stash and the base filter; it skips generation if no filter or stash upload is deemed necessary based on this comparison (see {ref}`Process <blocklist-doc-process>` below).

An ad-hoc bloomfilter can be created with the _export_blocklist_ command but it isn't considered for the cron job (or {ref}`stashing <blocklist-doc-stashing>`)

### Bloomfilter records

(blocklist-doc-bloomfilter-records)=

For the **v3 blocklist**, **two** base filter records are created on Remote Settings in the `addons-bloomfilters` collection (one for hard blocks, one for soft blocks, distinguished by `attachment_type`) and the filter file (`filter.bin`) uploaded as an attachment to each. The _generation_time_ property represents the point in time when all previous addon guid + versions and blocks were used to generate the bloomfilter.
An add-on version/file from before this time will definitely be accounted for in the bloomfilter so we can reliably assert if it's blocked or not.
An add-on version/file from after this time can't be reliably asserted - there may be false positives or false negatives.

See <https://github.com/mozilla/addons-server/issues/13695>.

#### Bloomfilter record example

```json
{
      "schema": 1740062666739,
      "attachment": {
        "hash": "37ba24caec49afe6c97c424623e226e31ad052286ffa66d794eb82497dabc279",
        "size": 28561,
        "filename": "filter.bin",
        "location": "staging/addons-bloomfilters/1234567890.bin",
        "mimetype": "application/octet-stream"
      },
      "key_format": "{guid}:{version}",
      "attachment_type": "bloomfilter-base",
      "generation_time": 1587990908999,
      "id": "851e162f-1227-486f-9abe-19bfdcb9fd12",
      "last_modified": 1740063264110
    }
```

_(A similar record exists with `attachment_type: "softblocks-bloomfilter-base"` for the soft block base filter)_

### Stashing

(blocklist-doc-stashing)=

Because the bloomfilter files can be quite large, for the **v3 blocklist**, "stash" files are also generated when changes are small compared to the base filters. These represent the changes (for **both hard and soft blocks**) since the _previous_ bloomfilter generation and can be used by Firefox v3 clients instead of downloading a full new filter, saving on bandwidth.

Multiple stashes can be applied by Firefox (in chronological order using `stash_time`) to match the state of an up-to-date bloomfilter.

The v3 stash data includes:

- `blocked`: New hard blocks since the previous generation.
- `unblocked`: Items no longer hard or soft blocked since the previous generation.
- `soft_blocked`: New soft blocks since the previous generation.

**Important:** When new base filters are uploaded (due to significant changes compared to the _base_, a missing base, or `force_base` being used), _all existing stash records are deleted_ from the Remote Settings collection. Clients fetching updates after this point will need to download the new base filters, and stashing effectively restarts for v3 clients.

Stash data is stored directly within the Remote Settings record JSON, not as an attachment.

#### Stash record example (v3)

```json
{
  "id": "example-stash-record-67890",
  "last_modified": 1678887000000,
  "key_format": "{guid}:{version}",
  "stash_time": 1678887000123, // Example Timestamp (milliseconds)
  "stash": {
    "blocked": [
      "{6f6b1eaa-bb69-4cdb-a24f-1014493d4290}:10.48",
      "kittens@pioneer.mozilla.com:1.2",
      "kittens@pioneer.mozilla.com:1.1",
      "{b01e0601-eddc-4306-886b-8a4fb5c38a1e}:1",
      "{232f11df-20ca-49d4-94eb-e3e63d7ae773}:1.1.2",
      "kittens@pioneer.mozilla.com:1.3",
    ],
    "unblocked": [
      "{896aff0b-d86e-4dd5-9097-5869579b4c28}:1.2",
      "{95ffc924-6ea7-4dfb-8f7b-1dd44f2159d1}:1.22.2"
    ]
  }
}
```

The blocked/soft_blocked items represent new versions that should be blocked or soft blocked in addition to any matches in the bloomfilter; the unblocked items represent versions that shouldn't be blocked or soft blocked (even though they would match the bloomfilter).  _stash_time_ is a timestamp that can be relied on to order the stashes.

If a version transitions from one block type to another in a stash, from a logical standpoint two operations are happening:

- It is ``unblocked`` from the previous block type.
- It is ``blocked`` or ``soft_blocked`` for the new block type.

We explicitly remove it from the "unblocked" list in this case to prevent double counting the same key in a single stash record. Firefox will use the first matching stash state, but this reduces the size of the stash and guarantees only one possible state per key at a given time.

### addons-bloomfilter collection

(blocklist-doc-collection)=

For the **v3 blocklist**, the `addons-bloomfilters` collection on Remote Settings will contain:

- Two attachment records, each with an `attachment_type` "bloomfilter-base" or "softblocks-bloomfilter-base" which are the base bloomfilters to compare the stash files to.
- Zero or more stash records, each with stash data directly in the data property.

The client-side algorithm for **v3 blocklist consumers** would be to:

- Get the entire collection from Remote Settings (the implementation supports diffing so only new records would be downloaded).
- Download the **two** base bloomfilter attachments (`bloomfilter-base` and `softblocks-bloomfilter-base`) if it hasn't already been downloaded.
- Gather the stash records and then sort them by "newest first".
- Look up the installed addons by `guid:version`, stopping at the first matching blocks state, either blocked, softblocked or unblocked (**in this order**). Assuming a block was found in the stashes, if the stash_time is older than the MLBF generation_time, Firefox looks up the key in the MLBF. The hard BF is checked first, then the soft BF.

#### Stashing support disabled in Firefox

If stashing support is disabled in a Firefox version the stash records can be ignored and the **two latest base filters** (`bloomfilter-base` and `softblocks-bloomfilter-base`) will be used instead.  (Records with a bloomfilter attachment always have a _generation_time_ field).  Firefox would just download the latest attachment and use that as it's bloomfilter.

### Process

(blocklist-doc-process)=

**The server process performed by the cron job (`upload_mlbf_to_remote_settings`) for the v3 blocklist is:**

- If the `blocklist_mlbf_submit` waffle switch is enabled (or bypassed), proceed. Otherwise, stop.
- Generate the current lists of hard-blocked, soft-blocked, and not-blocked `{guid}:{version}` items based on signed add-ons and `Block` records.
- Load the state (item lists) from the _previous_ successful generation and the _current base filters_ from storage/config.
- Compare current state to previous/base states to decide action:
  - **Filter Upload?** If changes for _either_ hard or soft blocks vs. their respective _base filter_ exceed a threshold (default 5000), or `force_base` is true, or a base filter is missing, flag for a filter upload.
  - **Stash Upload?** If _not_ uploading filters, but there are _any_ changes for _either_ hard or soft blocks vs. the _previous generation_, flag for a stash upload.
  - **Skip?** If neither flag is set, stop the process.
- Generate required files based on the decision:
  - Filter Upload: Generate _two_ separate bloomfilter files (`filter-blocked`, `filter-soft_blocked`).
  - Stash Upload: Generate _one_ unified `stash.json` file with diffs vs. the previous generation.
- Trigger the asynchronous `upload_filter` task, passing the generation timestamp and required actions (e.g., `UPLOAD_BLOCKED_FILTER`, `UPLOAD_SOFT_BLOCKED_FILTER`, `CLEAR_STASH`, `UPLOAD_STASH`).
- The `upload_filter` task then executes:
  - Connects to the `addons-bloomfilters` collection on Remote Settings.
  - If uploading filters: Uploads the two new filter attachments (hard=`bloomfilter-base`, soft=`softblocks-bloomfilter-base`), deletes any previous filter attachments of the same types, and **deletes all existing stash records**.
  - If uploading a stash: Uploads the new stash JSON data in a record.
  - Commits the Remote Settings changes.
  - Updates AMO config keys with the new timestamp(s).
  - Triggers cleanup of old local files.

## Legacy Blocklist

(blocklist-doc-legacy)=

To populate the blocklist on AMO the legacy blocklist on Remote Settings was imported; all guids that matched addons on AMO (and that had at least one webextension version) were added; any guids that were regular expressions were "expanded" to individual records for each addon present in the AMO database.

Support for importing the legacy blocklist into AMO, and exporting changes from AMO into the legacy blocklist, has now been removed; it is no longer possible to propagate changes made to the v2 blocklist via the remote-settings web admin tool to the v3 blocklist held on AMO, or visa versa.

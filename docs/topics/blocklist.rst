#############
AMO Blocklist
#############

.. _blocklist-doc:

This is a high-level overview of the addons-server implementation of the addons blocklist.


===================
Full-Stack Overview
===================

.. _blocklist-doc-overview:

Firefox determines which add-ons are unsafe to allow to continue to be enabled by checking a blocklist.
With v1 and v2 blocklist this is literally a list of addon guids, plus other metadata, that should be blocked from executing (v1 is XML format, v2 is JSON format);
with v3 blocklist this is a bloomfilter that is queried - if the addon guid and xpi version is present then it's in the blocklist so should be blocked by Firefox.

The blocklists are all served via Firefox Remote Settings (the current implementation is Kinto):
 - the v3 blocklist bloomfilter files are attachments in the records of https://firefox.settings.services.mozilla.com/v1/buckets/blocklists/collections/addons-bloomfilters/records
 - the v2 blocklist is the full output of https://firefox.settings.services.mozilla.com/v1/buckets/blocklists/collections/addons/records
 - the v1 blocklist is a (server-side) wrapper around the v2 blocklist that rewrites the JSON into XML

.. note::
    v2/v1 are referred to as "legacy" blocklist in these docs.

AMO holds the addon blocklist records and generates the bloomfilters as needed, which are then uploaded to Remote Settings.
The records are managed via the admin tools on addons-server, where updates can also be made to the legacy blocklists (:ref:`in most cases <blocklist-doc-regex>`).


==========
Admin Tool
==========

.. _blocklist-doc-admin:

`Block` records aren't created and changed directly via the admin tool; instead `BlockSubmission` records are created that hold details of the submission of (potentially many) blocks that will be created, updated, or deleted.
If the add-ons that the Block affects are used by a significant number of users (see `DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD` setting - currently 100k) then the BlockSubmission must be signed off (approved) by another admin user first.

Once the submission is approved - or immediately after saving if the average daily user counts are under the threshold - a task is started to asynchronously create, update, or delete, Block records.
If the Block records are marked as legacy then they will be uploaded to the legacy blocklist collection too in this task.


======================
Bloomfilter Generation
======================

.. _blocklist-doc-bloomfilter:

Generating a bloomfilter can be quite slow, so a new one is only generated every 6 hours - or less frequently if no Block records have been changed/added/deleted in that time - via a cron job.

An ad-hoc bloomfilter can be created with the `export_blocklist` command but it isn't considered for the cron job (or :ref:`stashing <blocklist-doc-stashing>`)

-------------------
Bloomfilter records
-------------------

.. _blocklist-doc-bloomfilter-records:

A record is created on Remote Settings for each bloomfilter and the filter uploaded as an attachment.  The `generation_time` property represents the point in time when all previous addon guid + versions and blocks were used to generate the bloomfilter.
An add-on version/file from before this time will definitely be accounted for in the bloomfilter so we can reliably assert if it's blocked or not.
An add-on version/file from after this time can't be reliably asserted - there may be false positives or false negatives.

See https://github.com/mozilla/addons-server/issues/13695 and https://github.com/mozilla/addons-server/blob/master/src/olympia/blocklist/cron.py


Bloomfilter record example
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: json

    {
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
    }


--------
Stashing
--------

.. _blocklist-doc-stashing:

Because the bloomfilter files can be quite large "stash" files are also generated, which represent the changes since the previous bloomfilter generation and can be used by Firefox instead to save on bandwidth.

Multiple stashes can be applied by Firefox (in chronological order) to match the state of an up-to-date bloomfilter.


Stash record example
^^^^^^^^^^^^^^^^^^^^

.. code-block:: json

    {
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
      },
      "key_format": "{guid}:{version}",
      "stash_time": 1587990908999,
    }

The blocked items represent new versions that should be blocked in addition to any matches in the bloomfilter; the unblocked items represent versions that shouldn't be blocked (even though they would match the bloomfilter).  `stash_time` is a timestamp that can be relied on to order the stashes.


-----------------------------
addons-bloomfilter collection
-----------------------------

.. _blocklist-doc-collection:

The collection on Remote Settings at any given point will consist of a single record with `"attachment-type": "bloomfilter-base"`, which is the base bloomfilter to compare the stash files to, and potentially subsequent records which either contain an attachment with `"attachment-type": "bloomfilter-full"`, or stash data directly in the data property.  The client-side algorithm would be to:

* Get the entire collection from Remote Settings (the implementation supports diffing so only new records would be downloaded).
* Download the base bloomfilter attachment (`"attachment-type": "bloomfilter-base"`) if it hasn't already been downloaded.
* Gather the stash records and consolidate them, taking into account timestamps so later stashes override earlier stashes.


Stashing support disabled in Firefox
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If stashing support is disabled in a Firefox version the stash records can be ignored and all bloomfilters considered instead.  (Records with a bloomfilter attachment always have a `generation_time` field).  Firefox would just download the latest attachment and use that as it's bloomfilter.


-------
Process
-------

.. _blocklist-doc-process:

The server process is:
 * If the `blocklist_mlbf_submit` waffle switch is enabled, check if there have been any changes to the blocklist since the previous execution of the cron job - if not return without any action.  (not blocked guids)
 * Produce a list of all "guid:version" combinations of all signed webextension addons/versions in the database.  (blocked guids)
 * Produce a list of "guid:version" combinations that the Block records cover.  Blocks have a minimum and maximum version range - 0 being the minimum, and * meaning infinity, so 0 - * would be all versions of an add-on.
 * Create and verify a bloomfilter with these two lists (we use https://github.com/mozilla/filter-cascade/); save the filter file and the two lists (as JSON)

 * Compare list of blocked guids from this execution to the base bloomfilter file. If there have been few changes then write those changes to a stash JSON blob

   #. Upload the stash as JSON data in record
   #. Upload the filter as an attachment to a separate record with the type `bloomfilter-full`
 * If there have been many changes then:

   #. clear the collection on Remote Settings
   #. Upload the filter as an attachment to a separate record with the type `bloomfilter-base`


================
Legacy Blocklist
================

.. _blocklist-doc-legacy:

To populate the blocklist on AMO the legacy blocklist on Remote Settings was imported; all guids that matched addons on AMO (and that had at least one webextension version) were added; any guids that were :ref:`regular expressions<blocklist-doc-regex>` were "expanded" to individual records for each addon present in the AMO database.

If the `include_in_legacy` is selected in AMO's admin tool the block will also be saved to the legacy blocklist.  Edits to Blocks will propagate to the legacy blocklist too (apart from :ref:`regular expression based blocks<blocklist-doc-regex>`). An existing Block can be edited to deselect `include_in_legacy` which would delete it from the legacy blocklist; or edited to add select which would add it to the legacy blocklist.


------------------
Regex-based Blocks
------------------

.. _blocklist-doc-regex:

The legacy blocklist records can contain regular expressions in the `guid` field, which are interpreted by Firefox to match addon guids.

AMO's blocklist implementation, by design, does not generate or change regular expressions in legacy blocklist records.
So Blocks imported from a regular expression in the legacy blocklist can be viewed and updated on AMO, and are included in the v3 bloomfilter blocklist, but changes to those records cannot be propagated back to the legacy blocklist because the regular expression would need to be amended.

A warning message is displayed and the user must manually make the changes to the legacy blocklist via the kinto admin tool.

.. note::
    Blocks with a `kinto-id` property starting with `*` were imported from regular expression based Remote Setting records.

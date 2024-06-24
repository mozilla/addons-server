=============
Abuse Reports
=============

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.

The following API endpoint covers abuse reporting

---------------------------------
Submitting an add-on abuse report
---------------------------------

.. _`addonabusereport-create`:

The following API endpoint allows an abuse report to be submitted for an Add-on,
either listed on https://addons.mozilla.org or not.
Authentication is not required, but is recommended so reports can be responded
to if necessary.

.. warning::

    Except for the ``message``, all strings have a maximum length of 255 characters
    and should be truncated by the client where necessary.

.. warning::

    For ``addon_install_method`` and ``addon_install_source`` specifically,
    if an unsupported value is sent, it will be silently changed to ``other``
    instead of raising a 400 error.

.. http:post:: /api/v5/abuse/report/addon/

    :<json string|int addon: The id, slug, or guid of the add-on to report for abuse (required).
    :<json string message: The body/content of the abuse report (required).
    :<json string|null report_entry_point: The report entry point. The accepted values are documented in the :ref:`table below <abuse-report_entry_point-parameter>`.
    :<json string|null addon_install_method: The add-on install method. The accepted values are documented in the :ref:`table below <abuse-addon_install_method-parameter>`.
    :<json string|null addon_install_origin: The add-on install origin.
    :<json string|null addon_install_source: The add-on install source. The accepted values are documented in the :ref:`table below <abuse-addon_install_source-parameter>`.
    :<json string|null addon_install_source_url: The add-on install source URL.
    :<json string|null addon_name: The add-on name in the locale used by the client.
    :<json string|null addon_signature: The add-on signature state. The accepted values are documented in the :ref:`table below <abuse-addon_signature-parameter>`.
    :<json string|null addon_summary: The add-on summary in the locale used by the client.
    :<json string|null addon_version: The add-on version string.
    :<json string|null app: The :ref:`application <addon-detail-application>` used by the client. Can be either ``firefox`` or ``android``.
    :<json string|null appversion: The application version used by the client.
    :<json string|null lang: The language code of the locale used by the client for the application.
    :<json string|null location: Where the content being reported is located - on AMO or inside the add-on. The accepted values are documented in the :ref:`table below <abuse-location-parameter>`.
    :<json string|null client_id: The client's hashed telemetry ID.
    :<json string|null install_date: The add-on install date.
    :<json string|null operating_system: The client's operating system.
    :<json string|null operating_system_version: The client's operating system version.
    :<json string|null reason: The reason for the report. The accepted values are documented in the :ref:`table below <abuse-addon-reason-parameter>`.
    :<json string|null reporter_name: The provided name of the reporter, if not authenticated.
    :<json string|null reporter_email: The provided email of the reporter, if not authenticated.
    :<json string|null illegal_category: The type of illegal content - only required when the reason is set to ``illegal``. The accepted values are documented in this :ref:`table <abuse-report-illegal_category-parameter>`.
    :<json string|null illegal_subcategory: The specific violation - only required when the reason is set to ``illegal``. The accepted values are documented in this :ref:`table <abuse-report-illegal_subcategory-parameter>`.
    :>json object|null reporter: The user who submitted the report, if authenticated.
    :>json int reporter.id: The id of the user who submitted the report.
    :>json string reporter.name: The name of the user who submitted the report.
    :>json string reporter.username: The username of the user who submitted the report.
    :>json string reporter.url: The link to the profile page for of the user who submitted the report.
    :>json string|null reporter_name: The provided name of the reporter, if not authenticated.
    :>json string|null reporter_email: The provided email of the reporter, if not authenticated.
    :>json object addon: The add-on reported for abuse.
    :>json string addon.guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json int|null addon.id: The add-on id on AMO, or ``null`` if the ``addon`` submitted was a guid.
    :>json string|null addon.slug: The add-on slug, or ``null`` if the ``addon`` submitted was a guid.
    :>json string message: The body/content of the abuse report.
    :>json string|null report_entry_point: The report entry point.
    :>json string|null addon_install_method: The add-on install method.
    :>json string|null addon_install_origin: The add-on install origin.
    :>json string|null addon_install_source: The add-on install source.
    :>json string|null addon_install_source_url: The add-on install source URL.
    :>json string|null addon_name: The add-on name in the locale used by the client.
    :>json string|null addon_signature: The add-on signature state.
    :>json string|null addon_summary: The add-on summary in the locale used by the client.
    :>json string|null addon_version: The add-on version string.
    :>json string|null app: The application used by the client.
    :>json string|null appversion: The application version used by the client.
    :>json string|null lang: The language code of the locale used by the client for the application.
    :>json string|null location: Where the content being reported is located - on AMO or inside the add-on.
    :>json string|null client_id: The client's hashed telemetry ID.
    :>json string|null install_date: The add-on install date.
    :>json string|null operating_system: The client's operating system.
    :>json string|null operating_system_version: The client's operating system version.
    :>json string|null reason: The reason for the report.
    :>json string|null illegal_category: The type of illegal content - only defined when the reason is set to ``illegal``.
    :>json string|null illegal_subcategory: The specific violation - only defined when the reason is set to ``illegal``.

.. _abuse-report_entry_point-parameter:

 Accepted values for the ``report_entry_point`` parameter:

 ===========================  =================================================
                       Value  Description
 ===========================  =================================================
                   uninstall  Report button shown at uninstall time
                        menu  Report menu in Add-ons Manager
        toolbar_context_menu  Report context menu on add-on toolbar
                         amo  Report button on an AMO page (using ``navigator.mozAddonManager.reportAbuse``)
        unified_context_menu  Report unified extensions (context) menu
 ===========================  =================================================

.. _abuse-addon_install_method-parameter:

 Accepted values for the ``addon_install_method`` parameter:

  .. note::

      This should match what is documented for ``addonsManager.install.extra_keys.method`` in `Firefox telemetry event definition <https://searchfox.org/mozilla-central/source/toolkit/components/telemetry/Events.yaml>`_ except that the values are normalized by being converted to lowercase with the ``:`` and ``-`` characters converted to ``_``. In addition, extra values are supported for backwards-compatibility purposes, since Firefox before version 70 merged source and method into the same value. If an unsupported value is sent for this parameter, it will be silently changed to special ``other`` instead of raising a 400 error.

 ===========================  =================================================
                       Value  Description
 ===========================  =================================================
                    amwebapi  Add-on Manager Web API
                        link  Direct Link
              installtrigger  InstallTrigger API
           install_from_file  Local File
       management_webext_api  WebExt Management API
               drag_and_drop  Drag & Drop
                    sideload  Sideload
                    file_url  File URL
                         url  URL
                       other  Other
           enterprise_policy  Enterprise Policy (obsolete, for backwards-compatibility)
                distribution  Included in build (obsolete, for backwards-compatibility)
                system_addon  System Add-on (obsolete, for backwards-compatibility)
             temporary_addon  Temporary Add-on (obsolete, for backwards-compatibility)
                        sync  Sync (obsolete, for backwards-compatibility)
 ===========================  =================================================

.. _abuse-addon_install_source-parameter:

 Accepted values for the ``addon_install_source`` parameter:

  .. note::

      This should match what is documented for ``addonsManager.install.extra_keys.method`` in `Firefox telemetry event definition <https://searchfox.org/mozilla-central/source/toolkit/components/telemetry/Events.yaml>`_ except that the values are normalized by being converted to lowercase with the ``:`` and ``-`` characters converted to ``_``. We support the additional ``other`` value as a catch-all. If an unsupported value is sent for this parameter, it will be silently changed to ``other`` instead of raising a 400 error.

 ===========================  =================================================
                       Value  Description
 ===========================  =================================================
                about_addons  Add-ons Manager
             about_debugging  Add-ons Debugging
           about_preferences  Preferences
                         amo  AMO
                 app_builtin  Built-in Add-on
                  app_global  Application Add-on
                 app_profile  App Profile
           app_system_addons  System Add-on (Update)
         app_system_defaults  System Add-on (Bundled)
            app_system_local  System-wide Add-on (OS Local)
          app_system_profile  System Add-on (Profile)
            app_system_share  System-wide Add-on (OS Share)
             app_system_user  System-wide Add-on (User)
                       disco  Disco Pane
                distribution  Included in build
           enterprise_policy  Enterprise Policy
                   extension  Extension
                    file_url  File URL
                  gmp_plugin  GMP Plugin
                    internal  Internal
                       other  Other
                      plugin  Plugin
                       rtamo  Return To AMO
                        sync  Sync
                system_addon  System Add-on
             temporary_addon  Temporary Add-on
                     unknown  Unknown
           winreg_app_global  Windows Registry (Global)
             winreg_app_user  Windows Registry (User)
 ===========================  =================================================

.. _abuse-addon_signature-parameter:


 Accepted values for the ``addon_signature`` parameter:

 ===========================  =================================================
                       Value  Description
 ===========================  =================================================
         curated_and_partner  Curated and partner
                     curated  Curated
                     partner  Partner
                 non_curated  Non-curated
                    unsigned  Unsigned
                      broken  Broken
                     unknown  Unknown
                     missing  Missing
                 preliminary  Preliminary
                      signed  Signed
                      system  System
                  privileged  Privileged
 ===========================  =================================================

.. _abuse-addon-reason-parameter:

 Accepted values for the ``reason`` parameter (for add-on abuse reports):

 ===========================  ================================================================
                       Value  Description
 ===========================  ================================================================
                      damage  Damages computer and/or data
                        spam  Creates spam or advertising
                    settings  Changes search / homepage / new tab page without informing user
                      broken  Doesn’t work, breaks websites, or slows Firefox down
                      policy  Hateful, violent, or illegal content
                   deceptive  Doesn't match description
                    unwanted  Wasn't wanted / impossible to get rid of
   hateful_violent_deceptive  Hateful, violent, deceptive, or other inappropriate content
                     illegal  Violates the law or contains content that violates the law
               does_not_work  Doesn’t work, breaks websites, or slows Firefox down
               feedback_spam  Spam
              something_else  Something else
                       other  Other
 ===========================  ================================================================


.. _abuse-location-parameter:

 Accepted values for the ``location`` parameter:

 ===========================  ===================================================
                       Value  Description
 ===========================  ===================================================
                         amo  Offending content is on add-on's detail page on AMO
                       addon  Offending content is inside the add-on
                        both  Offending content is in both locations
 ===========================  ===================================================

.. _abuse-report-illegal_category-parameter:

 Accepted values for the ``illegal_category`` parameter:

 ================================================  ================================================
                                            Value  Description
 ================================================  ================================================
                                   animal_welfare  Animal welfare
                             consumer_information  Consumer information infringements
           data_protection_and_privacy_violations  Data protection and privacy violations
                        illegal_or_harmful_speech  Illegal or harmful speech
              intellectual_property_infringements  Intellectual property infringements
 negative_effects_on_civic_discourse_or_elections  Negative effects on civic discourse or elections
                         non_consensual_behaviour  Non-consensual behavior
                pornography_or_sexualized_content  Pornography or sexualized content
                             protection_of_minors  Protection of minors
                         risk_for_public_security  Risk for public security
                                  scams_and_fraud  Scams or fraud
                                        self_harm  Self-harm
                   unsafe_and_prohibited_products  Unsafe, non-compliant, or prohibited products
                                         violence  Violence
                                            other  Other
 ================================================  ================================================

.. _abuse-report-illegal_subcategory-parameter:

 Accepted values for the ``illegal_subcategory`` parameter:

 ================================================  ============================================  =============================================================================================
 Illegal category                                  Value                                         Description
 ================================================  ============================================  =============================================================================================
 animal_welfare                                    other                                         Something else
 consumer_information                              insufficient_information_on_traders           Insufficient information on traders
 consumer_information                              noncompliance_pricing                         Non-compliance with pricing regulations
 consumer_information                              hidden_advertisement                          Hidden advertisement or commercial communication, including by influencers
 consumer_information                              misleading_info_goods_services                Misleading information about the characteristics of the goods and services
 consumer_information                              misleading_info_consumer_rights               Misleading information about the consumer’s rights
 consumer_information                              other                                         Something else
 data_protection_and_privacy_violations            biometric_data_breach                         Biometric data breach
 data_protection_and_privacy_violations            missing_processing_ground                     Missing processing ground for data
 data_protection_and_privacy_violations            right_to_be_forgotten                         Right to be forgotten
 data_protection_and_privacy_violations            data_falsification                            Data falsification
 data_protection_and_privacy_violations            other                                         Something else
 illegal_or_harmful_speech                         defamation                                    Defamation
 illegal_or_harmful_speech                         discrimination                                Discrimination
 illegal_or_harmful_speech                         hate_speech                                   Illegal incitement to violence and hatred based on protected characteristics (hate speech)
 illegal_or_harmful_speech                         other                                         Something else
 intellectual_property_infringements               design_infringement                           Design infringements
 intellectual_property_infringements               geographic_indications_infringement           Geographical indications infringements
 intellectual_property_infringements               patent_infringement                           Patent infringements
 intellectual_property_infringements               trade_secret_infringement                     Trade secret infringements
 intellectual_property_infringements               other                                         Something else
 negative_effects_on_civic_discourse_or_elections  violation_eu_law                              Violation of EU law relevant to civic discourse or elections
 negative_effects_on_civic_discourse_or_elections  violation_national_law                        Violation of national law relevant to civic discourse or elections
 negative_effects_on_civic_discourse_or_elections  misinformation_disinformation_disinformation  Misinformation, disinformation, foreign information manipulation and interference
 negative_effects_on_civic_discourse_or_elections  other                                         Something else
 non_consensual_behaviour                          non_consensual_image_sharing                  Non-consensual image sharing
 non_consensual_behaviour                          non_consensual_items_deepfake                 Non-consensual items containing deepfake or similar technology using a third party's features
 non_consensual_behaviour                          online_bullying_intimidation                  Online bullying/intimidation
 non_consensual_behaviour                          stalking                                      Stalking
 non_consensual_behaviour                          other                                         Something else
 pornography_or_sexualized_content                 adult_sexual_material                         Adult sexual material
 pornography_or_sexualized_content                 image_based_sexual_abuse                      Image-based sexual abuse (excluding content depicting minors)
 pornography_or_sexualized_content                 other                                         Something else
 protection_of_minors                              age_specific_restrictions_minors              Age-specific restrictions concerning minors
 protection_of_minors                              child_sexual_abuse_material                   Child sexual abuse material
 protection_of_minors                              grooming_sexual_enticement_minors             Grooming/sexual enticement of minors
 protection_of_minors                              other                                         Something else
 risk_for_public_security                          illegal_organizations                         Illegal organizations
 risk_for_public_security                          risk_environmental_damage                     Risk for environmental damage
 risk_for_public_security                          risk_public_health                            Risk for public health
 risk_for_public_security                          terrorist_content                             Terrorist content
 risk_for_public_security                          other                                         Something else
 scams_and_fraud                                   inauthentic_accounts                          Inauthentic accounts
 scams_and_fraud                                   inauthentic_listings                          Inauthentic listings
 scams_and_fraud                                   inauthentic_user_reviews                      Inauthentic user reviews
 scams_and_fraud                                   impersonation_account_hijacking               Impersonation or account hijacking
 scams_and_fraud                                   phishing                                      Phishing
 scams_and_fraud                                   pyramid_schemes                               Pyramid schemes
 scams_and_fraud                                   other                                         Something else
 self_harm                                         content_promoting_eating_disorders            Content promoting eating disorders
 self_harm                                         self_mutilation                               Self-mutilation
 self_harm                                         suicide                                       Suicide
 self_harm                                         other                                         Something else
 unsafe_and_prohibited_products                    prohibited_products                           Prohibited or restricted products
 unsafe_and_prohibited_products                    unsafe_products                               Unsafe or non-compliant products
 unsafe_and_prohibited_products                    other                                         Something else
 violence                                          coordinated_harm                              Coordinated harm
 violence                                          gender_based_violence                         Gender-based violence
 violence                                          human_exploitation                            Human exploitation
 violence                                          human_trafficking                             Human trafficking
 violence                                          incitement_violence_hatred                    General calls or incitement to violence and/or hatred
 violence                                          other                                         Something else
 other                                             other                                         Something else
 ================================================  ============================================  =============================================================================================


------------------------------
Submitting a user abuse report
------------------------------

.. _`userabusereport-create`:

The following API endpoint allows an abuse report to be submitted for a user account
on https://addons.mozilla.org. Authentication is not required, but is recommended
so reports can be responded to if necessary.

.. http:post:: /api/v5/abuse/report/user/

    .. _userabusereport-create-request:

    :<json string|int user: The id or username of the user to report for abuse (required).
    :<json string message: The body/content of the abuse report (required).
    :<json string|null lang: The language code of the locale used by the client for the application.
    :<json string|null reason: The reason for the report. The accepted values are documented in the :ref:`table below <abuse-user-reason-parameter>`.
    :<json string|null reporter_name: The provided name of the reporter, if not authenticated.
    :<json string|null reporter_email: The provided email of the reporter, if not authenticated.
    :<json string|null illegal_category: The type of illegal content - only required when the reason is set to ``illegal``. The accepted values are documented in this :ref:`table <abuse-report-illegal_category-parameter>`.
    :<json string|null illegal_subcategory: The specific violation - only required when the reason is set to ``illegal``. The accepted values are documented in this :ref:`table <abuse-report-illegal_subcategory-parameter>`.
    :>json object|null reporter: The user who submitted the report, if authenticated.
    :>json int reporter.id: The id of the user who submitted the report.
    :>json string reporter.name: The name of the user who submitted the report.
    :>json string reporter.url: The link to the profile page for of the user who submitted the report.
    :>json string reporter.username: The username of the user who submitted the report.
    :>json string|null reporter_name: The provided name of the reporter, if not authenticated.
    :>json string|null reporter_email: The provided email of the reporter, if not authenticated.
    :>json object user: The user reported for abuse.
    :>json int user.id: The id of the user reported.
    :>json string user.name: The name of the user reported.
    :>json string user.url: The link to the profile page for of the user reported.
    :>json string user.username: The username of the user reported.
    :>json string message: The body/content of the abuse report.
    :>json string|null lang: The language code of the locale used by the client for the application.
    :>json string|null illegal_category: The type of illegal content - only defined when the reason is set to ``illegal``.
    :>json string|null illegal_subcategory: The specific violation - only defined when the reason is set to ``illegal``.


.. _abuse-user-reason-parameter:

 Accepted values for the ``reason`` parameter (for user abuse reports):

 ===========================  ================================================================
                       Value  Description
 ===========================  ================================================================
   hateful_violent_deceptive  Hateful, violent, deceptive, or other inappropriate content
                     illegal  Violates the law or contains content that violates the law
               feedback_spam  Spam
              something_else  Something else
 ===========================  ================================================================

--------------------------------
Submitting a rating abuse report
--------------------------------

.. _`ratingabusereport-create`:

The following API endpoint allows an abuse report to be submitted for a rating
on https://addons.mozilla.org. Authentication is not required, but is recommended
so reports can be responded to if necessary.

.. http:post:: /api/v5/abuse/report/rating/

    .. _ratingabusereport-create-request:

    :<json string|int rating: The id of the rating to report for abuse (required).
    :<json string message: The body/content of the abuse report (required).
    :<json string|null lang: The language code of the locale used by the client for the application.
    :<json string|null reason: The reason for the report. The accepted values are documented in the :ref:`table below <abuse-rating-reason-parameter>`.
    :<json string|null reporter_name: The provided name of the reporter, if not authenticated.
    :<json string|null reporter_email: The provided email of the reporter, if not authenticated.
    :<json string|null illegal_category: The type of illegal content - only required when the reason is set to ``illegal``. The accepted values are documented in this :ref:`table <abuse-report-illegal_category-parameter>`.
    :<json string|null illegal_subcategory: The specific violation - only required when the reason is set to ``illegal``. The accepted values are documented in this :ref:`table <abuse-report-illegal_subcategory-parameter>`.
    :>json object|null reporter: The user who submitted the report, if authenticated.
    :>json int reporter.id: The id of the user who submitted the report.
    :>json string reporter.name: The name of the user who submitted the report.
    :>json string reporter.url: The link to the profile page for of the user who submitted the report.
    :>json string reporter.username: The username of the user who submitted the report.
    :>json string|null reporter_name: The provided name of the reporter, if not authenticated.
    :>json string|null reporter_email: The provided email of the reporter, if not authenticated.
    :>json object rating: The user reported for abuse.
    :>json int rating.id: The id of the rating reported.
    :>json string message: The body/content of the abuse report.
    :>json string|null lang: The language code of the locale used by the client for the application.
    :>json string|null reason: The reason for the report.
    :>json string|null illegal_category: The type of illegal content - only defined when the reason is set to ``illegal``.
    :>json string|null illegal_subcategory: The specific violation - only defined when the reason is set to ``illegal``.


.. _abuse-rating-reason-parameter:

 Accepted values for the ``reason`` parameter (for rating abuse reports):

 ===========================  ================================================================
                       Value  Description
 ===========================  ================================================================
   hateful_violent_deceptive  Hateful, violent, deceptive, or other inappropriate content
                     illegal  Violates the law or contains content that violates the law
              something_else  Something else
 ===========================  ================================================================


------------------------------------
Submitting a collection abuse report
------------------------------------

.. _`collectionabusereport-create`:

The following API endpoint allows an abuse report to be submitted for a collection
on https://addons.mozilla.org. Authentication is not required, but is recommended
so reports can be responded to if necessary.

.. http:post:: /api/v5/abuse/report/collection/

    .. _collectionabusereport-create-request:

    :<json string|int collection: The id of the collection to report for abuse (required).
    :<json string message: The body/content of the abuse report (required).
    :<json string|null lang: The language code of the locale used by the client for the application.
    :<json string|null reason: The reason for the report. The accepted values are documented in the :ref:`table below <abuse-collection-reason-parameter>`.
    :<json string|null reporter_name: The provided name of the reporter, if not authenticated.
    :<json string|null reporter_email: The provided email of the reporter, if not authenticated.
    :<json string|null illegal_category: The type of illegal content - only required when the reason is set to ``illegal``. The accepted values are documented in this :ref:`table <abuse-report-illegal_category-parameter>`.
    :<json string|null illegal_subcategory: The specific violation - only required when the reason is set to ``illegal``. The accepted values are documented in this :ref:`table <abuse-report-illegal_subcategory-parameter>`.
    :>json object|null reporter: The user who submitted the report, if authenticated.
    :>json int reporter.id: The id of the user who submitted the report.
    :>json string reporter.name: The name of the user who submitted the report.
    :>json string reporter.url: The link to the profile page for of the user who submitted the report.
    :>json string reporter.username: The username of the user who submitted the report.
    :>json string|null reporter_name: The provided name of the reporter, if not authenticated.
    :>json string|null reporter_email: The provided email of the reporter, if not authenticated.
    :>json object collection: The collection reported for abuse.
    :>json int collection.id: The id of the collection reported.
    :>json string message: The body/content of the abuse report.
    :>json string|null lang: The language code of the locale used by the client for the application.
    :>json string|null illegal_category: The type of illegal content - only defined when the reason is set to ``illegal``.
    :>json string|null illegal_subcategory: The specific violation - only defined when the reason is set to ``illegal``.


.. _abuse-collection-reason-parameter:

 Accepted values for the ``reason`` parameter (for collection abuse reports):

 ===========================  ================================================================
                       Value  Description
 ===========================  ================================================================
   hateful_violent_deceptive  Hateful, violent, deceptive, or other inappropriate content
                     illegal  Violates the law or contains content that violates the law
               feedback_spam  Spam
              something_else  Something else
 ===========================  ================================================================

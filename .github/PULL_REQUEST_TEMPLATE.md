Fixes: mozilla/addons#ISSUENUM

<!--
Thanks for opening a Pull Request (PR), here's a few guidelines as to what we need in your PR before we review it.
-->

### Description

<!--
Your PR will be squashed when merged so the 1st commit must contain a descriptive and concise summary of the change.
Additional details should be added in the description. If your change is simple enough to summarize in the commit, or
if it is not relevant for your PR, remove this section.
-->

### Context

<!--
Often a pull request contains changes that are not fully self explanatory. Maybe this PR is a part of a series,
or maybe it is a partial change now with a more ambitious plan for the future. Add this additional context here.
If it is not relevant for your PR, remove this section.
-->

### Testing

<!--
Your change must be related to an existing, open issue. This issue should contain testing instructions.
Often, the testing info in the issue is higher level, geared towards a user or QA experience.
Here you can provide information for a developer verifying this PR. Get technical.
If it is not relevant to your PR, remove this section.
-->

### Checklist

<!--
Here's a few guidelines as to what we need in your PR before we review it.
Please delete anything that isn't relevant to your patch.
-->

- [ ] Add `#ISSUENUM` at the top of your PR to an existing open issue in the mozilla/addons repository.
- [ ] Successfully verified the change locally.
- [ ] The change is covered by automated tests, or otherwise indicated why doing so is unnecessary/impossible.
- [ ] Add before and after screenshots (Only for changes that impact the UI).
  - use `##` headers so you get the description and a line break to easily know when one screenshot ends and another starts
  - specify an absolute width value on the html tag and set height to auto, otherwise it distorts the image and makes it too big `<img width=450" height="auto ... />`
  - make the screenshots focus on the main part of the screen you want to represent so the reviewer doesn't have to scroll much to see the relevant part and get lost between the images.

- [ ] Add or update relevant [docs](../docs/) reflecting the changes made.

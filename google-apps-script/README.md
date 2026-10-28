# Strativa Energy Monthly Google Performance Report

This Google Apps Script creates a read-only monthly report from Google Analytics 4 and Google Search Console. It saves Markdown and JSON files in a Google Drive folder named `Strativa Energy Monthly Reports`.

## One-time setup

1. Open [Google Apps Script](https://script.google.com/) while signed in as the Google account that can access the Strativa Energy GA4 property and Search Console property.
2. Create a new standalone project named `Strativa Energy Monthly Google Performance Report`.
3. Replace the default files with `Code.gs` and `appsscript.json` from this folder. In the Apps Script editor, open **Project Settings** and enable **Show appsscript.json manifest file in editor** before replacing the manifest.
4. Set the project timezone to `Australia/Melbourne`.
5. If automatic GA4 discovery does not find the property, set `ga4PropertyId` in `Code.gs` to the numeric GA4 property ID. This is an identifier, not a secret.
6. Run `setupMonthlyTrigger` once and approve the requested read-only Google scopes.
7. Run `generateMonthlyReport` once to verify access and create the first report.

The script never changes website files, GA4 settings, Search Console settings, or search data. It stores only aggregated report data in Drive and does not collect user-level data.

## Schedule

The trigger runs on the first day of each month at approximately 08:00 in `Australia/Melbourne`. Apps Script controls the exact execution minute.

## Files

- `Code.gs` — report collection, comparison, Markdown/JSON generation, and monthly trigger.
- `appsscript.json` — read-only Analytics/Search Console scopes and external request permission.

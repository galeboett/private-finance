# UX/UI Cleanup Gameplan

## Goal

Make the app feel like a calm personal finance workstation: dense enough for repeated ledger work, but not cramped, jumpy, or visually noisy. The main problem is not one bad component. It is inconsistent sizing, too many card-like surfaces, fixed-width data grids, and controls that change shape from screen to screen.

> **Design reference, not status report:** Some recommendations here are implemented, including single-account sidebar flattening, analysis-tab cleanup, filtered summaries, and custom date ranges. Settings information architecture, deeper component extraction, and several visual-system items remain open. Track completion in the [iteration 3 implementation plan](pf-implementation-plan-iteration-3-7-14-26.md).

## Current UX Diagnosis

The app is doing the right jobs: import files, review transactions, maintain accounts, and read reports. The UI currently makes those jobs feel heavier than they are.

Key issues:

- The visual system mixes rounded pills, square panels, heavy shadows, gradients, bordered cards, compact controls, and large empty areas without a consistent rule.
- Dashboard widgets compete with the actual work. The overview has metrics, custom dashboard controls, widget cards, and a report panel before the user reaches the ledger/review workflow.
- Ledger and holdings tables rely on very wide fixed minimum widths, which creates horizontal scrolling and makes the interface feel oversized.
- The sidebar tries to be navigation, account taxonomy, account balances, customization, and account creation all at once.
- Review, import, account management, and settings share the same generic panel style even though they are different workflows.
- Mobile behavior mostly stacks desktop components instead of redesigning them for narrow screens.
- Several controls use text labels where icon-only or compact icon+tooltip controls would be cleaner, while other controls are icon-only without enough hierarchy.

## Priority 1: Normalize The Design System

Create a small set of layout and control rules before touching individual screens.

Recommended changes:

- Use one radius scale: `6px` for panels and inputs, `999px` only for true chips/badges.
- Reduce card shadows across app work surfaces. Use borders and background contrast for most panels; reserve shadows for modals/popovers.
- Standardize control heights:
  - Inputs/selects/textareas: `36px` minimum.
  - Primary/secondary buttons: `34px`.
  - Compact icon buttons: `30px` square.
  - Table row controls: `30px`.
- Remove decorative radial gradients from dashboard widgets and sidebar unless they communicate state.
- Introduce shared CSS tokens for spacing: `4, 8, 12, 16, 20, 24`.
- Replace repeated one-off panel styles with shared classes:
  - `.surface`
  - `.surfaceHeader`
  - `.toolbar`
  - `.dataGrid`
  - `.statusChip`
  - `.iconButton`

Files to start with:

- `frontend/src/styles.css`
- `frontend/src/App.tsx`

## Priority 2: Simplify The Overview

The overview should answer: "What needs my attention now?" It should not feel like a customizable dashboard builder on first contact.

Recommended changes:

- Keep the four top metrics, but make them smaller and less card-like.
- Replace the current dashboard widget grid with a single attention-first layout:
  - Review queue count and call to action.
  - Import next-step status.
  - Cash-flow snapshot.
  - Account/net-worth summary.
- Move "Customize dashboard" out of the main first-view flow. Put it behind settings or a small overflow/menu control.
- Reduce the report surface height and avoid the oversized `flowCanvas` as the default report view. Use simple bar/table summaries first; keep the visual graphic as an optional expanded report.
- Make the period selector visually lighter. It currently competes with primary actions.

Acceptance check:

- At desktop width, the first screen should show top metrics and the next important action without feeling like a wall of cards.
- At 760px width, the overview should not become a long stack of similar-looking cards.

## Priority 3: Rebuild Ledger Layout Around Usability

The ledger is the heart of the app. It should be scannable, editable, and stable without huge horizontal scrolling.

Current issue:

- `.ledgerHeader` and `.ledgerRow` use `min-width: 1420px`, which forces a spreadsheet-like scroll even when many columns could be collapsed, hidden, or moved into a detail row.

Recommended changes:

- Convert the ledger into a responsive data grid with priority columns.
- Always visible:
  - Select
  - Date
  - Description
  - Category
  - Amount
  - Actions
- Secondary fields:
  - Institution
  - Account
  - Details/note
  - Type
- On desktop, show secondary fields when space allows.
- On narrower screens, put secondary fields in an expandable row detail area.
- Replace the always-visible Delete text button with an icon button plus tooltip, and keep destructive text in confirmations.
- Make row edit mode visually calmer:
  - Avoid pill-shaped selects inside table cells.
  - Use rectangular inputs aligned to cell edges.
  - Keep "Done" and "Cancel" in a fixed row action area.
- Make category assignment a true combobox-style popover with consistent width and keyboard behavior.

Acceptance check:

- No horizontal scroll should be needed for the default ledger view at 1280px.
- At mobile width, each transaction should become a readable card/list row rather than a squeezed table.

## Priority 4: Make Review Inbox A Fast Workflow

The review screen should support quick decisions. Right now each transaction card carries a lot of repeated UI: type select, category select, note textarea, rule hint, and three action buttons.

Recommended changes:

- Split review cards into collapsed and expanded states.
- Collapsed card:
  - Description
  - Date/account
  - Amount
  - Suggested status/category
  - Primary confirm action
- Expanded card:
  - Type
  - Category
  - Note
  - Save rule
  - Delete
- Move the rule hint behind a small "Rule preview" disclosure unless the user is saving a rule.
- Make bulk review controls sticky within the Review Inbox panel.
- Replace repeated text buttons with a consistent command row:
  - Confirm
  - Save rule
  - More/delete
- Add a clear visual distinction between "needs category", "suggested", and "possible duplicate" beyond badge text.

Acceptance check:

- A user should be able to confirm ordinary suggested transactions with one click per row.
- The screen should show more review items per viewport without feeling cramped.

## Priority 5: Rework Import Into A Stepper

Import currently appears in settings and a modal, with overlapping controls for smart/manual flows. It would feel cleaner as a guided sequence.

Recommended changes:

- Use a 3-step import flow:
  1. Choose file.
  2. Match/create account.
  3. Preview and commit.
- Show one primary action at a time.
- Hide manual account creation until the app cannot confidently match the file or the user chooses "Create account".
- Move categorized history import into a separate "Import history" section, not mixed into ordinary CSV import.
- Replace raw file inputs with styled file drop zones/buttons that show selected filename.
- Keep preview rows compact and table-like, with a clear warning area.

Acceptance check:

- The import modal should never show Analyze, Preview, and Commit as equally weighted actions before the user has completed earlier steps.

## Priority 6: Tame The Sidebar

The sidebar is useful but too busy. It is doing global navigation, account tree, balances, customization, resize behavior, and account creation.

Recommended changes:

- Keep global nav at the top.
- Add a clear "Accounts" section with search/filter when account count grows.
- Move taxonomy customization out of the persistent sidebar into settings or a dedicated account organization modal.
- Keep "Add Account" as a compact primary action near the accounts header, not as a footer control.
- Remove the abrupt 84px collapsed sidebar behavior below 1100px. Either keep a readable sidebar until mobile, or switch to a top navigation/mobile drawer.
- Use one balance treatment. Negative balances currently become bright pill badges, which makes the sidebar visually uneven.

Acceptance check:

- At 1100px, the sidebar should still communicate where the user is without hiding most text.
- At mobile width, there should be a replacement navigation path, not simply a hidden sidebar.

## Priority 7: Clean Up Reports

Reports should feel analytical, not decorative.

Recommended changes:

- Replace the current cash-flow graphic with simpler financial charts:
  - Monthly income/expense/net grouped bars.
  - Spending category ranked bars.
  - Net-worth account/allocation summaries.
- Use consistent chart dimensions and avoid large minimum heights when there is little data.
- Keep report tabs, but make "Reports" either an overview tab or remove it if Cash Flow/Spending/Income/Net Worth are the real views.
- Let empty states suggest the next action with a direct import/review button.

Acceptance check:

- Reports should show useful numbers above visual decoration.
- Empty report states should take less vertical space.

## Priority 8: Responsive Pass

The mobile CSS mostly stacks desktop grids. That fixes overflow only partially.

Recommended changes:

- Add explicit mobile layouts for:
  - Overview metrics
  - Ledger rows
  - Review cards
  - Import modal
  - Account management rows
  - Holdings rows
- Avoid fixed minimum widths in mobile paths.
- Make filters horizontal scroll chips or a drawer, not full-width stacked dropdowns.
- Ensure modal cards use nearly full viewport width with stable action buttons at the bottom.

Acceptance check:

- At 390px width, no primary workflow should require horizontal scrolling.
- Buttons should not wrap into awkward two-line labels.

## Suggested Implementation Order

1. Create shared surface/control tokens in CSS.
2. Normalize buttons, inputs, cards, shadows, and radii.
3. Rework the ledger table into a responsive data grid.
4. Simplify the review cards and bulk toolbar.
5. Turn import into a stepper.
6. Simplify overview dashboard widgets.
7. Move sidebar taxonomy customization out of the persistent sidebar.
8. Do a mobile-specific layout pass.
9. Add visual regression checks for desktop, tablet, and mobile widths.

## Quick Wins

- Remove heavy shadows from `.metricTile`, `.dashboardWidget`, `.toolPanel`, and `.ledgerPanel`.
- Change `.ledgerHeader` and `.ledgerRow` away from `min-width: 1420px`.
- Change `.holdingsHeader` and `.holdingsRow` away from `min-width: 950px`.
- Make all text buttons with only destructive purpose use an icon button until confirmation.
- Reduce the number of pill-shaped controls.
- Move dashboard customization off the main overview.
- Make the import modal show only the next valid action.

## Validation Checklist

Check these screens after each phase:

- Login/setup screen.
- Overview with no data and with populated data.
- All Accounts ledger.
- Single account ledger with many transactions.
- Review inbox with 0, 1, and many items.
- Import modal before file, after file, after analysis, after preview.
- Reports with empty and populated data.
- Settings/account management.

Viewport checks:

- 1440 x 900
- 1280 x 720
- 1024 x 768
- 760 x 900
- 390 x 844

Done means:

- No unexpected horizontal scroll in primary workflows.
- Text fits inside buttons, chips, cards, rows, and modals.
- Primary actions are obvious.
- Destructive actions are visually secondary until confirmation.
- The app feels denser, calmer, and more consistent.

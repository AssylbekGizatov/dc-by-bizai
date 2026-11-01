---
name: Grand Mobile Support Workbench
description: A comparison workspace for evidence, rules and a human-reviewed reply.
colors:
  primary: "#304eb4"
  primary-hover: "#243e94"
  primary-wash: "#e9eefc"
  shell: "#18223b"
  shell-muted: "#c2cbe0"
  page: "#edf0f5"
  surface: "#ffffff"
  ink: "#20283d"
  muted: "#58637b"
  line: "#dce1ea"
  line-strong: "#9aa7bd"
  attention: "#874309"
  attention-wash: "#fff1dd"
  error: "#a52437"
  success: "#15634c"
typography:
  heading:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.5
rounded:
  control: "4px"
  work-region: "6px"
  dialog: "8px"
spacing:
  tight: "4px"
  related: "8px"
  control: "12px"
  group: "16px"
  region: "24px"
  page: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "10px 15px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.surface}"
---

## Evidence and scope

This visual system remains the implementation reference. The final frontend run passed 34 tests and TypeScript/Vite build. Earlier browser/responsive checks are documented in [design-verification](docs/design-verification.md), with their historical scope retained. Product claims and measurements are maintained in [the submission](docs/SUBMISSION.md) and [the latest verification](docs/DEADLINE_VERIFICATION.md).

## Overview

This is an operator's workspace. The screen gives the original request, extracted information, source rules and response their own stable areas. Classification and human-review reasons precede the comparison. The signature is the two-part review document, with the player's source on the left and the editable response on the right, separated by a single hairline.

## Colors

The deep blue shell carries navigation. The blue primary colour identifies actions, selection and links. Warm amber means attention or required human review; red means a failed action; green appears in successful validation. State is also named in text. The Grand Mobile mark retains its established green. Neutral surfaces separate intake, page and document without nested decorative cards.

## Typography

One locally supplied IBM Plex Sans family covers Cyrillic and Latin. Page headings are 30px/600 (26px on phone), document headings 22px, sections 16px/600, player text 17px/1.65, reply text 16px/1.65, compact labels and metadata 12–14px. Identifiers alone use monospace. Fonts are bundled and use swap; no font CDN is needed.

## Layout

Maximum outer width is 1680px. Desktop intake is 310px (330px on wide screens); the document receives remaining space. When the document container reaches 720px its source and response areas share two columns. The administrator can hide the intake after analysis; its values remain available under “Изменить исходное обращение”. On phones the form collapses after a successful analysis and the result offers direct section buttons. Source, rules and reply follow the same reading order in one column.

Queue rows are full-width scanning targets. A selected request creates a 300px queue beside the document; below 900px the detail replaces the list with an explicit return link. Queue status, search and filters precede results. Server pagination limits each page to 50 records. The selected desktop list has its own bounded scroll area. No page-level horizontal scroll is intended.

## Elevation & Depth

Work areas are flat and divided by surface colour or hairlines. Only the authentication dialog uses a shadow (`0 20px 60px #10182b55`). No ornamental gradients or floating metric tiles.

## Shapes

Controls use 4px corners; work regions 6px; the dialog 8px. Form borders carry interaction boundaries. Important controls have a minimum 44px target, 46px on phone. Focus uses a visible 3px outline, amber on the dark shell and blue elsewhere.

## Components

The primary action is solid blue. Secondary actions have white fill and a visible border. Pending writes disable controls; text announces progress. Errors preserve form and editor values. Loading uses one bounded progress indicator; reduced-motion makes it static without suppressing status text.

The review reason area names the human-review requirement before listing reasons. Rules show public number, section and full text; internal source IDs remain in the API data, not in the reading flow. Both analyzer and queue offer direct section buttons that move keyboard focus without changing the route or losing edits. Source text stays visible so reviewing it is an explicit part of the task. Facts pair each value with its origin; focus on a fact highlights the associated player text. Algorithm confidence stays inside diagnostics and is explicitly not measured accuracy.

The analyzer editor is for copying. Its hint links to the saved queue record for durable edits. The queue editor names the saved revision, distinguishes unsaved changes, edits notes, and exposes a recoverable draft and note after revision conflict. Simulation requires explicit confirmation and states that no message reaches the game.

## Do's and Don'ts

- Do put task and provenance before visual decoration.
- Do preserve typed work on network, authorization and revision errors.
- Do use the same control sizes and semantic colours across analyzer and queue.
- Do keep the original text accessible when normalizing Kazakh substitutions.
- Don't silently replace an API failure with synthetic demo data.
- Don't claim to inspect attachments or execute game actions.
- Don't add decorative metrics, gradients, arbitrary badges or nested cards.
- Don't put private rules, tickets or screenshots containing private source data in Git.

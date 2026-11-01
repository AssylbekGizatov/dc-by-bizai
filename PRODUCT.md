# Grand Mobile Support Copilot

Product status and evidence: [submission](docs/SUBMISSION.md), [latest verification](docs/DEADLINE_VERIFICATION.md). Capabilities below describe the existing review workflow; productivity gains require a separate user study.

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Grand Mobile support administrators reviewing short player requests, complaints, payment issues and account-access problems. Russian is the working interface language; player text and drafts may be Russian, Kazakh, Uzbek or another supported language.

## Product Purpose

Turn an incoming request into a reviewable classification, extracted information, relevant official rule sources and a draft in the player's language. The administrator makes the decision and can save edits, add a note, escalate or record a simulated send.

## Operating Context

The primary comparison is between the player's original words, machine interpretation, retrieved rules and the proposed reply. Desktop is the main work surface; tablet and phone must support the same workflow. The real API and an explicitly selected synthetic browser demonstration are separate modes.

## Capabilities and Constraints

- Preserve vanilla HTML/CSS/JavaScript + Vite and FastAPI contracts.
- Payments, ban appeals and suspected account compromise require human review independently of model category. Unknown off-topic also requires clarification and review.
- Rule identity and source visibility are implemented; applicability of direct taxonomy-selected citations remains incomplete.
- No game-server connection exists. Sending records a simulation only.
- The service has attachment counts, not attachment contents. Player claims are unverified.
- Preserve drafts on recoverable errors; resolve revision conflicts against fresh server data.
- Do not publish datasets, private rules, SQLite, tokens or derived private samples.
- Confidence is an algorithm score, not measured accuracy.

## Brand Commitments

Keep Grand Mobile naming. Build a professional, expressive support tool with clear Cyrillic typography, useful density and no decorative metrics, gradients or nested cards. The user delegated selection among distinct visual directions and routine design decisions.

## Evidence on Hand

Existing frontend, API contracts and synthetic examples. Official assignment defines operating restrictions. Actual player datasets and rule files remain private and are not visual fixtures.

## Product Principles

1. Make the origin and limits of every conclusion visible.
2. Keep source and answer available during review.
3. Give saving, copying and simulation distinct meanings.
4. Treat failures as recoverable states and preserve human work.

## Accessibility & Inclusion

Keyboard operation, visible focus, labelled fields, readable contrast, reduced-motion support, touch-sized actions and no page-level horizontal scrolling on phones are explicit requirements.

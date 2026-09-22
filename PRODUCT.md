# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One FPL manager using a private localhost tool before deadlines and during regular mini-league discussions. Their job is to turn a public FPL snapshot, player news, fixtures, and rival ownership into a confident next action.

## Product Purpose

FPL Brief gathers public FPL data for the manager's team and #club-football mini-league, then turns it into an auditable decision workspace. Success is a faster, evidence-led weekly discussion—not automated transfers or a promise of points.

## Positioning

The dashboard joins the manager's own squad, live public mini-league context, availability, fixtures, and explicitly editable planning scenarios in one local screen.

## Operating Context

The existing `fetch_fpl.py` refreshes `data/latest.json` and `digest.md` from the public FPL API. The dashboard runs only on the manager's computer and continues to work from the last snapshot when refresh is unavailable.

## Capabilities and Constraints

- Read-only FPL data; never log in, make transfers, or see rivals' unsubmitted moves.
- FPL availability and `ep_next` are inputs, not medical confirmation or a points forecast.
- The first dashboard release supports up to four saved Wildcard timing scenarios locally.
- The scope is the #club-football league only.

## Evidence on Hand

`data/latest.json`, `data/changes.json`, `digest.md`, `config.json`, and public FPL API responses. No proprietary injury-feed or authenticated FPL data is available.

## Product Principles

- Lead with the decision and the evidence behind it.
- Separate facts, FPL estimates, and the manager's assumptions.
- Make risk visible before it becomes a transfer problem.
- Preserve the existing zero-dependency collection workflow.

## Accessibility & Inclusion

Keyboard-operable controls, clear focus states, and text labels in addition to color.

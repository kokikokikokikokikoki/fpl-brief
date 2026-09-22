# Design system

## Direction

**Matchday control room.** This is a private desk used while checking fixtures and league movement, not a generic sports landing page. It rejects the usual stack of interchangeable metric cards in favour of a decisive briefing strip, a dense squad board, and evidence panels that read like match analysis.

## Scene and colour

The manager is likely checking the app on a laptop in the evening or close to a deadline. The surface is deep ink blue (`#07121f`) with slate work areas, off-white type, and restrained grass green for constructive action. Amber signals uncertainty and red is reserved for availability risk; each is paired with readable text.

## Type and layout

Use the system UI stack for fast, legible operations. Large figures are only used when they communicate a decision; data labels use tabular numerals. The desktop layout has a persistent league rail and a wide analysis canvas; compact screens collapse to a single column and horizontally scroll only dense tables.

## Components and states

Panels have crisp 1px boundaries, small corner radii, and offset shadows. Buttons, tabs, selects, and editable scenario fields have visible keyboard focus. Refresh, loading, stale-data, empty, and request-failure states must explain the condition and recovery.

## Motion

The active view enters once with a brief upward reveal; no recurring or decorative motion. Respect reduced-motion preferences.

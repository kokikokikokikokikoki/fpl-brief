---
name: FPL Brief
description: A coach's magnetic tactics board for evidence-led weekly FPL decisions.
colors:
  wall: "#D9DEDB"
  tray: "#DDE2E0"
  enamel: "#F7F8F5"
  enamel-shade: "#EEF1EC"
  frame-hi: "#E3E6E7"
  frame: "#B9BFC2"
  rule: "#C6CDCA"
  ink: "#14213D"
  ink-soft: "#4A5670"
  pitch-line: "rgb(20 120 110 / 28%)"
  marker-blue: "#1C55C7"
  marker-red: "#C9302C"
  marker-green: "#1C7C45"
  caution: "#9A6200"
typography:
  display:
    fontFamily: "Barlow Condensed, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 800
    lineHeight: 1
  headline:
    fontFamily: "Barlow Condensed, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 800
    lineHeight: 1.1
  label:
    fontFamily: "Barlow, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    letterSpacing: "0.06em"
  body:
    fontFamily: "Barlow, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  metric:
    fontFamily: "Barlow Condensed, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 700
  marker:
    fontFamily: "Kalam, cursive"
    fontSize: "20px"
    fontWeight: 700
rounded:
  board: "18px"
  enamel: "8px"
  panel: "14px"
  control: "10px"
  tag: "6px"
spacing:
  tight: "8px"
  standard: "16px"
  section: "28px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "#FFFFFF"
    rounded: "{rounded.control}"
    padding: "12px 16px"
  nav-active:
    backgroundColor: "{colors.enamel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
---
# Design System: FPL Brief

## Overview

**Creative North Star: "The Tactics Board."** The manager plans the week the way a coach does: at a white magnetic board in an aluminium frame. The XI are shirt magnets on a printed pitch. Decisions are dry-erase marker strokes: arrows for who comes in, a circle around the captain, and short handwritten notes. Everything else in the product (panels, tables, notes) is paper and enamel that belongs next to that board.

This replaced the 2026-09-23 Away-Day Route Map (Overseer decision 2026-09-25). The approved reference is `.impeccable/mockups/a-tactics-board.html`.

**Key characteristics**
- One light, low-glare world. The use scene is a manager at a laptop or phone in an ordinary indoor room, evening or daytime.
- Club-coloured shirt magnets are the only saturated colour on the board. Marker colours carry meaning; everything else is ink on enamel.
- The handwritten marker face is used only for annotations of *change or decision*. Facts are always set in Barlow.

## Colors

- **Enamel and enamel shade** make up the board surface and the note panels. **Wall** and **tray** form the ground around them and the rail.
- **Ink** is for primary text and the primary buttons. **Ink soft** is for secondary text (≥4.5:1 on enamel, and never used on the tray).
- **Marker green** means "start / positive change". **Marker red** means the deadline, "bench / warning", and the captain circle. **Marker blue** marks armband and selection notes, and is also the focus ring. **Caution** is amber-brown text for doubts; it is never used as fill.
- Semantic colour is always paired with a word ("IN", "Doubtful", "Blocked").

## Typography

- **Barlow Condensed** is for headings, metrics, and name plates. **Barlow** is for body text, tables, and controls. **Kalam** is for marker annotations only.
- The body is 16px, with a 15px minimum on panels and a 13px minimum for labels. Marker notes are 18–22px.
- Fonts are self-hosted with `@fontsource`, so there are no runtime third-party font requests.

## Components

- **Board.** An aluminium frame (gradient frame-hi → frame, 14px padding, radius 18px, soft offset shadow) around the enamel. The pitch lines are printed in faint teal. The bench is a recessed grey tray under the enamel.
- **Shirt magnet.** A minimal SVG jersey in club colours; keepers get a distinct keeper shirt. It sits on a round magnet base with an offset drop shadow, above a navy name plate and an "FPL est." line. Hover or selection lifts the magnet (translateY −6px, rotate −2deg, deeper shadow, 350ms expo ease-out). Doubtful players get a caution-coloured plate label and a "Doubtful" word.
- **Marker annotations.** SVG strokes with rounded caps and a slight wobble: arrows from the bench tray to the pitch for each suggested start, an ellipse around the captain, and short notes. They are decorative, so they are `aria-hidden`; the same facts appear as text in Coach's notes.
- **Coach's notes.** An enamel panel with dashed rules between sections, where marker-hand lines state the changes. It holds the selected-player detail (`aria-live`) and the Ask Jev prompt.
- **Panels and tables** (the other views) are enamel sheets on the wall, with a radius of 14px, soft offset shadows, dashed or solid rules, and no nested cards. Tables use 15px text and an ink-soft uppercase header.
- **Rail navigation.** A tray-coloured rail where each item has a magnet dot; the active item sits on enamel with a red dot. On narrow screens it becomes a horizontally scrolling strip.
- **Buttons.** Primary buttons are ink fill with white condensed uppercase text. Secondary buttons are an enamel fill with an ink rule. The focus ring is 3px marker blue.

## Interaction

- **Try-a-lineup.** Magnets can be dragged (pointer or touch) between the bench and the pitch, or selected with a click or keyboard and then swapped. Formation rules are enforced, and an illegal drop snaps back with a marker message. Totals update live. The board is saved in this browser only and never contacts FPL.
- **Motion.** There is one authored motion: the magnet lift and settle. Everything else is instant. Reduced-motion settings remove the lift transition.

## Don'ts

- No dark theme, neon, or glow. No gradient text. No emoji icons.
- Marker handwriting is never used for facts, numbers in tables, or body copy.
- Nothing may imply that the board changes the real FPL team. Every estimate is labelled as FPL's.

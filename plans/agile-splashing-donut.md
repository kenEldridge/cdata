# UI Overhaul Plan

## Problems to Fix

### 1. Performance: Re-renders during playback
- 16ms setInterval updates `currentTime` state every frame
- Causes full component tree re-render 60x/sec
- Fix: Use refs more, memoize components, only update state when visual changes needed

### 2. Fixed Layout - Not Using Screen Space
- FallingNotesCanvas: hardcoded 800x400
- VisualKeyboard: hardcoded 800x150
- Sidebar: fixed 400px
- Fix: Use viewport-relative sizing, flex/grid to fill available space

### 3. Unclear Hit Point
- Current: thin gray line at bottom of falling notes canvas
- User doesn't know exactly when to press
- Fix: Prominent hit zone with visual emphasis (glow, thicker, animated?)

### 4. Vertical Distribution Glow Confusing
- Current: radial gradient around each falling note
- Doesn't visually connect to horizontal keyboard
- Fix: Show distribution as horizontal range indicator on the keyboard itself, or as columns/lanes in the falling notes

## User Choices
- **Controls**: Collapsible sidebar (can hide to maximize screen space)
- **Hit zone**: Notes fall directly onto keyboard keys (no separate line)

## Final Layout

```
┌────────────────────────────────────────────────┬──────────┐
│  Logo + Song/Status (compact)                  │ [≡]      │
├────────────────────────────────────────────────┤ Sidebar  │
│                                                │ (toggle) │
│  ┌──────────────────────────────────────────┐ │          │
│  │                                          │ │ Play/    │
│  │        FALLING NOTES                     │ │ Pause    │
│  │        (fills available height)          │ │ Stop     │
│  │                                          │ │ Tempo    │
│  │  Notes fall into lanes aligned with keys │ │ Stats    │
│  │           ↓  ↓  ↓  ↓  ↓                 │ │ etc      │
│  └──────────────────────────────────────────┘ │          │
│  ┌──────────────────────────────────────────┐ │          │
│  │  █ █ █ █ █ █ █ █ █ █ █ █ █ █ █ █        │ │          │
│  │  KEYBOARD (notes land on keys)           │ │          │
│  │  Keys light up when note arrives         │ │          │
│  │  Distribution glow on keys               │ │          │
│  └──────────────────────────────────────────┘ │          │
│  ┌──────────────────────────────────────────┐ │          │
│  │  Lyrics / Current Section                 │ │          │
│  └──────────────────────────────────────────┘ │          │
└────────────────────────────────────────────────┴──────────┘
```

## Implementation Details

### 1. FallingNotesCanvas Changes
- Remove hit zone line completely
- Notes fall to bottom edge (y=height means note is "on" the key)
- Lanes align perfectly with keyboard keys below
- Remove radial distribution glow (confusing vertically)
- Size: 100% width, flex-grow to fill vertical space

### 2. VisualKeyboard Changes
- Keys receive notes directly (no gap between canvas and keyboard)
- Key lights up bright when note "lands" (y reaches bottom)
- Distribution glow on keys (horizontal makes sense)
- Size: 100% width, height 180-200px

### 3. App Layout Changes
- Main area: flexbox column (header → falling notes → keyboard → lyrics)
- Sidebar: fixed width when open (350px), collapse to icon bar (50px)
- Toggle button to show/hide sidebar
- Minimum window width: 1000px

### 4. Sidebar (PracticeControls)
- Add collapse/expand functionality
- When collapsed: show just icons
- When expanded: full controls as current

### 5. Performance
- Memoize canvas components
- Canvas internal RAF loop independent of React state

## Files to Modify

1. `src/App.tsx` - New layout with collapsible sidebar
2. `src/components/FallingNotesCanvas.tsx` - Remove hit line, align lanes with keys
3. `src/components/VisualKeyboard.tsx` - Key glow when note lands
4. `src/components/PracticeControls.tsx` - Add collapse/expand
5. `src/App.css` - Flexbox layout styles

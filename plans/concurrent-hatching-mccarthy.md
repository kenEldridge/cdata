# Plan: Fix Excessive Re-renders

## Problem Analysis

The App component renders **~60 times per second** during playback. On each render:

1. **Line 58**: `useState<AppConfig>(loadConfig())` - `loadConfig()` is called on **every render**
   - Even though useState ignores subsequent values, the function still executes
   - `loadConfig()` reads from localStorage and logs to console each time

2. **Playback loop** (lines 404-458): `setCurrentTime(time)` triggers a re-render every 16ms
   - This is necessary for UI updates (falling notes, keyboard)
   - But everything on the render path should be optimized

## Root Cause

```javascript
// PROBLEM: loadConfig() called on every render (even if result is ignored)
const [config, setConfig] = useState<AppConfig>(loadConfig());

// SOLUTION: Use lazy initializer - only called once on mount
const [config, setConfig] = useState<AppConfig>(() => loadConfig());
```

## Implementation

### Step 1: Fix Config Loading (`src/App.tsx`)

Change line 58 from:
```javascript
const [config, setConfig] = useState<AppConfig>(loadConfig());
```

To:
```javascript
const [config, setConfig] = useState<AppConfig>(() => loadConfig());
```

This uses React's **lazy state initializer** pattern - the function is only called once when the component mounts, not on every render.

### Step 2: Remove Debug Logging (Optional)

Line 56 logs on every render:
```javascript
console.log('[App] Component rendering');
```

Either remove this or make it conditional on a debug flag.

## Files to Modify

1. **`src/App.tsx`** (line 58)
   - Change `useState(loadConfig())` to `useState(() => loadConfig())`
   - Optionally remove/conditionalize line 56 debug log

## Expected Results

- **Before**: `loadConfig()` called ~60x/second during playback
- **After**: `loadConfig()` called once on mount
- **Performance gain**: Eliminates ~60 localStorage reads + JSON parses per second

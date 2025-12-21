# Fix Preload Script Loading + MIDI Audio

## ROOT CAUSE DISCOVERED (2025-11-27 09:40)

**Critical Issue**: The preload script is NOT loading, which breaks:
- Console capture system (no renderer logs)
- Potentially MIDI initialization
- Any preload-dependent features

**Evidence**:
- `src/main/index.ts:36` looks for `preload.js`
- Build system outputs `preload.mjs` (ES module format)
- No renderer.log file exists
- No [Renderer] logs in main.log
- File mismatch: looking for `preload.js`, actual file is `preload.mjs`

## Fix Plan

### Step 1: Update Preload Path in index.ts

**File**: `src/main/index.ts`
**Line**: 36

Change:
```typescript
preload: path.join(__dirname, 'preload.js'),
```

To:
```typescript
preload: path.join(__dirname, 'preload.mjs'),
```

### Step 2: Verify Console Capture Works

After fixing, restart the app and check:
1. Does `renderer.log` file get created in logs folder?
2. Do we see `[Preload] Console capture initialized` message?
3. Do MIDI events appear in the log?

### Step 3: Re-test MIDI Audio (Previous Fix)

Once preload loads correctly, the MIDI audio fix we already implemented should work:
- getCurrentNote() now handles gaps (✅ already implemented)
- Diagnostic logging added (✅ already implemented)
- Console capture will now work (🔧 fixing now)

## Expected Outcome

Once preload.mjs loads correctly:
- Console capture will start working
- All console.log/debug/info/warn/error will write to renderer.log
- We'll see MIDI events in the logs
- MIDI keyboard audio should work (our previous fix will take effect)

## Critical Files

- **src/main/index.ts** - Fix preload path (line 36)
- **src/main/preload.ts** - Console capture code (already correct)
- **src/App.tsx** - MIDI handling with getCurrentNote fix (already correct)

## Success Criteria

✅ Preload script loads (renderer.log file created)
✅ Console output captured to logs
✅ MIDI events visible in logs
✅ MIDI keyboard produces audio

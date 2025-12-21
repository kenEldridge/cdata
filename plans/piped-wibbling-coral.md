# Fix Audio Engine Crashing on Note Playback

## Problem Summary
MIDI keyboard IS connected and events ARE being received (✅ solved), but no sound plays because the audio engine crashes with:
```
Uncaught Error: Cannot set properties of undefined (setting 'value')
```

## What's Working ✅
- MIDI device connects via native `midi` package in main process
- IPC bridge forwards events to renderer
- Events are received: logs show "Note ON", "[MIDI] Note mapping", "Key mapped"
- Song loads, UI renders, reference melody starts

## What's Failing ❌
- `AudioEngine.playNote()` crashes trying to access `sampler.detune.value`
- Tone.js Sampler doesn't have `detune` property like oscillator-based Synth
- Error prevents any user-played notes from producing sound

## Root Cause
In `src/components/AudioEngine.ts`:
```typescript
this.sampler.detune.value = 0;  // FAILS - Sampler has no detune
```

Tone.Sampler doesn't expose a `detune` Signal. It plays pre-recorded samples, so pitch shifting requires a separate effect node.

## Solution: Use Tone.PitchShift for Detuning

Replace direct `sampler.detune` access with a `Tone.PitchShift` effect in the signal chain.

## Audio Signal Chain (New)
```
Sampler → PitchShift → Filter (LowPass) → Destination
            ↑             ↑
         detuning      timbre
```

## Files to Modify

### `src/components/AudioEngine.ts`

## Implementation Steps

### Step 1: Add PitchShift to signal chain
```typescript
// Add new property
private pitchShift: Tone.PitchShift | null = null;

// In initialize(), create chain:
this.pitchShift = new Tone.PitchShift({
  pitch: 0,        // No shift initially (in semitones)
  windowSize: 0.1, // Balance between quality and latency
  delayTime: 0,
});

// Connect: Sampler → PitchShift → Filter → Destination
this.sampler.connect(this.pitchShift);
this.pitchShift.connect(this.filter);
// (filter already connects to destination)
```

### Step 2: Update applyDetuning to use PitchShift
```typescript
private applyDetuning(accuracy: number): void {
  if (!this.pitchShift || !this.config.audioFeedback.detuning.enabled) {
    if (this.pitchShift) this.pitchShift.pitch = 0;
    return;
  }

  if (accuracy >= 0.999) {
    this.pitchShift.pitch = 0;
    return;
  }

  const { maxCents, weight } = this.config.audioFeedback.detuning;
  const detuningAmount = this.calculateDegradation(accuracy, weight);
  const cents = detuningAmount * maxCents;
  const direction = Math.random() > 0.5 ? 1 : -1;

  // Convert cents to semitones (100 cents = 1 semitone)
  this.pitchShift.pitch = (cents * direction) / 100;
}
```

### Step 3: Update logging
```typescript
detuningCents: this.pitchShift ? (this.pitchShift.pitch * 100).toFixed(1) : 'N/A',
```

### Step 4: Update dispose
```typescript
if (this.pitchShift) {
  this.pitchShift.dispose();
  this.pitchShift = null;
}
```

### Step 5: Restart app and test
Full restart needed to pick up new code.

## Notes
- PitchShift uses FFT-based processing, may add ~10ms latency
- `windowSize: 0.1` is a good balance for piano (not too artifacty)
- Pitch is in semitones, so divide cents by 100

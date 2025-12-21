# Enable Melody Playback with Different Instrument

## The Real Problem
User can't hear the melody - the app only plays accompaniment (chords).

Previous attempt to play melody with same piano caused phasing when user played along.

## Solution: Melody on Different Instrument

Play melody on a **celeste/music box** sound instead of piano:
- Won't clash with user's piano (different timbre = no phasing)
- Sounds like a "guide track" rather than doubled melody
- Still ducks when user plays

## Implementation

### 1. Modify ReferenceMelody.ts
Replace Tone.Sampler (Salamander piano) with a different instrument.

Options using Tone.js built-in synths:
- **Tone.MetalSynth** - Bell-like tones
- **Tone.Synth** with soft settings - Simple sine/triangle waves
- **Tone.FMSynth** - Can create celeste/vibraphone sounds

Or use smplr's other instruments (already have smplr installed):
- `Marimba`
- `Vibraphone`

### 2. Simple approach: Use Tone.Synth with soft triangle wave
```typescript
// Replace Sampler with simple synth
this.synth = new Tone.PolySynth(Tone.Synth, {
  oscillator: { type: 'triangle' },
  envelope: {
    attack: 0.02,
    decay: 0.3,
    sustain: 0.2,
    release: 0.8
  },
  volume: -6
}).toDestination();
```

This creates a soft, bell-like tone that won't clash with piano.

### 3. Enable in App.tsx
- Import and initialize ReferenceMelodyPlayer
- Wire up alongside AccompanimentPlayer
- Add ducking on user note events

## Files to Modify
1. `src/components/ReferenceMelody.ts` - Change from Sampler to Synth
2. `src/App.tsx` - Enable melody player

## Why This Works
- Different timbre = no phasing/interference
- User hears melody clearly as guide
- Piano (user) + Bells (guide) + Chords (accompaniment) = full musical experience
- Ducking still helps when user is actively playing

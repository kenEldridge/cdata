# Music Learning App - Adaptive Key Mapping Approach

## Core Concept
Revolutionary piano learning app that ALWAYS lets you play the melody, but gradually guides you to the correct keys through audio feedback.

## How It Works

### Phase 1: Complete Freedom (Beginning)
- **ANY key on the keyboard plays the melody**
- Distribution is spread across all 88 keys
- As long as you hit keys at the right tempo, you're playing the song
- User experiences immediate success - they're playing Canon in D from minute 1!

### Phase 2: Gentle Guidance (Progressive)
- As user plays, app tracks which keys they use
- Gradually tighten the probability distribution around CORRECT keys
- Wrong keys still play the melody BUT:
  - Sound starts to degrade (slightly off-tune, different timbre, something subtle)
  - Correct keys sound perfect/clean
  - User is nudged gently toward improvement
- This happens over hours of practice - very gradual

### Phase 3: Mastery (Final)
- Distribution has zeroed in on actual correct keys
- Only the right keys sound good
- Wrong keys sound noticeably bad
- User is now playing the actual song correctly

## Key Principles
1. **Never lose the melody** - user is ALWAYS playing the song, just with varying quality
2. **Gradual progression** - might take 2-3+ hours to fully tighten
3. **Audio feedback** - sound quality indicates accuracy (not visual cues initially)
4. **Tempo matters** - must maintain rhythm throughout
5. **Automatic adaptation** - app intelligently adjusts difficulty based on user performance

## Technical Implementation Needs

### 1. MIDI Input Processing
- Capture any key press from MIDI keyboard
- Track timing/tempo
- Map pressed key to melody note based on current distribution

### 2. Probability Distribution System
- Start: uniform distribution across all keys → melody notes
- Middle: gaussian/bell curve centered on correct keys, width decreases over time
- End: delta function at correct keys only

### 3. Audio Feedback Mechanism
- **Instrument**: Piano tone (using Tone.js PolySynth or sampler)
- Correct key: clean piano sound
- Slightly wrong: subtle detuning (±5-10 cents)
- More wrong: more detuning + timbre change
- Very wrong: obvious degradation
- Need smooth interpolation based on "distance" from correct key

### 3a. Reference Melody Track (Adaptive)
- **Background melody plays along** to help learner hear the song
- Starts at moderate volume for beginners
- **Gradually fades out** as user improves/learns the melody
- Can be manually controlled (volume slider)
- Different timbre from user's piano (maybe softer synth or music box sound) to distinguish

### 4. Progression Tracking
- Monitor user accuracy over time
- Calculate metrics: average key distance from correct, consistency, improvement rate
- Automatically tighten distribution when thresholds met
- Persist progress (localStorage or file)

### 5. Song Data (Canon in D)
- Melody note sequence with timing
- Correct key mapping for each note
- Tempo information
- Need MIDI file OR manual encoding

### 6. UI Elements - GUITAR HERO STYLE VISUAL
- **Falling notes visualization**
  - Notes fall from top of screen toward bottom
  - Show only the range used in the song + small padding (NOT all 88 keys)
  - Visual indicator of which note is coming
  - Color coding for different notes
  - Hit zone at bottom where notes should be played

- **Distribution Visualization (SUBTLE)**
  - Show the "acceptable key range" visually
  - **Option A**: Falling notes have width/glow that represents distribution
    - Wide distribution = wider note block or larger glow
    - Narrow distribution = thinner, more precise indicator
  - **Option B**: Keys at bottom have highlight/glow showing acceptable range
    - Gradient from correct key (bright) to edge of distribution (dim)
  - **Option C**: Both - falling note shows target, bottom shows acceptance zone
  - Gives visual feedback on how tight the learning has become

- **Visual keyboard at bottom**
  - Shows only the keys in the song's range (NOT all 88)
  - Visual feedback when keys are pressed
  - Highlights which key the falling note will land on
  - Could show distribution as described above
- **Additional UI:**
  - Current "accuracy zone" width indicator
  - Progress/score display
  - Practice controls: start/stop, reset progress, tempo adjustment
  - Real-time tuning controls for audio feedback parameters

## Song Library - PUBLIC DOMAIN

### Initial Songs to Include:
1. **Canon in D** (Pachelbel) - the main teaching song
2. **Für Elise** (Beethoven) - popular, recognizable
3. **Ode to Joy** (Beethoven) - simple melody
4. **Twinkle Twinkle Little Star** (Traditional) - beginner friendly
5. **Amazing Grace** (Traditional hymn)
6. **Greensleeves** (Traditional English)
7. **Bach Minuet in G**
8. **Mozart - Eine Kleine Nachtmusik** (simplified melody)

### Sources for Public Domain MIDI:
- **Primary**: Search and download from public domain collections
  - MuseScore public domain library
  - BitMIDI (filter for public domain)
  - ClassicalArchives
  - IMSLP (International Music Score Library Project)
- **Backup**: Generate from sheet music if needed
- User does NOT have MIDI files - need to acquire them

### Implementation Approach:
1. Search web for "Canon in D MIDI public domain"
2. Download and parse MIDI file
3. Extract melody line (typically track 1 or highest voice)
4. Convert to internal JSON format for the app
5. Repeat for other songs in library

### Format:
- Parse MIDI to extract: note number, timing, duration
- Store as JSON: `{notes: [{midi: 60, time: 0, duration: 0.5}, ...], tempo: 120}`
- Keep original MIDI for reference melody track playback

## Files to Create/Modify
- `src/App.tsx` - Main app, replace validation UI
- `src/components/AdaptiveKeyMapper.ts` - Core distribution logic
- `src/components/AudioEngine.ts` - Sound synthesis with quality feedback
- `src/components/ProgressTracker.ts` - User progress monitoring
- `src/data/canon-in-d.ts` - Song data
- `src/utils/midi-mapper.ts` - MIDI to melody note mapping

## Technical Challenges
1. **Smooth audio degradation** - how to make wrong notes sound "worse" without being jarring
2. **Distribution math** - proper probability functions that feel natural
3. **Progress pacing** - not too fast, not too slow
4. **Tempo tracking** - need to follow user's timing, not force a metronome

## Design Decisions

### Audio Feedback Approach
**IMPLEMENT ALL OPTIONS WITH TUNABLE PARAMETERS**
- Detuning amount (cents off-pitch)
- Timbre shift (filter cutoff, harmonics)
- Volume reduction
- Combination weight of each

**Reasoning:** We don't know what works best yet. Need to iterate and experiment together. Build all controls so we can tune in real-time.

### Other Decisions
- Chords: Start with single notes only
- Sheet music: Audio-only initially, add visual later if needed
- Practice mode: YES - manual controls for distribution width, feedback intensity
- **Expect iteration** - this is v1, will refine based on actual use

### Gameplay Mechanics
- **Song playback**: Continuous, NO WAITING - melody plays in real-time
- User must keep up with tempo
- Missing a note doesn't stop the song (melody continues)
- Like Guitar Hero - constant forward motion

### Progression System
- **BOTH automatic AND manual control**
- **Automatic mode**: Monitors accuracy, gradually tightens distribution based on performance
- **Manual override**: Slider/controls to manually adjust distribution width
- Can switch between modes or use manual to fine-tune automatic
- Saves progress between sessions

## Success Criteria
- User can play Canon in D melody from day 1 (any keys)
- Over 2-3 hours of practice, naturally gravitates to correct keys
- Audio feedback is clear but not punishing
- System adapts smoothly to user skill level

---

## CRITICAL NOTE
This is a UNIQUE approach - not like Synthesia or traditional learning tools. The innovation is:
- **No wrong notes** (initially)
- **Audio quality as teaching tool** (not visual cues)
- **Gradual adaptation** (not pass/fail)
- **Always playable** (never frustrating)

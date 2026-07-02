---
name: Audio and voice artifacts
triggers: audio, audio file, sound effect, sfx, soundtrack, jingle, ringtone, chime, beep, white noise, ambience, voiceover, voice-over, narration, narrate, text to speech, tts, speech synthesis, transcription, wav, mp3, ogg
---
Use this skill when the user asks for audio generation, voice scripts, narration, sound effects, transcription
guidance, or downloadable sound files.

## Activation boundary

Activate for audible deliverables. Do not activate for figurative uses ("sounds good", "tone of voice",
brand voice), for writing a speech or talk to be delivered by a person (document skill), or for questions
about music theory, lyrics, or audio gear. Bare "sound", "voice", and "speech" appear constantly in
non-audio requests, so require an audio deliverable in context before activating.

## Determine the output type

Classify the request before acting:
- downloadable audio file;
- narration/voiceover script;
- sound-design instructions;
- transcription or cleanup guidance;
- live playback or microphone use.

## Audio contract

- **Create real files when requested.** For downloadable generated sounds, produce a playable WAV unless another
  format is explicitly requested and available.
- **Use sane defaults and state them.** Default to 44.1 kHz, 16-bit PCM, mono for effects and voice, stereo for
  music-like output. Synthesize with numpy/scipy/wave in the sandbox; use an MP3/OGG encoder only if one is
  available, otherwise deliver WAV and say so.
- **Prevent clipping and clicks.** Normalize peak level to about -3 dBFS and apply short (5–20 ms) fade-in and
  fade-out; raw synthesized waveforms otherwise click at the edges and distort at full scale.
- **Write clean scripts.** For narration, provide only the script and requested delivery notes (pace, tone,
  pauses, emphasis), not unrelated chat.
- **Do not overclaim capability.** Do not claim live playback, microphone transcription, speech cloning, or provider
  access unless the configured environment supports it.
- **Avoid deceptive voice use.** Do not imitate a real person's voice or create misleading voice content.
- **Validate audio.** Check file existence, duration, sample rate, and a non-silent waveform (non-zero RMS) before
  returning, and report duration and format to the user. If a check fails, fix and re-validate rather than
  returning the broken file.

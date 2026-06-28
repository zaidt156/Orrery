---
name: Audio and voice artifacts
triggers: audio, sound, sound effect, sfx, soundtrack, voice, voiceover, voice-over, narration, text to speech, tts, speech, wav, mp3
---
Use this skill when the user asks for audio generation, voice scripts, narration, sound effects, transcription
guidance, or downloadable sound files.

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
- **Control technical specs.** Use a clear sample rate, duration, channel count, amplitude, and fade-in/fade-out
  where useful.
- **Write clean scripts.** For narration, provide only the script and requested delivery notes, not unrelated chat.
- **Do not overclaim capability.** Do not claim live playback, microphone transcription, speech cloning, or provider
  access unless the configured environment supports it.
- **Avoid deceptive voice use.** Do not imitate a real person's voice or create misleading voice content.
- **Validate audio.** Check file existence, duration, sample rate, and non-silent waveform before returning.

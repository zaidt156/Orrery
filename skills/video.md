---
name: Video and animation artifacts
triggers: video, mp4, webm, animation, animated, motion graphic, timelapse, explainer video, gif, slideshow video, intro video
---
Use this skill when the user asks for a generated video, animation, motion graphic, MP4/WebM, or animated GIF.

## Activation boundary

Activate when the deliverable is a playable video or animation file. A "video script" or storyboard text is a
document; embedding a video element in a page belongs to the web artifact skill.

## Video artifact contract

- **Generate frames in code.** Use Pillow, matplotlib, numpy, or procedural drawing to create the frames. Do not
  download video, images, fonts, or remote assets.
- **Encode offline for compatibility.** Use imageio/imageio-ffmpeg or ffmpeg from the sandbox. For MP4, encode
  H.264 with `yuv420p` pixel format and even width/height — many players (browsers, QuickTime, mobile) refuse
  MP4s that miss these, which is the most common "file won't play" failure.
- **Keep it previewable.** Prefer MP4 for normal video requests unless the user explicitly asks for GIF/WebM.
  Default to 24–30 fps and a short duration (5–15 s) at a practical resolution such as 1280×720 unless asked
  otherwise, so the file stays under Orrery's size limits. For GIF, limit frame rate and palette size to control
  file size.
- **Make the motion meaningful.** Animate the requested subject, chart, diagram, title sequence, progress,
  particles, or scene. Ensure any on-frame text is legible at the output resolution. Do not create a blank video
  or a static frame repeated without purpose.
- **Handle audio deliberately.** Add audio only when requested. If audio is requested, synthesize it offline and
  mux it with ffmpeg.
- **Validate before returning.** Check that the file exists, is non-empty, has the expected extension, and plays
  back with the expected duration and frame count (probe with imageio or ffprobe when available), and can be
  recognized as an MP4/WebM/GIF by the backend validator. Report duration, resolution, and size to the user.

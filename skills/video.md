---
name: Video and animation artifacts
triggers: video, mp4, webm, animation, animated, motion graphic, timelapse, explainer video, gif
---
Use this skill when the user asks for a generated video, animation, motion graphic, MP4/WebM, or animated GIF.

## Video artifact contract

- **Generate frames in code.** Use Pillow, matplotlib, numpy, or procedural drawing to create the frames. Do not
  download video, images, fonts, or remote assets.
- **Encode offline.** Use imageio/imageio-ffmpeg or ffmpeg from the sandbox to write MP4/WebM/GIF files.
- **Keep it previewable.** Prefer MP4 for normal video requests unless the user explicitly asks for GIF/WebM.
  Use a practical resolution and duration so the file stays under Orrery's size limits.
- **Make the motion meaningful.** Animate the requested subject, chart, diagram, title sequence, progress,
  particles, or scene. Do not create a blank video or static frame repeated without purpose.
- **Handle audio deliberately.** Add audio only when requested. If audio is requested, synthesize it offline and
  mux it with ffmpeg.
- **Validate before returning.** Check that the file exists, is non-empty, has the expected extension, and can be
  recognized as an MP4/WebM/GIF by the backend validator.

---
name: video-frame-timing
description: Use when timing a video or screen recording frame by frame.
category: visual-analysis
---

# Video frame timing

Never estimate an animation's duration by eye from a video. Extract frames at the recording's native rate, crop to the element, and read a contact sheet. Report every event as an offset from the input event (touch down = 0 ms) with its frame number.

## Procedure

1. Check the frame rate with `ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "FILE"`. One frame lasts 1000 / fps ms. If ffprobe is missing, say so and ask for the rate.
2. Coarse pass: extract about 10 fps across the suspect range. Read the sheet and note when the change first appears.
3. Fine pass: extract every native frame in a window of about 0.5 s around that point. Crop to the cell or element, scale it up, and tile the frames into one contact sheet with PIL (run Python with `-I`). Read the PNG.
4. Report onset as the earliest frame where the change is visible at all, even if faint. A scale-in or alpha-in starts too small to see for several frames.
5. Mapping: the image viewer may downscale and print a factor such as "Multiply coordinates by 1.17". Apply that factor to any coordinate read off the displayed image before cropping.
6. Comparing two recordings (ours versus a reference): use the same frame rate and method on both. State both offsets side by side. Film our build too. A value computed from the tween is not a measurement of the screen.
7. Compare at fixed checkpoints after the first visible frame, for example 33, 66, 116 and 150 ms, and the end. Report the share of the final shape at each checkpoint. Quote offsets as ±1 frame (about 16 ms at 61 fps).
8. Do not say a build matches a reference until both measured tables sit side by side. Before that, write "closer" or "not yet matched". A teardown or analysis doc can be wrong. When a frame contradicts a doc, say so and offer to correct the doc.

## Capture guidance for the user

Give these steps when the user records the device:

- On Android, enable Developer options, then "Show taps", so the touch point shows in the frame.
- Record at the highest frame rate offered, 60 fps if available.
- Record a fast double tap, a slow double tap, a double tap on a filled cell, and a single tap followed by a one-second wait.
- Hold still about one second after each gesture, so the animation finishes before the next one starts.

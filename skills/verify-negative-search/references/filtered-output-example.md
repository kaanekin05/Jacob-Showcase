# Filtered output markers from rtk

A find run through the rtk proxy returned this shape. The hits were hidden, so a zero-hit reading would have been wrong:

```
... (20 filtered)
[see remaining: tail -n +1 "$HOME/Library/Application Support/rtk/tee/<id>_find-hidden.log"]
---siblings---
... (38 filtered)
[see remaining: tail -n +1 "$HOME/Library/Application Support/rtk/tee/<id>_find-hidden.log"]
```

Read the tee log with `tail -n +1 <path>`, or rerun the command under `rtk proxy` to get unfiltered output before you conclude that nothing matched.

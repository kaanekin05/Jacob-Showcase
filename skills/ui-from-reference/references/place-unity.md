# Placing and verifying in Unity

Read at Phase 3. Covers anchoring, the match-mode arithmetic, headless prefab editing and the render
harness that closes the gate.

## 1. What the CanvasScaler costs you

`Scale With Screen Size` with `Match Width Or Height` resolves as:

```
scale        = (screenW / refW)^(1 - m) * (screenH / refH)^m
logicalW     = screenW / scale
logicalH     = screenH / scale
```

`m` is `m_MatchWidthOrHeight`. **0 matches width, 1 matches height.** Anything between loses room on
one axis relative to the reference.

Work the number for the widest and narrowest targets you support before placing. One real case, a
reference of 1170 × 2532 at `m = 0.8` on a 1536 × 2048 tablet:

```
scale    = (1536/1170)^0.2 * (2048/2532)^0.8 = 0.891
logical  = 1723.8 x 2298.5
```

That is 554 units **gained** horizontally and 233 units **lost** vertically. A layout pinned at fixed
offsets from the centre clips whatever sits nearest the bottom.

**Do not retune the scaler to fix one screen.** It is usually shared across the project and often
across sibling projects.

## 2. Anchor to edges

Edge anchoring is what makes the loss above land in empty space rather than on a control.

| Element | anchorMin / anchorMax | pivot |
|---|---|---|
| Top bar | (0,1)-(1,1) | (0.5, 1) |
| Bottom bar | (0,0)-(1,0) | (0.5, 0) |
| Top-left control | (0,1) | (0, 1) |
| Top-right control | (1,1) | (1, 1) |
| Genuinely centred content | (0.5, …) | (0.5, …) |
| Full-screen background | (0,0)-(1,1) | — |

Band heights do not matter when every child anchors to a band edge. Raise a band rather than
re-parent a child that needs to reach further.

**A conditional element anchors to an edge, never into a centred row.** A badge that appears on some
levels and not others must not move the row it joins. Anchor it to the nearest screen edge at the
row's height.

**Decorative scatter takes fractional anchors.** Set `anchorMin = anchorMax` to the element's
fractional position so the scatter spreads with the screen instead of clustering.

## 3. Safe area

Check whether a parent already applies `Screen.safeArea` before insetting anything. If it does, the
panel stretches corner to corner and adds nothing of its own.

Two things that surprise people:

- **Designers draw into the status bar.** A mock's top margin is smaller than a notch inset, so
  applying it inside an already-inset rect gives a sensible small margin rather than a double pad.
- **A safe-area component may also subtract a banner ad's height.** If so, the bottom of the panel is
  not the bottom of the screen, and a bottom margin is a minimum rather than the actual gap.

## 4. Editing the prefab headlessly

No scene, no Canvas, no layout pass — the authored values save exactly as written.

```csharp
var root = PrefabUtility.LoadPrefabContents(path);
try
{
    // find by name, set anchors / pivot / anchoredPosition / sizeDelta
    PrefabUtility.SaveAsPrefabAsset(root, path);
}
finally { PrefabUtility.UnloadPrefabContents(root); }
```

Verify by **re-loading the saved asset**, not by trusting the in-memory copy.

### Traps

- **A right-to-left TextMeshPro's `text` setter regenerates the mesh and throws with no canvas.**
  Write `m_text` through `SerializedObject` instead. The same applies to font size, colour and
  material on those components.
- **Every `CFText`-style wrapper has two children**, a normal and a right-to-left variant. Both must
  carry the same material and size. Mismatches hide well.
- **`Object.Instantiate` inside `LoadPrefabContents` makes a plain copy**, not a nested prefab
  instance. It will not inherit later changes to its source.
- **A serialized field added to an existing component is not written to the prefab YAML** until the
  prefab is next saved. It loads from the field initialiser meanwhile, which is correct but implicit.
- **Reparenting keeps a reference alive** when the reference points at the component, so moving a
  text node into a new wrapper does not break its binding.

### Look at every Image, not the first

`GetComponentInChildren<Image>` returns a decoy often enough to matter. One card had an Image at
alpha 0 on its own node while the visible art sat on a child inside a nested prefab. Enumerate:

```csharp
foreach (var im in node.GetComponentsInChildren<Image>(true))
    Debug.Log($"{im.name} sprite={im.sprite?.name} colour={(Color32)im.color} type={im.type}");
```

Placeholder sprites inherited from another screen are common. Confirm each one against the reference.

## 5. The render harness — the gate

Render through the project's real scaler configuration, read the pixels, measure.

```csharp
var cam = /* orthographic, SolidColor, background = the screen's own backdrop */;
var canvas = /* ScreenSpaceCamera, worldCamera = cam */;
var scaler = /* copy referenceResolution, screenMatchMode, matchWidthOrHeight from the project */;
var panel  = (GameObject)PrefabUtility.InstantiatePrefab(prefab, canvas.transform);
/* stretch the panel to the canvas: anchorMin 0, anchorMax 1, offsets 0 */

var rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32) { antiAliasing = 2 };
cam.targetTexture = rt;
Canvas.ForceUpdateCanvases();
cam.Render();
RenderTexture.active = rt;
tex.ReadPixels(new Rect(0, 0, W, H), 0, 0);
tex.Apply();
/* finally: cam.targetTexture = null before releasing the RenderTexture */
```

Render at `W, H` equal to the reference resolution when you want pixels to equal units. Use a
smaller multiple when you only need to look.

`RectTransformUtility.WorldToScreenPoint` plus `GetWorldCorners` gives an element's exact crop box.
Use it rather than guessing a crop; a guessed crop measures the wrong thing and reads as a pass.

### What to do with the render

- **Measure, do not admire.** Compute a number per element you moved and compare it.
- **Isolate by colour** when an element sits on a busy background — a red icon on a white pill is
  separable by channel, and a centroid of those pixels is the position.
- **Freeze a frame to check an animation.** DOTween does **not** tick in the editor, so set the
  transform to each key pose by hand and render a filmstrip. This verifies poses only. Say so:
  timing and easing remain unverified until someone watches it.
- **Render both states of a swap** and measure the drift between them.

## 6. Reuse the material palette

Before setting a colour, look for a role material and a screen already using it.

An exact match between a mock's stated colour and an existing material's **outline** colour means
the mock was drawn from that system. Adopt the role.

The common convention is a shared material carrying the outline and shadow, with the face tinted per
instance by the TMP vertex colour. Copy the pairing from the screen that already does it.

**Widening an outline widens its shadow**, because the underlay is cast from the fattened silhouette.
Bring `_UnderlayDilate` down when you raise `_OutlineWidth`, or a crisp edge becomes a halo.

Editing a shared role is allowed. Check every referencing asset first, change the locale-paired twin
with it, and report that a shared asset moved.

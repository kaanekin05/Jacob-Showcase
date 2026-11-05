# Importing Figma exports into Unity

Read before choosing an export scale, a pixels-per-unit value, an atlas, a nine-slice border or a
text outline width. Getting the pixels out of Figma is `extract-figma.md`. Sizing a rect is
`measure.md`. This file covers what happens after the PNG lands in the project.

Every rule here comes from one puzzle-game project, between 2026-09-17 and 2026-10-03. Numbers from
that project appear only as labelled examples. Never copy one into another game.

## How to read the status on each rule

Each rule ends with one of three labels.

- **Confirmed.** The record holds the cause and a measurement that showed the fix working.
- **Stated.** The record states the rule and its reason. It holds no measurement.
- **Observed.** A value was found by trial and it held. Nobody recorded why. Treat it as a starting
  point and measure again.

Where two records disagree, the rule says so and names the newer one.

## 1. Export scale and pixels per unit

Pixels per unit (PPU) is the number of texture pixels that cover one Unity unit.

**Multiply the PPU and every nine-slice border by the export multiplier.** Unity stores both in
source pixels. A source exported at `k` times its old size needs `k` times the PPU and `k` times
each border. Otherwise the art draws at the wrong size and the borders cut the wrong region.
Example: a re-export at 3x updated the PNG files and only some of the `.meta` files. Board tiles
then drew at half size with gaps between them, and four borders cut far inside the art.
**Confirmed.**

**The same art at 100 pixels with 100 PPU and at 300 pixels with 300 PPU draws at the same size.**
The second holds nine times the texels. It looks sharper only where the art covers more screen
pixels than the smaller export has. Below that point the extra pixels buy nothing. **Stated.**

**Pick the multiplier per asset, from the largest size the art is drawn at.** Do not export a whole
sheet at one scale.

```
neededPx   = drawnSizeInCanvasUnits * worstDeviceScaleFactor * largestScaleTween
multiplier = neededPx / nodeSizeAt1x        # round up to the next export step
```

Take the scale factor from the formula in `place-unity.md` section 1, on the largest device you
support. Example: a 1170 x 2532 reference at match 0.8 gives 1.26 on a 1440 x 3200 device. In that
project the per-asset choice cut the atlas source pixels from 31.5 to 15.0 megapixels. The source
is a plan. Its tile rows shipped. The record does not show whether the other rows did. **Stated.**

**An oversized texture is a defect when the atlas has no mipmaps.** The reason given is that a
texture squeezed into half its pixel count samples about every other texel, so thin lines shimmer
when the sprite moves. The record holds no measurement of the shimmer. **Stated.**

**Keep a source under the importer's maximum texture size.** Unity resamples a larger one at
import, at a scale that is not a whole number. On a nine-sliced sprite that softens the border
pixels the slicing depends on. Example: a 1740 x 3900 source against a 2048 limit was resampled to
913 x 2048. **Stated.**

**For UI sprites, set PPU to 100 times the multiplier.** A `RectTransform` sets the drawn size of a
UI sprite, so PPU does not change that size. PPU still decides how thick a nine-slice border draws
and what `Set Native Size` produces. **Stated.**

**For world-space sprites, PPU is the geometry.** Sprites that swap into one renderer must draw at
the same world size. Give each the PPU that produces that size from its own pixel count. Example:
four faces of one game piece carried 375 and 100, so three of them would have drawn 3.75 times the
size of the fourth. **Confirmed** by reading the importer values. No render of the swap is
recorded.

### Art that must tile without seams

This covers a lattice of world-space sprites that must meet edge to edge.

**The PPU that closes the seams is a measured window, not the exact-fit number.** At the exact fit
a thin dark seam showed between neighbours. The record does not say what caused the seam. A lower
PPU enlarges each sprite so the neighbours overlap. Too low, and one sprite covers the detail on
the next. **Confirmed** for the window. The seam itself is **Observed**.

**Measure the corners, not only the flat edges.** Rounded corners pull apart before the flat edges
do. Example: a hex tile measured clean across its flat edges and still showed the background as a
pinhole where three tips met. **Confirmed.**

**Measure with the real sprites.** Render a lattice of the atlas-compressed sprites over a magenta
clear colour and count the background pixels inside the tiles. Check every kind of corner. Part of
the usable window comes from the soft edge of the sprite, so a re-export can close it. Re-measure
after every re-export of that art. **Confirmed.**

**Layers of one tile share one PPU.** A fill and its separate outline ring keep their fit only
while both scale together. Splitting the two opens a hairline inside each tile. **Confirmed.**

**The records disagree on the fix when the art and the lattice do not fit.** The 2026-10-02 records
lowered the PPU, which widened the line between tiles by about a tenth. The 2026-10-03 record is
newer. It restored the higher PPU and edited the outline PNG by hand so its tips reach the corner.
That keeps the line width. It also lives only in the PNG, so a fresh export from the artist removes
it. If you edit exported art by hand, say so where the next person re-importing it will look.
Asking the artist to change the source art was named as the proper fix. The record does not show it
happening.

## 2. Transparent padding

`measure.md` section 1 owns this, and `scripts/sprite_bounds.py` does the arithmetic. Do not
re-derive it here. Three points connect it to importing.

**An uneven edge on an export can be the design.** A drop shadow pads one side more than the
others. Example: a close button padded 7 pixels on top and 10 below was chased as a compression
artefact. It was the shadow drawn in Figma. Check the padding numbers before blaming the pipeline.
**Confirmed.**

**Pass `--sliced` for a nine-sliced sprite whose padding sits inside its border.** The padding
there stays constant, so the script adds the padding to the design size and does not scale it.
Example: the scaling formula on a sliced button gave a rect 3% too large. The gap between buttons
came out at 79.1 units against a design of 88.0. Only a render caught it. **Confirmed.**

**Re-measure the padding after every re-export.** The script counts padding in sprite pixels, so
the numbers move with the export scale. This rule follows from that arithmetic. The record holds no
worked example of a rect corrected across a scale change.

## 3. Dirty or bleeding edges

**First composite the source PNG over a flat colour.** A clean source means Unity added the dirt
and the export is not at fault. In that project, earlier sessions blamed the Figma drop shadows, a
sharpened export and the atlas padding. The record calls each one only part of the story.
**Confirmed.**

**The confirmed cause was double compression.** Each source texture imported with its own platform
compression. The sprite atlas then packed from that compressed import and compressed the page
again. The evidence is a comparison. The packed result matched "compress, then compress again"
far better than it matched a single pass of either format. **Confirmed.**

**The fix that held: every sprite in an atlas imports Uncompressed.** The atlas is then the only
compression step. A new sprite added later must follow the same rule, or the dirt returns for that
sprite alone. **Confirmed.**

**The records disagree on the block size.** In September the atlases went to a finer ASTC block as
part of the fix. A plan dated 2026-10-01 still describes that state. The 2026-10-02 record is
newer. It moved every atlas back to the coarser block, because the earlier rejection of that block
was really a rejection of double compression. Example: the coarser block cost 2.5 to 3 times the
edge error of the finer one. Atlas memory went from 42.5 MB to 19.2 MB in the same pass. Choose the
block by measuring, and look at the sharpest-edged art first. In that project it was the buttons.

**Measure the error against the source.** Compare the alpha of the antialiased edge pixels in the
packed sprite with the same pixels in the source PNG. When the sprite uses a Tight mesh, offset the
source read by `Sprite.textureRectOffset`. Without that offset the comparison is meaningless.
**Confirmed.**

**A tiny sprite stretched large shows a soft ramp at its edges.** Bilinear sampling at the edge of
the quad blends the outer half texel with the transparent padding of the atlas. Half a texel is a
fixed share of the sprite, whatever size it is drawn at. Example: a 4 x 4 square stretched over the
screen ramped across 12.5% of its width on each side. The fix that held was to draw the quad larger
so the ramp falls off screen. Point filtering was rejected, because the atlas page owns the filter
mode and the source texture does not. **Confirmed** at three aspect ratios.

A flat backdrop baked behind an export is a different fault. See the export paths in
`extract-figma.md`.

## 4. Sprite atlases

**Keep a texture that a material samples out of every atlas-packed folder.** A material samples the
original texture and not the atlas page. The record says such a texture is probably in the build
twice. Nobody checked a build. **Stated.**

**A mesh built from several sprites binds one texture.** A piece that sits on another atlas page
does not fail. It draws with the texture coordinates of some other sprite. So a kit drawn as one
mesh belongs on one page, and that is what brings it down to one draw call. **Confirmed.**

**Never let the code assume the one page.** The records disagree here, and the newer one changes
the fix.

- The 2026-09-28 record found all pieces on one page while the one-page check still failed. A
  sprite reports its own source texture until its atlas is bound. The fix then was a serialized
  reference to the atlas on the asset that owns the kit. That record marks the fix as not verified
  after a restart.
- The 2026-10-02 records are newer. They measured the reference loading the atlas without binding
  it. `SpriteAtlas.GetSprite` and `SpriteAtlasUtility.PackAllAtlases` did not bind the atlas
  either. In Editor Play mode with Addressables Fast Mode, no sprite in the project was bound.
- The fix in place now groups the sprites by `texture` and bakes one submesh per texture. A bound
  atlas collapses that to one draw call. An unbound atlas costs one draw call per texture and still
  draws the art. The 2026-09-28 record had rejected exactly this option.

So pack the kit on one page for the draw call, and keep the per-texture path for correctness. The
records say a player build binds its atlases at startup. No device capture is recorded.

**When a one-page check fails, read `sprite.packed` before repacking.** A value of `False` with a
texture named after the PNG means the atlas is unbound and the art is fine. Example: the error
"Pack the whole corner kit onto one page" was pasted into four sessions while every piece was
already on one page. **Confirmed.**

**Build a merged mesh from `sprite.vertices`, `sprite.uv` and `sprite.triangles`.** A quad plus the
sprite's rect is correct only while the atlas keeps rotation and tight packing off. The sprite's
own mesh already carries the pivot, the PPU, the packing and the rotation. That atlas had both
options off, so the quad was never seen failing. **Stated.**

**Never read draw calls or atlas savings from the Editor in Fast Mode.** Nothing is bound there, so
the reading is not the build's. **Confirmed.**

Compression belongs to the atlas alone. See section 3.

The record holds no rule for which sprites to group into which atlas. It notes only that each
atlas carries its own compression setting, so one atlas can take a finer block than the rest.

## 5. Nine-slice borders and mesh type

`measure.md` section 3 owns how to compute a border. These rules cover the import settings.

**Set Mesh Type to Full Rect on every sprite that carries a border.** With a Tight mesh a sliced
`Image` squashes its caps by the amount of trimmed padding. Unity logs nothing and the Inspector
shows nothing. Example: two headers shared one role and one border. The Tight one drew 42 pixels
narrower and 34 shorter than the Full Rect one. **Confirmed** by that measurement.

The record gives this mechanism. Tight packing trims the transparent pixels, so
`Sprite.textureRect` shrinks. `Image` insets the quad by that trim, and still measures the border
lines from the untrimmed rect. The record states it and does not show how it was derived.

**Audit, do not inspect.** Load each `Sprite`. Assert that a non-zero `border` comes with zero
`DataUtility.GetPadding` and exactly four vertices. Run the audit after a re-export too. A sprite
that measures clean today can pick up padding from the next export. **Confirmed.**

**An `Image` set to Sliced on a sprite with a zero border renders as Simple.** Unity does not warn.
Enumerate the sliced Images and check that each sprite has a border. **Stated.**

**Sprites that share a role share a border.** Copy the border across the pair, then check both
after a re-export. **Stated.**

Borders scale with the export multiplier. See section 1.

## 6. A Figma text stroke as a TextMesh Pro outline

None of this was written into the project's notes. It comes from two working sessions on
2026-09-29 and 2026-09-30. The numbers in those sessions were corrected several times. Read every
rule in this section as provisional and verify by render.

**Ask the designer for three values per text style.** The stroke width, the stroke colour, and the
stroke alignment, which is Inside, Center or Outside. The automated design read returned the
colours and left the stroke out. A first pass therefore concluded the text had no stroke.
**Observed** once.

**Do not divide a text stroke by the export scale.** Text is not exported. A stroke width read
from the design frame is in frame points, like every other frame number. Convert it with the canvas
scale from Phase 0. In the session, dividing by the export scale was proposed as the fix for an
outline that came out too thick. The real error was elsewhere. This differs from a stroke measured
on an exported sprite. `extract-figma.md` covers that case under Scale.

**`_OutlineWidth` is not a pixel count.** The ring it draws scales with the rendered font size. It
also depends on the padding and sampling size of the font asset. Three consequences follow.

- Fit the width at the font size the label renders at. The design's font size times the canvas
  scale is the target. Example: one label was set to 100 where the design scaled to 76.9, so it
  alone read 30% heavy.
- Auto-sizing thins the stroke. A long string that shrinks the text shrinks the ring with it.
- One material used at two font sizes cannot match the design at both.

**Stated** from the shader arithmetic in the session.

**TextMesh Pro centres the outline on the glyph edge.** Half the ring sits outside the edge and
half eats into the face. That matches a Figma stroke set to Center. For an Outside stroke, raise
`_FaceDilate` to about the value of `_OutlineWidth`, so the whole ring sits outside and the face
keeps its thickness. For an Inside stroke, use about the negative of that value. The session
applied the Outside setting to one material. It checked the result by reading the values back
through the shader arithmetic. It records no render measured against the design. **Stated.**

`_FaceDilate` may already be in use. Some projects build font weights from it. Check before adding
a stroke correction on top.

**No conversion constant from stroke points to `_OutlineWidth` is confirmed.** Example: for a
2.15 point stroke the user picked 0.3 by eye. Four explanations followed in two days.

1. Ten times the stroke divided by the font size. This doubled the outline and was withdrawn.
2. A rim of 0.197 em per unit of width, measured from a render.
3. A rim of 0.2137, solved backwards from the accepted 0.3 at an assumed font size of 100.
4. Shader arithmetic. The ring is `_OutlineWidth` times `_ScaleRatioA`, across a span of twice the
   gradient scale in atlas pixels. That gave about 0.32 at font size 100 with `_FaceDilate` equal
   to it. The author noted that the atlas generator was not read to prove the span.

So 0.3 is **Observed**. The fourth explanation lands near it. It rests on an unproven span and on a
label that auto-sizes. Do not reuse any of the four constants.

**Fit each role material by render.** Measure the outline as a percentage of cap height, per
`measure.md` section 4, on the mock and on the render. Adjust and re-render. Read the scale ratios
from the live material, because they change whenever the width or the dilate changes. A value read
from disk can be stale. Example: one title went from 8.5% to 14.8% of cap height against 16.0% on
the mock, inside the mock's measurement noise. The last step between two candidate widths was
chosen by eye. **Confirmed** for the method.

**Every effect shares the font atlas padding.** The outline, the dilate and the underlay must fit
inside it together. A wide outline leaves little room for the shadow. The underlay is cast from
the face alone, so the outline can also cover it. **Stated** from reading the shader. The shadow
that grows with a widened outline is in `place-unity.md` section 6.

## Where each rule came from

So a later reader can check a rule against its record.

| Section | Record |
|---|---|
| 1 | The game repo's `Docs/Texture-Export-Plan.md` of 2026-10-01. The tile window is in the vault page `puzzle-board-rendering-decisions` section 9 and the project memory note `puzzle-tile-ppu-window` of 2026-10-03 |
| 2 | Vault page `puzzle-figma-sprite-padding` sections 1 and 6 |
| 3 | Project memory note `puzzle-atlas-double-compression`. The ramp is in `puzzle-board-rendering-decisions` section 9 |
| 4 | `puzzle-board-rendering-decisions` sections 6 and 8, vault page `sprite-atlas-lazy-binding`, project memory note `puzzle-fast-mode-atlases-unbound` |
| 5 | Project memory note `puzzle-nine-slice-fullrect`, and the stale borders in `Docs/Texture-Export-Plan.md` |
| 6 | Session transcripts of 2026-09-29 and 2026-09-30 only. The cap-height fit is in the game repo's `Docs/Level-HUD-Panel-Plan.md` |

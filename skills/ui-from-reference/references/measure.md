# Measuring a reference and the sprites that fill it

Read when sizing anything. The engine-independent half of the skill.

## 1. The transparent-padding correction

**Every exported sprite carries a margin.** It comes from antialiasing and from baked drop shadows.
Setting a rect to the design number renders the art smaller than designed, and off-centre wherever
the padding is uneven.

**Rule: size the rect so the opaque art lands on the design number. The padding falls outside it.**

```
rectW = designW * spriteW / artW
rectH = designH * spriteH / artH
```

Then shift the rect, because the art is rarely centred in its own sprite:

```
offsetX = (artCentreX - spriteCentreX) * designW / artW     # move the rect the opposite way
offsetY = (artCentreY - spriteCentreY) * designH / artH
```

A bottom-heavy pad is the usual case, because a drop shadow only falls one way. One real example: a
192×192 button sprite whose art was 172×172 with pad L10 R10 T6 B14. The rect became 192/172 larger
and dropped 5.5 units, because the art sat 4 px above the sprite's centre.

`scripts/sprite_bounds.py` does all of this. Run it instead of redoing the arithmetic.

### It behaves differently per Image type

| Image type | Padding behaviour |
|---|---|
| Sliced, pad inside the fixed corner caps | **Constant** at any rect size |
| Sliced, zero border on an axis | That axis stretches, so the pad **scales** on it |
| Simple | The whole quad scales, so **all** padding scales |

So the correction above is exact for Simple, and for Sliced it is exact on any axis whose pad sits
inside the border.

## 2. Alpha centroid, not bounding box

When two sprites replace each other in one slot — whole and broken, on and off, full and empty — a
matching bounding box does not mean a matching position.

**The eye tracks the alpha-weighted centroid.** Measure that, not the box.

A real case: two 256×220 hearts whose bounding boxes agreed to 2 px. Their centroids differed by
**5.6 px**, which was 1.58 units at the authored icon size. The swap read as a jump, because a snap
with no motion is more visible than a large moving change.

Fix by offsetting the rect while the second sprite is shown, so the visible art does not move:

```
offset = (centroidB - centroidA) * rectH / spriteH      # applied while B is displayed
```

Re-pivoting the sprite is cleaner and needs no code — but **check every other user first**. A sprite
shared with another prefab or scene cannot be re-pivoted for one screen.

## 3. Nine-slice borders

Border on an edge = that edge's transparent pad **plus** the corner radius.

Check the borders leave room: `left + right` must be well under the sprite width, and the same
vertically. A rect shorter than `top + bottom` squashes the caps and looks wrong.

Measure the corner radius as the first row whose opaque span reaches its maximum. The script reports
this.

**Look before you set one.** A sprite may already carry a border someone authored deliberately.
Overwriting it with a fresh measurement is a change nobody asked for.

## 4. Compare scale-independently

A render and a mock are almost never the same pixel size, so raw pixel comparisons mean nothing.

Normalise both sides against something in the image:

| Measuring | Normalise by |
|---|---|
| Text outline or stroke weight | Cap height |
| Element position | Parent rect dimension |
| Icon size | Its container's opaque art |
| Gap between elements | The element width beside it |

One real case: a title outline measured 8.5% of cap height against the mock's 16.0%. That comparison
was actionable at any zoom, where "2 px against 7 px" would not have been.

**Note the noise.** A mock measured at a 17 px cap height has one pixel of antialiasing worth 6%, so
landing inside 2% of it is a match, not a miss. Say what the noise is when you report a percentage.

## 5. Measuring a flat image reference

No node tree, so everything comes from pixels.

1. Find the frame edges. If the mock is a screenshot, the device screen is the frame.
2. Establish scale: `scale = referenceResolution.x / mockWidthPx`.
3. For each element, measure its opaque bounding box in mock pixels, then multiply.
4. Measure gaps between elements, not just positions. A gap is what the eye checks.
5. Sample colours from flat interior areas, never from an edge — edges are blended.

A flat image cannot tell you an element's true rect, only its visible art. That is the same thing
the padding correction gives you from the other direction, so the two agree: **the design number is
always the opaque art.**

## 6. What a measurement cannot tell you

- Whether a colour is a face fill or an outline. A small glyph with a thick outline averages to a
  colour that is neither. Check the project's material palette before trusting a sampled value.
- Whether an element is conditional. A mock shows one state. Ask which controls appear always.
- Whether two similar elements are one reused asset or two. Compare their opaque dimensions.

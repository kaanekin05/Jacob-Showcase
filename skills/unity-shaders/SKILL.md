---
name: unity-shaders
description: Unity shader standards for URP/HDRP — naming, fragment-shader cost, SRP Batcher compatibility, variant and keyword stripping, and the C# side of binding material properties. Use when checking shader work against the rules, or when you need the rule before writing one. Authoring a shader, effect or render feature as a deliverable is the `unity-shader-specialist` agent, not this. Trigger keywords — shader standards, is this SRP Batcher compatible, shader variants are bloating the build, multi_compile vs shader_feature, MaterialPropertyBlock, review this shader.
---

# Unity Shader Standards

On-demand standards for Unity shader work. Pairs with the §frameworks Render Pipeline
rule (URP/HDRP/BiRP choice) and §performance (no per-frame allocations / cache string IDs).
Choose the render pipeline first — shaders are pipeline-specific and do not port.

## Naming & readability
- File/asset naming indicates type + purpose: `SG_Env_Water` (Shader Graph),
  hand-written `Env_Water`. Prefix by role (`Env_`, `UI_`, `Particle_`, `Post_`).
- Group material properties with `[Header(...)]` / `[Space]` attributes in the
  `Properties` block so the material Inspector is readable.
- No magic numbers in HLSL — use named constants or documented, exposed properties.
- Comment math-heavy sections (lighting, distortion, packing) — the *why*, not the *what*.

## Prefer URP's built-in shaders before hand-rolling
- URP ships lean, pre-optimized Lit/Unlit shaders — use the simplest one that works
  before authoring a custom shader.
- On low-end mobile: **Baked Lit** for static geometry, **Simple Lit** for dynamic
  objects, **Unlit** wherever lighting isn't needed. Reserve the full **Lit** shader
  and custom Shader Graphs for surfaces that actually need them.
- A custom shader is a maintenance + variant cost — justify it against the built-ins.

## Fragment performance
- Declare a target platform + complexity budget per shader (mobile vs PC differ wildly).
- Use `half`/`min16float` on mobile where full `float` precision isn't needed.
- Minimize texture samples in the fragment stage; never sample a texture inside a loop.
- Avoid dynamic branching in fragment shaders — prefer `step()`, `lerp()`/`mix()`,
  `smoothstep()`. If a branch is genuinely needed at runtime, see `dynamic_branch` below.
- Two-pass approach for blur (horizontal then vertical) instead of one wide kernel.

## SRP Batcher compatibility (URP/HDRP — strict)
The SRP Batcher reduces the **CPU cost** of preparing draws by keeping per-material
data persistent in GPU memory — it does **NOT merge draw calls** (that's GPU
instancing / static batching) and does not reduce their count. A batch spans
consecutive draws that share the **same shader variant**; mixing variants or
materials breaks the run. "Saved by batching: 0" / "Nodes have different shaders"
almost always means a variant/compatibility mismatch, not a setup bug.

To qualify as SRP-Batcher-compatible (per Unity Manual, SRP Batcher requirements):
- Declare **all built-in engine properties** in a single constant buffer named
  `UnityPerDraw` (e.g. `unity_ObjectToWorld`, `unity_SHAr`).
- Declare **all material properties** in a single constant buffer named
  `UnityPerMaterial`.
- A material property declared in `Properties` but **missing from the
  `UnityPerMaterial` CBUFFER makes the shader SRP-Batcher-incompatible** — silently
  dropping batching. Verify the status in the shader's Inspector panel.
- Shader Graph emits compatible CBUFFERs automatically; hand-written HLSL must do it manually.

## Shader variants & keyword stripping (build-size critical)
Each keyword combination is a *separate compiled variant* — variant count is
multiplicative and is a primary driver of build size and compile time.
- `#pragma shader_feature <kw>` — the compiler **excludes unused keywords from the
  build**. Use for keywords toggled by *material state* (a variant ships only if some
  material uses it). NOT safe for keywords toggled from script at runtime — that
  variant may not exist in the build.
- `#pragma multi_compile <kw>` — keeps **all** variants in the build. Use for
  keywords toggled at **runtime** from C# (`Material.EnableKeyword`/`DisableKeyword`).
- `#pragma dynamic_branch <kw>` — one variant with a runtime branch instead of N
  compiled variants; trades a small GPU branch cost for far fewer variants. If a
  keyword is declared both `dynamic_branch` and `multi_compile`/`shader_feature`,
  Unity uses `dynamic_branch`.
- **Stage-specific suffixes** cut variants Unity would otherwise generate for stages
  that don't branch: `shader_feature_fragment` / `shader_feature_vertex` (and the
  `multi_compile_*` equivalents) declare that the keyword only conditions that stage.
- **Material keyword discipline:** a `shader_feature` variant ships only if some
  material references its keyword — so leaving unused material features enabled
  (emission, detail maps, specular highlights) silently inflates the build. Disable
  what a material doesn't use.
- **Stripping order:** first use the built-in **Graphics → Shader Stripping / Shader
  Build** settings (cheap, no code); reach for a build-time `IPreprocessShaders`
  stripper only for project-specific rules the settings can't express.
- Document every keyword and its purpose, and monitor total variant count.

## C# side (cross-ref §performance)
- Cache property handles with `Shader.PropertyToID("_Color")` once — never pass raw
  string names every frame in `Update`/`LateUpdate`.
- Use `MaterialPropertyBlock` for per-renderer property overrides instead of
  instancing new `Material` objects (which break batching and leak material instances).
- Reuse one `MaterialPropertyBlock` instance; don't allocate one per frame.
- For many identical renderers differing only by per-instance data, enable GPU
  instancing (`#pragma multi_compile_instancing` + `UNITY_INSTANCING_BUFFER`).

## Anti-patterns
- DO NOT add a `Properties` entry without mirroring it in `UnityPerMaterial` (kills SRP Batcher).
- DO NOT use `shader_feature` for a keyword you toggle from script at runtime.
- DO NOT sample textures inside loops or dynamic-branch in the fragment stage on mobile.
- DO NOT mix shaders authored for different render pipelines in one directory.
- DO NOT instantiate `Material` per renderer for a color/float tweak — use `MaterialPropertyBlock`.

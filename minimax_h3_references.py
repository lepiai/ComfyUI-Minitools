# -*- coding: utf-8 -*-
"""
MiniMax H3 Professional Knowledge Base
从 h3skills001 (minimax-h3-local-video-generator) 的 7 个 references 文档提炼的精简规则集。
每个常量约 1-2KB，保留核心规则、表格模板和审计项，去掉重复说明和示例。
"""

# ============================================================
# 1. 动画十二法则（animation-principles.md 提炼）
# ============================================================
REF_ANIMATION_PRINCIPLES = """## Animation Principles (Disney Twelve)

Apply across the complete motion system. Adapt intensity to the reference's medium and material.

### Core chain per major beat:
staging -> anticipation -> primary action -> graphic/environmental response -> follow-through/overlap -> moving settle -> outgoing momentum carrier -> cut or transformation -> incoming momentum carrier

### Style adaptation:
- Minimal/luxury: subtle anticipation, precise easing, restrained overlap, one decisive exaggeration, long confident holds.
- Industrial/mechanical: rigid volume, measured preparation, rail or scan paths, hard locks, minimal deformation.
- Dense collage/editorial: clear staging, pose-to-pose panel locks, staggered overlaps, cropped exaggeration.
- Organic/elastic/character-led: visible squash and stretch, curved arcs, stronger anticipation, overlapping hair or fabric.
- Typography-led: pre-shift, grouped assembly, style-appropriate deformation or reflow, overshoot, lock, motivated exit.

### Rules:
- Use pose-to-pose for identity, anatomy, typography locks, products, precise layouts. Use straight-ahead for particles, fabric, ink, liquid, trails, organic secondary motion.
- Cut while outgoing motion still carries energy. Incoming shot inherits, redirects, transforms, or absorbs that energy. Avoid rest-to-rest cuts.
- Breath beats and pose islands are reduced-amplitude motion, not dead stops. Preserve camera drift, parallax, hair/cloth overlap, particles, or typography micro-adjustment.
- 1-3 primary movers per beat; supporting layers remain static or subordinate.
- Exaggeration never breaks volume, identity, anatomy, product geometry, spelling, or layer order.
"""

# ============================================================
# 2. 动效风格路由（motion-style-routing.md 提炼）
# ============================================================
REF_MOTION_STYLE_ROUTING = """## Motion Style Routing

Derive motion from the supplied visual style. Do not start from a favorite effect or previous prompt.

### Derivation order:
medium -> composition -> geometry -> typography -> material behavior -> visual density -> spatial tendency -> rhythm contour -> tempo -> transition family -> prohibitions

### Material behavior inference:
- Paper: tear, fold, flip, slide, overlap, tape, stamp.
- Ink/print: bleed, spread, overprint, misregister, press, reveal through halftone.
- Glass: refract, split, slide by facets, focus, restrained caustics.
- Fabric: pull, fold, ripple, wrap, unveil.
- Pixel/digital UI: quantize, scan, cascade, tile, buffer, reorganize by modules.
- Hand drawing: draw on, retrace, erase, redraw, circle, underline.
- Liquid vector: melt, stretch, swell, splash, swallow, fold, recombine.
- Fine-line diagram: trace, calibrate, orbit, align, lock, unfold symmetrically.
- Metal/industrial: scan contours, assemble panels, track details, wipe with hard highlights.
If the motion could be applied unchanged after replacing the medium, it is too generic.

### Spatial tendency:
- Grid -> modular swapping, aligned slides, controlled reflow.
- Scroll/panoramic -> continuous lateral travel and motif relay.
- Deep perspective -> tunnel travel, scale inversion, portal transitions.
- Centered -> convergence, radial expansion, impact from center.
- Symmetrical -> mirrored construction, calibration, ritual unfolding.
- Panel -> frame replacement, nested windows, page logic.
- Whitespace-led -> few precise moves, large negative-shape changes, strong reveal.

### Visual density profiles:
- Low: few primary elements, broad whitespace, limited motifs, shallow overlap.
- Medium: several coordinated modules, moderate whitespace, recurring motifs, 2-3 depth bands.
- High: layered background fields, multiple secondary modules, micro accents, frequent overlap, broad typography coverage.
Match the reference's distribution bidirectionally. Do not apply fixed decoration to every project.
"""

# ============================================================
# 3. 跨模态风格一致性（style-coherence.md 提炼）
# ============================================================
REF_STYLE_COHERENCE = """## Cross-modal Style Coherence

The approved style reference is the artistic source of truth for the complete film. Every domain must cite evidence from it.

### Style contract:
- medium, finish, surface behavior
- era, cultural, genre cues
- palette hierarchy, contrast, brightness, saturation, temperature
- geometry, motif family, edge language, silhouette character
- composition, grid, whitespace, overlap, cropping, depth
- visual density and detail hierarchy
- typography personality, construction, hierarchy, spatial role
- implied weight, elasticity, precision, aggression, softness, playfulness, restraint
- dominant direction, motion material, timing contour, transition logic
- explicit prohibitions

### Coherence matrix (fill every row):
| Domain | Evidence from reference | Derived decision | Prohibited mismatch |
- Rendering and material: finish, layer treatment, lighting, deformation vs unrelated rendering
- Composition and density: shot layouts, occupied regions, layer stack vs generic sparse/maximal
- Motion: verbs, easing, amplitude, arcs vs reusable preset
- Typography: family, weight, case, tracking, outline, grid role vs unrelated fashionable type
- Typography motion: draw, stamp, crop, tile, reflow, collide, scan vs generic fade/scale/slide
- Camera and transitions: camera path, amplitude, transition carriers vs unrelated spectacle
- Edit rhythm: shot budget, interval contour, bursts, breath, climax vs reused timestamps
- BGM: genre, timbre, instruments, BPM, groove, phrase shape, dynamics vs arbitrary trending track
- Sound effects: small coherent effect palette vs unrelated material world

### Global test: replacing the reference with an unrelated one should make the complete plan feel wrong.
"""

# ============================================================
# 4. 片内布局多样性（intra-film-diversity.md 提炼）
# ============================================================
REF_INTRA_FILM_DIVERSITY = """## Intra-film Layout and Motion Diversity

Lock style invariants (palette, material, typography family, motif DNA, easing, directional logic). Vary structural axes per beat.

### Distinct-composition test:
A major landing counts as distinct ONLY when at least 3 structural axes change:
- layout skeleton and occupied regions
- subject scale, crop, angle, position
- focal count and hierarchy
- negative-space topology
- layer topology (BG/MG/subject/FG)
- typography-image relationship
- primary graphic operation
- primary motion carrier and transformation mechanism
- camera behavior and transition carrier

### Rejection tests:
- Content-swap: replacing subject and words leaves the same poster template = repeated.
- Silhouette: nearly identical light/dark masses = require stronger change.
- Typography-removal: remaining panels occupy same regions = not distinct.
- Motion-removal: same spatial skeleton after motion stops = not distinct.

### Layout-diversity matrix (create before writing shots):
| Beat | Layout ID | Spatial skeleton | Subject scale/crop | Focal count | Negative space | Layer topology | Type-image relation | Primary motion | Exit mechanism | Distinctness proof |

### Shot-change and distinct-layout budgets:
- Restrained/ceremonial: ~4-6 distinct compositions
- Medium-energy: ~6-8
- Dense/playful/editorial/action-led: ~7-10, including justified acceleration burst
- Excluding final hold, >=70% of major landings use independent spatial skeletons

### Rotate motion mechanisms:
Dense/editorial films should use >=4 observable reference-derived mechanisms (panel reflow, mask/crop reveal, typography construction, shape transformation, match action, foreground occlusion, parallax relay, camera-scale handoff, material tear/fold, trace/draw, smear/echo, light/scan travel, spatial collapse/expansion). Do not repeat the same entry->assembly->settle->exit chain in consecutive shots.
"""

# ============================================================
# 5. BGM 主导音画编排（music-sync.md 提炼）
# ============================================================
REF_MUSIC_SYNC = """## BGM-led Audiovisual Choreography

Treat BGM as the primary temporal spine and dominant non-verbal audio layer.

### Audio hierarchy:
1. BGM structure and musical continuity
2. Required dialogue or narration (when present)
3. Selected hero sound effects
4. Low ambience and texture

### Design BGM before visual timing:
- genre/production family derived from visual style
- tempo or narrow BPM range
- meter and subdivision (quarter-note drive, eighth-note pulse, triplet swing, syncopated sixteenths)
- 2-4 core instruments with stable roles
- recurring rhythmic cell or bass pattern
- phrase structure across full duration
- energy contour: pickup -> establishment -> build -> breath/breakdown -> climax -> final cadence
- named musical accents for major reveals, impacts, title assembly, final lock

### Music cue sheet (create before shot timeline):
| Time | Music event | Visual event | Sync relationship | Supporting SFX |
Map cuts, action landings, camera peaks, graphic transformations, typography locks to named musical events (pickups, downbeats, accents, fills, breaks, rises, drops, cadence).

### Rules:
- Stage/anticipate during pickup or pre-beat. Land on accent. Follow-through after accent.
- Keep one continuous BGM across cuts. No restarts, random instrument changes, competing grooves.
- Sound effects sparse, short, subordinate. Reserve strongest effect for 1-2 genuine climax events.
- Do not hit every beat with every layer. Distribute camera/subject/graphics/typography across compatible subdivisions.
- For uploaded BGM: analyze actual signal, derive cut times from its beat map, cite <Audio 1> consistently.
"""

# ============================================================
# 6. 制作规范（production-spec.md 提炼）
# ============================================================
REF_PRODUCTION_SPEC = """## Production Specification

### 15-second narrative arc (style-derived order, not equal sections):
1. Iconic hook and style declaration
2. Subject, world, or product reveal
3. Development or capability escalation
4. Optional breath, pose island, reset, or contrast beat
5. Climax or transformation
6. Stable title, product, logo, or CTA hold

### Rhythm and shot-change budget:
- Restrained/slow references: ~4-6 distinct compositions
- Medium-energy: ~6-8
- Dense/playful/editorial/action-led: ~7-10, with strategically placed short-shot bursts
- Build a non-uniform rhythm contour. Do NOT distribute shots at approximately equal intervals.
- Make rhythm irregular by ADDING cuts at acceleration/climax, not by reducing shot count.
- At least one meaningful acceleration, deceleration, syncopation, breath, or tempo contrast before final hold.

### Cut-to-cut momentum bridge:
At every cut, name the outgoing motion carrier (direction, speed, scale, or rotational energy) and the incoming camera/element motion that inherits, redirects, transforms, or absorbs it. Cut while motion still carries energy. Avoid rest-to-rest cuts and frozen breath beats.

### Quality-preserving motion rules:
- Each action has clear start pose, readable path, landing pose.
- Breath beats/pose islands = reduced-amplitude motion, not dead stops.
- Preserve subtle continuity carrier (camera drift, parallax, hair/cloth overlap, particles, light travel, typography micro-adjustment).
- Final readable layout stable for >=1 second with subtle supporting motion alive.
- Principal subject large enough to read during hero beats.
- Limit isolated flashes to named beats. Forbid continuous strobing.
- Typography = held layout, not texture spread across deforming action. Multi-stage path: entry -> assembly/transformation -> interaction -> readable lock -> motivated exit.
- Coordinate letter/word/line/block hierarchy. Do not animate every glyph simultaneously.
"""

# ============================================================
# 7. 提示词审计（t2va-prompt-template.md 47项精简版）
# ============================================================
REF_PROMPT_AUDIT = """## Prompt Audit Checklist

Before submission, verify:

1. Required fields exist once and in correct order for the chosen mode.
2. Timeline fits the requested duration. Cut times are chronological and within video duration.
3. No shot asks for multiple incompatible hero actions simultaneously.
4. Every graphic motif has a defined appearance and behavior.
5. Exact copy is quoted and readable in a held composition. User-supplied strings preserved character-for-character.
6. Sound effects correspond to visible actions. Music dynamics correspond to visual beat events.
7. Every negative requirement is concrete and relevant.
8. Character identity and palette come from approved character source; motion and layout from approved style source.
9. Visual density matches the approved style reference (not defaulting to sparse or maximal).
10. Complex references retain layer richness through later shots and final card; simple references preserve intentional whitespace.
11. Static layer richness does not create simultaneous motion overload.
12. Still-reference cut times follow a style-derived rhythm contour, not approximately even division.
13. At least one meaningful acceleration, deceleration, syncopation, breath, or tempo contrast before final hold.
14. Every important text string has explicit role, hierarchy, entry, construction/transformation, interaction, readable lock, and exit behavior.
15. Typography motion matches reference's material, geometry, density, layout, rhythm. No basic fades, uniform scaling, or repeated slide-ins as complete animation.
16. Major beats describe staging, anticipation, pose/layout anchor, primary action, secondary response, follow-through/overlap, settle, and exit.
17. Disney's Twelve Principles applied across the complete film with intensity adapted to approved style.
18. Rhythm variation does not come from reducing shot changes. Shot-change budget fits reference energy and density.
19. Every adjacent shot pair defines outgoing and incoming momentum carrier. No ordinary cut is rest-to-rest.
20. Final layout remains readable while supporting movement decays gradually instead of freezing abruptly.
21. One coherent BGM defines tempo, pulse, instrumentation, phrase structure, energy contour, climax, and final cadence before visual timestamps are assigned.
22. Major visual events map to named BGM events. Anticipation before accent, landing on accent, follow-through after.
23. Cuts do not restart or randomly change BGM. Sound effects sparse, short, subordinate.
24. One approved reference cluster governs every artistic domain. Incompatible references not averaged into generic hybrid.
25. A layout-diversity matrix exists. Every major landing has layout ID plus 3-axis distinctness proof.
26. Excluding final hold, >=70% of major landings have independent spatial skeletons.
27. Adjacent beats rotate primary motion carriers and entry-assembly-settle-exit chains.
28. Global style invariants stated once. Shot descriptions use specific construction verbs, not repeated style paragraphs.
"""

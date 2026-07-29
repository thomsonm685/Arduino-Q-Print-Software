# Fargo DTC1250e — Research & Print-Tuning Reference

Compiled research on the HID Fargo DTC1250e, its Linux/CUPS driver, dye-sub print
physics, and the practical settings for **true color, sharp edges, edge-to-edge
printing, and no bleed** — plus the hardware/consumable knowledge to avoid jams.

Sourced from HID's official docs (User Guide **PLT-01668**, Linux CUPS Driver Guide
**PLT-04870 Rev A.4**), reseller support pages, and printing forums. Where a claim
is inference rather than verbatim vendor text, it is **flagged**.

> **Read this first — your driver build is a variant.** Your printer's PPD exposes
> `ColorModel=RGBW/RGB` and `ColorMatching=None/ICC1/ICC2`. HID's *documented* Linux
> driver (PLT-04870 A.4) instead uses `ColorMode=RGB/RGBK` and
> `ColorMatching=System/None`. So the explanations of **RGBW**, **ICC1**, **ICC2**,
> and the extra ribbon types below are **informed inference**, not verbatim HID text.
> The definitive description of *your* build's options lives in the PPD:
> ```bash
> sudo grep -iE '\*OpenUI|\*Default|ColorModel|ColorMatching|Ribbon|Intensity' \
>   /etc/cups/ppd/Fargo-DTC-1250e.ppd
> ```

---

## 1. Quick reference — recommended starting settings

For a full-color ID badge on a YMCKO ribbon, aiming for accurate color + sharp text.
**Verify each with a test card; every ribbon/card batch behaves slightly differently.**

| Option | Value | Why |
| --- | --- | --- |
| `Ribbon` | `YMCKO` | Match the physically loaded ribbon exactly |
| `PageSize` | `CR80` | Standard credit-card size (85.6 × 54 mm) |
| `Resolution` | `300dpi` | Native printhead resolution |
| `ColorModel` | `RGB` *(see §7)* | Your app currently defaults here; `RGBW` misaligned channels |
| `ColorMatching` | `ICC2` | ICC profile; on the bench beat None and ICC1 for true green |
| `ResinDither` | `graphics` | Crispest black text / barcodes |
| `DyeSubIntensity` | `0`, tune **+2…+5** | Color density (heat). **The bleed/jam knob — go slow** |
| `ResinHeatFront` | `0` | Only raise a few points if black text is faint |
| `OverlayHeat` | `0` | Overlay adhesion |
| `KPanelApplyFront` | `Fullcard` | Route black pixels to the sharp resin panel |
| `YMCunderKFront` | `False` | Maximizes sharpness of resin text/barcodes |
| `CardThickness` | `30` | Standard 30 mil PVC |
| `ImageHOffset` / `ImageVOffset` | `0` | **H-offset can break the ribbon — nudge cautiously** |

Feed the driver an image **pre-rendered to exact size at 300 dpi** so CUPS does no
rescaling (see §11). Q-Print already does this (1110 × 638 canvas, 300 dpi tagged).

---

## 2. Your symptoms → likely fix (fast triage)

| Symptom | Most likely cause | Fix |
| --- | --- | --- |
| **Greens print blue** | Weak yellow / wrong color path. Green = yellow + cyan; weak yellow → blue-green. Plus RGBW channel misalignment. | `ColorModel=RGB` + `ColorMatching=ICC2`; ensure YMCKO ribbon; small `DyeSubIntensity` bump |
| **Colors light / faded** | Dye-sub intensity too low, or dirty printhead, or non-dye-sub card stock | Raise `DyeSubIntensity` **+5 at a time**; clean printhead; confirm dye-sub-receptive PVC |
| **Yellow bleeding at edges** | **Too much heat** (yellow is first + weakest panel, bleeds first), OR wrinkled ribbon after a jam, OR dirty platen | **Lower** `DyeSubIntensity`; advance to clean ribbon panel; clean platen roller |
| **Ribbon jammed / tangled** | Heat too high → ribbon sticks/melts to card; also H-offset, worn platen, static | Lower intensity; recalibrate ribbon sensor; clean; §13 |
| **Edges clipped / lost** | DTC leaves a thin margin; art not oversized; position off | Oversize art (bleed); calibrate with `ImageV/HOffset`; §10 |
| **Faded/bleed unchanged by intensity** | Not a settings problem — damaged ribbon or dirty/contaminated hardware after a jam | Fresh ribbon panel, cleaning card, **run the self-test** (§16) to isolate hardware |

**Rule of thumb:** *fade* and *bleed* are the two ends of the **same heat knob**
(`DyeSubIntensity`). The target is the **lowest** intensity that fully saturates. If
adjusting intensity does nothing, the problem is physical (ribbon/rollers/card), not
software.

---

## 3. Print technology

The DTC1250e is a **direct-to-card (DTC)** printer combining two thermal methods in
one pass sequence. Ribbon and card travel together under a thermal printhead.

**Dye-sublimation (Y, M, C panels):** The printhead's heater elements (256 heat
levels each) vaporize dye from the ribbon; the gas diffuses **into** the card's PVC
surface and re-solidifies just below it. Variable heat → variable dye → **continuous
tone** (256 shades/pixel, up to 16.7M colors). Because dye sits *under* the surface,
the image is smudge- and fade-resistant.

**Resin / mass transfer (K, O panels):** These do **not** sublimate. Once the
printhead reaches transfer temperature, the whole resin/overlay material is
transferred onto the card. Resin black (K) is dense, sharp, and machine-readable —
ideal for text and barcodes. Overlay (O) is a clear protective topcoat.
*(Sources: idwholesaler.com dye-sub explainer; alphacard.com resin-transfer explainer.)*

### YMCKO panel order (one pass per panel, in this sequence)
1. **Y — Yellow** (dye-sub) ← *first down, weakest, most heat-sensitive → bleeds first*
2. **M — Magenta** (dye-sub)
3. **C — Cyan** (dye-sub) → Y+M+C blend into the full-color image
4. **K — Black resin** (mass transfer) → dense black for text/barcodes, over the color
5. **O — Overlay** (clear mass transfer) → protective topcoat over the whole card

This order is *why* green trouble shows as blue: green is **cyan + yellow**, and if
the first/weakest **yellow** panel under-transfers, cyan dominates → blue-green.

### Printhead & heat
- Edge-type **thermal printhead, 300 dpi**, hundreds of individually controlled
  resistive heaters across the card width.
- **HID does not publish an operating temperature.** Thermal card printheads reach on
  the order of a few hundred °C at the dot for a few milliseconds, but treat any
  specific number as **unverified**. What matters operationally is *relative* heat:
  the `DyeSubIntensity` / `ResinHeat` / `OverlayHeat` sliders.
- **Static-sensitive and expensive.** HID recommends an ESD strap when servicing.
  Never touch the heater line with fingers/tools. Warranty: 3-year printhead,
  **unlimited passes when using genuine UltraCard stock** (a strong hint that card
  quality drives head life).

### Resolution & speed
- **300 dpi** (optimized modes up to 300 × 600 dpi); 256 shades/pixel.
- Single-sided speed: **K ≈ 6 s**, **KO ≈ 8 s**, **YMCKO ≈ 16 s (~225 cards/hr)**,
  **YMCKOK ≈ 24 s**.

### Card specifications
- **CR-80: 3.375″ × 2.125″ = 85.6 × 54 mm** (native orientation is **landscape**).
- **Thickness: 9–40 mil**; standard ID card = **30 mil (0.76 mm)**. The
  `CardThickness` driver setting must match the actual cards or you get feed errors.
- **Surface must be dye-sub-receptive:** glossy/polished **PVC** (or PVC-laminated
  composite/PET). **100% polyester (PET) can't take dye-sub color** — it needs
  monochrome resin. Rough/uncoated/generic-plastic cards → washed-out color and
  shorter printhead life. HID's genuine stock: **UltraCard / UltraCard Premium**
  (Premium is composite ~60% PVC / 40% PET, more heat/warp resistant).

---

## 4. Ribbons

Supplied as **EZ snap-in cartridges with an integrated cleaning roller** (a new
cleaning roller ships with every ribbon). An **RFID tag** tells the printer the
ribbon type and remaining count — non-genuine/expired ribbons throw errors
(#93 Wrong Ribbon, #100 RFID Error).

| Ribbon | Panels | Yield | Use |
| --- | --- | --- | --- |
| **YMCKO** | Y, M, C, K-resin, O | 250 | Full color one side + resin black + overlay (normal choice) |
| **YMCKO Half-Panel** | half-width Y/M/C; full K, O | 350 | Color on part of card (fixed photo) + black anywhere |
| **YMCKOK** | Y, M, C, K, O + 2nd K | 200 | Color front + resin black back (dual-sided) |
| **Mono resin K** | single K | ~500–1000+ | Text-only badges, barcodes |
| **KO** | K-resin + overlay | — | Mono black + protective overlay |

**Half-panel** means the Y/M/C panels are physically **half width** (K and O stay full
size) — full color on ~half the card, black anywhere, more prints per roll. Trust the
**panel string** (YMCKO / YMCKOK / half-panel), not the reseller SKU (part numbers
vary: 45010 vs 45014, etc.).

**Storage:** original packaging, cool/dry, out of sunlight; ~59–77 °F, <50% RH; ~12-month
shelf life. A dried/brittle old ribbon breaks more easily. Let a cold ribbon acclimate
(condensation risk).

---

## 5. The Linux / CUPS driver

**Authoritative doc:** *HID FARGO DTC™ Printers Linux User Guide, PLT-04870 Rev A.4
(June 2023)* — covers DTC1500/4500e/4250e/**1250e**/DTCii via one `rastertofargo`
filter. Download: hidglobal.com/drivers/41707 (DTC1250e Linux driver).

### Installed files (there is no uninstaller — remove these manually)
- `/usr/share/cups/model/DTC1250e.ppd` — the PPD
- `/usr/libexec/cups/filter/rastertofargo-x.y.z` — the raster filter **binary**
- `/etc/udev/rules.d/92-FARGO.rules` — USB permissions

### Architecture (important for the Arduino UNO Q / ARM)
HID states support for **x64, x86, MIPS, and ARM** — so ARM *is* supported in
principle, **but the tarball you installed must contain a `rastertofargo` binary built
for your CPU**. Verify:
```bash
file /usr/libexec/cups/filter/rastertofargo-*   # must match your arch (e.g. aarch64)
uname -m
```
A wrong-arch or non-executable filter is the classic cause of "filter failed" /
stuck-queue / nothing-prints. Also: firmware must be **≥ 1.0.4.10**; CUPS **≥ 1.7.2**;
**connect USB only after installing the driver**; **one driver instance per host**.

### Read the PPD for ground truth
Every option's token→meaning and default is written into the PPD:
```bash
sudo less /etc/cups/ppd/Fargo-DTC-1250e.ppd
# or targeted:
sudo grep -iE '\*OpenUI|\*Default' /etc/cups/ppd/Fargo-DTC-1250e.ppd
```

### `lp -o` usage
```bash
lpoptions -p Fargo-DTC-1250e -l              # list every option; * marks default
lp -d Fargo-DTC-1250e -o Ribbon=YMCKO -o DyeSubIntensity=5 front.png   # per-job
lpadmin -p Fargo-DTC-1250e -o Ribbon=YMCKO   # set a queue default
```
Each `-o Keyword=Token` maps 1:1 to a PPD entry; the PPD's `cupsFilter` line runs
`rastertofargo` against your selections + the incoming raster.

---

## 6. Option reference — color path

- **`Ribbon`** — tells the driver which panels exist. Set to the physically loaded
  ribbon. Documented values: `YMCKO` (default), `YMCKO_Half`, `YMCKOK`, `KStandard`,
  `None` (rewritable). Your build adds `KPremium, MonoColor, Metalic, KO, BO`
  *(inferred from Fargo's ribbon catalog — not in the A.4 doc)*.

- **`ColorModel` = `RGBW` | `RGB`** *(your build's keyword)* — the documented driver
  instead calls this **`ColorMode` = `RGB` | `RGBK`**, where RGBK adds a 4th channel
  routed to the **K resin panel**. *Inference:* `RGBW` is the CUPS 4-channel
  colorspace token (`CUPS_CSPACE_RGBW`), functionally the same "RGB + resin-black
  channel" idea; `RGB` is 3-channel dye-only (black comes from composite YMC, softer).
  **On this printer, feeding 3-channel RGB data while the driver expects the 4-channel
  RGBW mode misaligned the channels and shifted hues (greens → blue).** Q-Print
  defaults to **`RGB`** for that reason. If you print crisp resin black text, the
  documented `RGBK`/4-channel path *should* be preferable — but test on your build,
  since the tokens differ from HID's docs.

- **`ColorMatching` = `None` | `ICC1` | `ICC2`** *(your build's tokens)* — the
  documented driver uses **`System` | `None`**: *"shifts colors so the printed image
  more closely matches how they appear on the monitor."* The driver genuinely bundles
  ICC profiles (SampleICC / ICC license text appears in the guide). *Inference:* `ICC1`
  and `ICC2` are two selectable ICC profiles/intents; `None` disables matching (send
  device-native RGB or color-manage in your app). **Do not double color-manage** — if
  your app applies ICC, use `None`; otherwise let the driver do it.
  **Bench result:** both ICC1 and ICC2 printed true green; **ICC2 slightly better** →
  Q-Print defaults to `ICC2`.

- **`ResinDither` = `graphics` | `photos`** — **`graphics`** (default) for sharp
  barcodes/text via the resin panel; `photos` only if rendering continuous-tone
  imagery through resin.

---

## 7. Heat / density options — the bleed & fade controls

All numeric, range **−50 … +50**, default **0**. These set **printhead heat** for
each panel group. *(Verbatim from PLT-04870 A.4 §4.4.)*

- **`DyeSubIntensity` (YMC)** — *"Selects the intensity of the dye-sub."* Higher (+) =
  more heat → **darker, more saturated**; lower (−) = **lighter, less saturated**.
  - **This is the single most important knob for both fade and bleed.**
  - **Too low** → pale/washed-out cards.
  - **Too high** → dye over-diffuses laterally → **bleed/halo (yellow first)**, loss of
    fine detail, and at extremes **ribbon sticking, wrinkle, and jams/breaks**.
  - **Tune in small steps (±2…+5), reprinting each time.** Target the *lowest* value
    that fully saturates. Do **not** max it.

  > ⚠️ **Real-world:** a jump to **+25 fused the ribbon to the card and jammed the
  > machine.** Q-Print now caps the slider at **+15** and warns above +8. Most cards
  > are happy at **0…+10**. If edges bleed, go **down**, not up.

- **`ResinHeatFront` / `ResinHeatBack` (K)** — heat for the **black resin** panel,
  front/back. Raise if black text/barcodes are faint or don't fully transfer; lower if
  resin smears or fills in barcode gaps.

- **`OverlayHeat` (O)** — heat for the clear overlay. Raise if overlay flakes/frosts;
  lower if it wrinkles or hazes.

---

## 8. Color accuracy — why greens print blue, and how to fix

**Root cause of green→blue:** on a YMC ribbon, **green = cyan + yellow**. Yellow is
the **weakest and most heat-sensitive** dye and the **first** panel laid down. If
yellow under-transfers (low intensity, depleted/old panel, wrong media, or a color
path that suppresses it), cyan dominates and greens **shift blue/blue-green**. Dye-sub
also has a **narrower gamut than an RGB screen**, so vivid greens/blues are the hardest
colors and can look muted.

**Fixes, in order:**
1. **Correct color path** — `ColorModel=RGB` (your build) so channels aren't
   misaligned; **`ColorMatching=ICC2`** for a real color transform. *(Both are Q-Print
   defaults now.)*
2. **Single color manager** — either the app's ICC **or** the driver's, never both.
   Double-profiling desaturates and shifts hue. Q-Print sends clean sRGB and lets the
   driver (`ICC2`) manage → correct.
3. **Feed sRGB artwork** at exact size/300 dpi. Q-Print tags 300 dpi + sRGB and forces
   24-bit TrueColor (no palette quantization).
4. **Nudge yellow up** — a *small* `DyeSubIntensity` bump strengthens the weak yellow
   and pulls greens back from blue (watch for bleed).
5. **Right ribbon actually loaded** — confirm YMCKO so the yellow panel is in play.
6. **Spot/brand colors:** HID Fargo **Workbench → Color Assist** (Windows) for exact
   logo colors.

*(Sources: idwholesaler dye-sub explainer; whizz-tech color/wash-out guide; PLT-01668
Image Color tab; en.subtextile ICC/gamut explainer.)*

---

## 9. Sharp lines, text & barcodes — the resin K panel

Black **text and barcodes should print with the resin (K) panel**, not composite YMC
black — resin is denser, sharper, and machine-readable.

- **`ColorModel` 4-channel / `KPanelApplyFront=Fullcard`** — routes black pixels to the
  resin panel. `Fullcard` = "use resin black for all black pixels in the image."
- **`YMCunderKFront=False`** (default) — *"maximizes the sharpness of text and barcodes
  printed with resin black."* Only set `True` if you want a soft color-to-black
  transition (blended edges) at the cost of sharpness — **keep False for crisp
  barcodes.**
- **`KPanelResinThreshold`** (a.k.a. `ResinThreshold`) — how dark a pixel must be to go
  to resin. **Lower** = more near-black pixels use resin (sharper, heavier); **higher**
  = only very-dark pixels use resin (more stays soft YMC). Tune with the two options
  above. If barcodes don't scan / thin black is missing, lower the threshold.
- **`ResinDither=graphics`** — crisp text/barcodes; `photos` softens.
- **`ResinHeatFront`** — fine-tune resin sharpness: too high smears, too low breaks up
  thin lines.
- **Image side:** author at **300 dpi at final size**, export **sRGB**, avoid
  upscaling low-res sources (the #1 cause of blur). A light unsharp mask helps edges.
  Q-Print uses Lanczos resampling + unsharp for this.

---

## 10. Edge-to-edge / full-bleed printing

**Reality:** the DTC1250e prints "over-the-edge," but as a **direct-to-card** printer
it leaves a **thin unprinted margin** at the extreme edge. True zero-border full bleed
is only guaranteed on **retransfer** printers (e.g., HDP-series). You can get very
close, though.

- **Imaged (printable) area, CR-80 edge-to-edge:** **3.36″ × 2.11″ (85.3 × 53.7 mm)**.
- **Pixel dimensions at 300 dpi** (HID publishes no canonical full-bleed pixel size —
  these are computed):
  - Nominal card 3.375″ × 2.125″ → **≈ 1013 × 638 px**.
  - Printed area 3.36″ × 2.11″ → **≈ 1008 × 633 px**.
  - For reliable bleed, **oversize the art a few px past each edge** (Fargo's
    over-the-edge uses ~0.04″/~1 mm bleed per edge). Practical canvas ≈ **1013 × 638 px**
    with background art extended to the edges; keep important content ≥ ⅛″ from edges.
  - Q-Print's calibrated **1110 × 638** canvas is intentionally oversized on the long
    axis for bleed; the printer maps it onto the physical card.
- **Fix clipped/lost edges with position offsets** — `ImageVOffset` (+ toward rear /
  − toward front) and `ImageHOffset` (+ toward output / − toward input), range ±100.
  - **Units (inferred):** ~**1/300″ ≈ 0.085 mm per step** (one device pixel), so ±100 ≈
    ±0.33″ / ±8.5 mm of travel. Start at 0, nudge a few units, reprint.
  - ⚠️ **HID verbatim warning: "Adjusting the Horizontal Offset may result in ribbon
    breakage."** Move `ImageHOffset` in small steps and watch the ribbon.
- **Avoid dye bleeding off the edge:** don't combine heavy oversize with high
  `DyeSubIntensity` — excess edge dye + heat smears and can contaminate the platen.
  Keep bleed modest and intensity minimal.
- **`PrintAreaFrontOption`** can omit printing over mag-stripe / smart-chip / signature
  regions (`OmitMagStripe`, `OmitSmartChip`, `OmitSignature`).

**Calibration workflow:** print the calibration target (edge frame + registration
marks), see which edge is clipped, adjust `ImageV/HOffset` a few units, reprint, repeat
until the frame is even. Q-Print's "Print calibration target" button does exactly this.

---

## 11. CUPS image scaling — keep it 1:1 (sharpness + color)

By default CUPS's image filter (`imagetoraster`) **scales the image to fit the page,
preserving aspect ratio** — resampling that **softens edges and can shift color/position**.
Some scaling options (`fitplot`, `scaling`, `natural-scaling`) became inconsistent or
no-ops in CUPS ≥ 1.6 (Debian bug #745056).

**Best practice:** **pre-render the card art to the exact device raster (300 dpi, exact
CR-80 canvas) as a PNG** so the filter does a 1:1 pixel map — no resampling → crisp
resin text and accurate color. If you must let CUPS scale, prefer **`-o ppi=300`**
(fixes physical size) over percentage scaling, plus `-o position=center`. Printing a
PDF sized exactly to the card avoids fit-scaling entirely.

*Q-Print already renders to an exact 300 dpi canvas, so it sidesteps this.*

---

## 12. Bleeding — causes & fixes

Dye-sub bleed = dye spreading laterally beyond its pixel. Yellow (first, weakest panel)
haloes first, so over-heat bleed shows as **yellow ghosting at high-contrast edges**.

| Cause | Fix |
| --- | --- |
| **`DyeSubIntensity` / heat too high** (most common) | **Lower** it in small steps until the halo goes but color stays saturated |
| **`ResinHeat` too high** (black smear specifically) | Lower `ResinHeatFront/Back` |
| **Dirty rollers / platen / contaminated printhead** | Cleaning card + printhead alcohol swab; every ~500–1000 prints or per ribbon change |
| **Damaged / wrinkled ribbon** (often *caused* by prior over-heat) | Advance past the creased section or replace ribbon |
| **Panel misregistration after a jam** | Power-cycle; recalibrate ribbon sensor (§13) — shows as colored *fringes* rather than smear |
| **Wrong ribbon type / bad card stock** | Set exact ribbon; use dye-sub-receptive PVC/composite |

> If **lowering intensity to 0 does NOT reduce the yellow bleed** (or makes it worse),
> it is **not thermal** — it's a wrinkled/damaged ribbon, dirty platen, or panel
> desync from a jam. Advance to clean ribbon, clean the platen, power-cycle, and run
> the self-test.

---

## 13. Faded / washed-out prints — causes & fixes

| Cause | Fix |
| --- | --- |
| **`DyeSubIntensity` too low** | Raise **+5 at a time**, reprint each step |
| **Wrong gamma / double color management** | Use one color manager; sRGB input; `Gamma 1` equivalent |
| **Wrong / mis-detected / depleted ribbon** | Disable auto-detect, set exact ribbon; replace if depleted |
| **Non-dye-sub or wrong-side card** | Use dye-sub-receptive PVC/composite; print the correct side |
| **Printhead needs cleaning** (residue insulates heat) | Alcohol swab the printhead |

**Trade-off of raising intensity:** ribbon sticking, wrinkle, breaks/jams, and bleed.
Stop the moment color is rich. **This is what caused the +25 jam** — creep up slowly.

---

## 14. Ribbon jams, breaks & sync recovery

**Causes (highest-signal first):** heat/intensity too high (ribbon sticks/melts/tears);
worn or dirty platen roller; contaminated/warped/non-receptive card stock; static (low
humidity); wrong tension or install.

**Safe recovery:**
1. **Cancel the job; power off and unplug** before reaching in (protects you and the
   printhead). `cancel -a Fargo-DTC-1250e`.
2. Open cover, **remove the ribbon cartridge**.
3. If a **card** is stuck, use the printer's **Forward/Back buttons** to walk it out —
   **never yank**, never use metal tools near the printhead.
4. If the **ribbon broke**, **tape the ends** (or tape the loose end to the take-up
   core) and **hand-wind the take-up core past the damaged panels to a clean panel.**
5. **Recalibrate the ribbon sensor** so panel position re-syncs (below).
6. **Clean the printhead and platen** before resuming — leftover dye/resin re-jams.
7. Reinstall, close, power on, and **run a self-test** before a real job.

**Re-sync / recalibrate the ribbon sensor** (fixes color fringing / misplaced panels /
errors #97, #109/113, #128/170):
- Driver: **Printing Preferences → Card → Toolbox → Calibrate Ribbon**: (1) remove the
  ribbon cartridge, (2) close the cover, (3) select Calibrate Ribbon, (4) Calibrate.
- A **power-cycle** alone often re-finds the leading yellow panel and fixes post-jam
  misregistration.

**Tension** (for repeat *clean* breaks — a tension symptom, vs. melt = heat symptom):
Toolbox → Advanced → *Ribbon Print Tension* in ±5 steps (Identity People's DTC recipe:
Print Top of Form +10, End of Form −10, Ribbon Print Tension +5). Diagnose wrinkle vs.
clean break first — they need opposite adjustments.

---

## 15. Cleaning & maintenance

**Frequency:** clean **with every ribbon change**, and the platen/feed rollers
**~every 1,000 prints**.

**HID cleaning kit (86177):** 4 printhead swabs (99.99% IPA), 3 alcohol cards (rollers),
10 adhesive cleaning cards (path/roller routine).

**Printhead:** power off + unplug → remove ribbon → snap a swab (or use a cleaning pen)
→ **gentle single wipe along the heater line** → **let dry fully** before printing.
Light pressure only; never scrape.

**Platen / feed rollers (automated):** remove ribbon, remove cards → peel both sides of
an adhesive cleaning card → insert in the single-feed slot → driver **Toolbox → Clean
Printer → Clean** — the printer pulls the sticky card through and scrubs the rollers.

**Cleaning roller:** built into the ribbon cartridge, replaced with each ribbon; if it's
mis-seated you get feed errors (#70/#81).

**After a jam:** melted dye/resin on the platen forms an insulating film → streaks,
uneven transfer (fade), re-jams. Clean it off with an IPA card/swab; inspect the orange
platen roller for damage.

---

## 16. Error codes & the self-test (isolate hardware vs software)

**LED (button models, no display):** ON/OFF blue = on; Pause blue = ready; **Pause
blinking red = error**. Press ON/OFF to cancel, Pause to retry.

**Key error codes** (shown on the host / inferred from red LED):

| # | Meaning | Action |
| --- | --- | --- |
| 25 | Ribbon not installed | Install ribbon |
| 70 / 81 | Multiple / unable to feed | Fix `CardThickness`; check cleaning roller; cards stuck |
| 91 | Ribbon out | New ribbon |
| 93 / 100 | Wrong ribbon / RFID error | Match driver to ribbon; genuine ribbon |
| 97 | Ribbon search (can't find panel) | Clear jam; **recalibrate ribbon sensor**; tape to take-up core |
| 99 | Ribbon broke/jammed | Clear/tape; advance panel |
| 109/113 | Ribbon release (stuck to card) | Ensure ribbon not fused to card; replace; recalibrate |
| 110/112 | Card jam / align | Clear jam |
| 128/170 | Calibrate ribbon | Recalibrate sensor; clear anything blocking the sensor |

### 🔑 Self-test — bypasses the computer, CUPS, and this app entirely
- **Printer Settings card:** printer ready/idle → **hold Pause ≥ 4 seconds**.
- **Self-Test / Alignment card:** **hold Pause during power-up** (hold while switching on).

**Use it to isolate the fault:**
- **Self-test prints clean & vivid** → printer + ribbon are fine → problem is
  **software/driver/CUPS/image** → tune settings.
- **Self-test *also* bleeds/fades/jams** → the fault is **hardware** (ribbon, card,
  platen, printhead) → clean / recalibrate / replace. No setting will fix it.

HID asks you to have a self-test + sample card ready when calling support.

---

## 17. Environment

- **Operating: 65–80 °F / 18–27 °C, 20–80 % RH non-condensing.**
- **High heat** (ambient or driver intensity) → dye bleed/blur, ribbon sticking.
- **High humidity** → moisture spotting, poor dye bonding, feed issues.
- **Low humidity** → static → thin ribbon clings/wrinkles/jams.
- Good airflow; away from radiators/ducts/sunlight/dust; let it acclimate after temp
  swings (condensation).

---

## 18. CUPS gotchas for automation (Q-Print)

1. **CUPS reports "completed" even when the printer aborts internally.** CUPS marks a
   job done once the raster is handed to the device; a later ribbon break / jam / wrong
   ribbon happens in the printer's own firmware with **no rich back-channel to the CUPS
   queue**. *(This is architectural inference, not HID-documented — verify on your rig
   via `lpstat -p -l` / `printer-state-reasons`.)* **Do not trust CUPS completion as
   proof a card printed** — poll printer state and/or require operator confirmation.
   *(Q-Print already ends every run in operator confirmation and logs `lpstat` reasons.)*
2. **Image fit-scaling** softens/​shifts — pre-render to exact 300 dpi (§11). *(Q-Print
   does.)*
3. **Wrong-arch filter** on ARM → "filter failed"; check `file …/rastertofargo-*`.
4. Raise CUPS logging to debug when diagnosing: `cupsctl --debug-logging`, then read
   `/var/log/cups/error_log`.

---

## 19. Sources

**Primary (HID official):**
- User Guide **PLT-01668** (DTC1250e/1000Me/4250e): https://www.hidglobal.com/doclib/files/resource_files/plt-01668-1.2-fargo_dtc1250e_dtc1000me_dtc4250e_dtcii_user_guide_en.pdf
- Linux CUPS Driver Guide **PLT-04870 Rev A.4**: https://manuals.plus/m/bf74660c85710c6c54f72e29642c26bda86e6d3f8a5ce4c5635af5a9c5fdc03c
- HDP6600 CUPS Driver Guide PLT-05253 (sibling, corroborates heat/ICC semantics): https://www3.hidglobal.com/sites/default/files/resource_files/plt-05253_a.0_-_hid_fargo_hdp6600_cups_driver_user_guide.pdf
- Product page: https://www.hidglobal.com/products/dtc1250e · Linux driver: https://www.hidglobal.com/drivers/41707 · Firmware: https://www.hidglobal.com/drivers/24360
- ManualsLib readable mirrors (driver tabs): p.48 (color/matching) https://www.manualslib.com/manual/1248761/Hid-Fargo-Dtc1250e.html?page=48 · p.51 (image calibrate) https://www.manualslib.com/manual/1248761/Hid-Fargo-Dtc1250e.html?page=51

**Concepts & troubleshooting:**
- Dye-sub explained: https://www.idwholesaler.com/learning-center/what-is-a-dye-sublimation-id-card-printer/
- Resin transfer: https://www.alphacard.com/id-card-maker/resin-thermal-transfer-printing
- DTC1250e troubleshooting: https://www.idsecurityonline.com/dtc1250e-troubleshooting.htm
- Washed-out print / density: https://whizz-tech.com/support/photo-id-printer-washed-out-print/
- Ribbon break/jam (tension recipe): https://support.identitypeople.com.au/support/solutions/articles/51000329648-ribbon-break-jam-error-fargo-dtc-printer
- Cleaning: https://hidfargoprinters.com/how-to-clean-a-fargo-dtc1250e-card-printer/
- K-resin settings: https://help.cloudbadging.com/en/articles/11095102-how-to-adjust-k-resin-settings-on-your-id-card-printer
- Ribbon shelf life: https://idcardrepair.com/2024/10/03/understanding-the-shelf-life-of-ribbons-why-it-matters-for-your-printing-quality/
- CUPS image scaling: https://wiki.debian.org/CUPSImageManipulation · scaling no-op bug: https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=745056

**Caveats to keep in mind:**
- `RGBW`, `ICC1`, `ICC2`, and the extra ribbon tokens are your **build's** tokens —
  explanations are inference; **read your PPD** for the definitive descriptions.
- HID does **not** publish printhead temperature or a canonical full-bleed pixel size.
- `ImageHOffset/VOffset` units are inferred (~1/300″ per step); HID only states ±100.
- The "CUPS completed-but-aborted" behavior is architectural inference — verify on your
  rig before relying on it.

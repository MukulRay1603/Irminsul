# Genshin Impact — Elemental Mechanics, Reactions & Damage System

---

## The Seven Elements

Every character and enemy in Genshin deals one or more of seven elemental types: Pyro, Hydro, Cryo, Electro, Anemo, Geo, and Dendro. Elements interact with each other through reactions, which are the fundamental engine of team building and damage optimization.

---

## Elemental Reactions

### Vaporize (Pyro + Hydro)
One of the two "amplifying" reactions — it multiplies the triggering hit directly.
- Pyro hitting Hydro-affected enemy = 1.5x Pyro damage multiplier
- Hydro hitting Pyro-affected enemy = 2.0x Hydro damage multiplier

The 2.0x version (Hydro triggering on Pyro aura) is generally harder to achieve consistently. Most Vaporize teams are built around the 1.5x Pyro trigger — Pyro DPS characters like Hu Tao or Yoimiya repeatedly applying Pyro against a Hydro-maintained aura. Elemental Mastery increases the Vaporize multiplier further.

**Key teams that abuse Vaporize:** Hu Tao/Yelan/Xingqiu, Yoimiya/Yelan, Childe/Xiangling, National Team

---

### Melt (Pyro + Cryo)
The other amplifying reaction.
- Pyro hitting Cryo-affected enemy = 2.0x Pyro damage
- Cryo hitting Pyro-affected enemy = 1.5x Cryo damage

The 2.0x version is why Ganyu Melt is so powerful — Ganyu's Charged Attacks are all Cryo, but paired with off-field Pyro application from Xiangling, the Pyro aura gets maintained and Ganyu's Cryo attacks trigger 1.5x Melt consistently. Hu Tao Melt works when Cryo maintains aura and Pyro triggers 2.0x.

---

### Freeze (Hydro + Cryo)
Freezes the target, preventing movement and most actions for a duration. Frozen enemies can be Shattered by Heavy attacks (dealing Physical damage). Frozen enemies are also easy to hit.

Critically, Frozen enemies maintain both the Hydro and Cryo aura simultaneously. This means:
- Blizzard Strayer gives +40% CRIT Rate against Frozen enemies (on top of +20% against Cryo)
- Freeze teams effectively have permanent CRIT Rate bonus, allowing investment to shift to CRIT DMG
- Freeze is a soft CC that completely trivializes mobile enemies

Freeze duration scales with the strength of the aura applied. Strong Hydro/Cryo application from multiple sources keeps enemies perma-frozen.

---

### Superconduct (Electro + Cryo)
Deals minor AoE Electro-Cryo damage and reduces all enemies' Physical RES by 40% for 12 seconds. Not a damage reaction — purely a Physical resistance shred.

Used exclusively in Physical DPS teams (Eula, Razor, physical Fischl) to amplify Physical damage. The CRIT Rate bonus for Cryo resonance and Superconduct together are why Cryo batteries (Rosaria, Kaeya) appear in physical DPS teams.

---

### Overloaded (Pyro + Electro)
Explodes, dealing AoE Pyro-based damage and knocking enemies back. The knockback is significant — it pushes lighter enemies away, which can be disruptive to melee DPS characters who need to stay close.

Overloaded damage scales with Elemental Mastery of the triggering character. High EM builds can make Overloaded deal meaningful damage, but the knockback problem limits its use in sustained DPS compositions. Thoma-triggered Burgeon teams and some Fischl/Pyro teams utilize it.

---

### Electrocharged (Electro + Hydro)
Deals periodic Electro damage to all Electro-affected enemies connected through Hydro. The unique property: Electrocharged does not consume either aura — both Electro and Hydro coexist on the target simultaneously, allowing further reactions from other elements.

This makes Electrocharged a unique reaction that can enable other reactions simultaneously. It also bounces damage between connected Hydro-affected enemies — in groups of wet enemies, Electrocharged chains across all of them.

---

### Swirl (Anemo + Pyro/Hydro/Cryo/Electro)
Anemo cannot react with Geo or Dendro. Against all other elements, Anemo creates Swirl, which spreads the absorbed element to nearby enemies and deals bonus elemental damage. Swirl damage scales with Elemental Mastery only — not ATK or weapon stats.

The critical secondary effect: Viridescent Venerer (VV) 4pc set — the standard Anemo support artifact set — reduces enemy RES to the Swirled element by 40% for 10 seconds. This is why Kazuha, Sucrose, and Venti always run 4pc VV in support roles. The 40% RES shred is worth more damage amplification than most direct damage buffs.

Sucrose's Elemental Mastery shares 20% of her EM with the team when she triggers a Swirl, in addition to her Burst's team-wide EM buff.

---

### Crystallize (Geo + Pyro/Hydro/Cryo/Electro)
Creates a shard when Geo contacts another element (except Anemo or Dendro). Picking up the shard gives a shield that absorbs the crystallized element. The shield strength scales with the character's Elemental Mastery and level.

Crystallize is primarily a defensive reaction. Geo characters do not directly amplify elemental reactions — Geo's contribution is the universal shield and Geo RES shred (from Zhongli's pillar resonance and 4pc Tenacity of Millelith). Geo resonance (double Geo) gives +15% DMG while shielded and +15% shield strength.

---

### Quicken / Aggravate / Spread (Dendro + Electro)
The Dendro-Electro interaction introduced in Sumeru is fundamentally different from other reactions.

Quicken is the base reaction — Dendro + Electro creates a Quicken status on the enemy. From Quicken, two additional reactions branch:
- **Aggravate:** Electro hitting a Quickened enemy — deals bonus Electro damage (fixed bonus scaling with EM and level, added on top of the hit)
- **Spread:** Dendro hitting a Quickened enemy — deals bonus Dendro damage

Neither Aggravate nor Spread consumes the Quicken status. Both can proc repeatedly as long as the enemy remains Quickened, which makes Dendro-Electro teams sustain high damage over time without the reaction-application timing management that Vaporize/Melt require.

Key characters: Nahida (Spread trigger), Cyno (Aggravate main DPS), Fischl (Aggravate off-field), Raiden (Aggravate burst), Keqing (Aggravate main DPS)

---

### Bloom / Hyperbloom / Burgeon (Dendro + Hydro + Electro/Pyro)
Bloom is the Dendro + Hydro reaction, which creates Dendro Cores — explosive seeds that detonate after a short time, dealing AoE Dendro damage. Bloom damage scales with EM and level.

Dendro Cores can be further reacted:
- **Hyperbloom:** Electro hitting a Dendro Core — the core homes in on the nearest enemy and deals much higher Dendro damage. This is one of the highest DPS reactions in the game. Scales with the Electro character's EM. Raiden Shogun at high EM is a premier Hyperbloom trigger.
- **Burgeon:** Pyro hitting a Dendro Core — the core explodes in AoE Pyro-tinged Dendro damage. Scales with Pyro character's EM. The AoE can hit your own team, which requires careful HP management.

Pure Bloom teams let cores explode naturally — effective but less optimized than Hyperbloom. Hyperbloom with Raiden or Fischl as trigger, Nahida for Dendro, and Xingqiu/Kokomi for Hydro is one of the strongest reaction-based team compositions.

---

## Internal Cooldown (ICD)

ICD is one of the most important and least-explained mechanics in the game. When a character applies an element, there is a hidden cooldown before the same source can apply that element again. This prevents infinite reaction triggering.

The standard ICD rule: the same hit source can apply an element every 2.5 seconds OR every 3 hits (whichever comes first is reset). After the cooldown, the next hit reapplies the element.

**Why this matters for team building:**
- Xingqiu's Rain Swords have ICD between slashes — not every slash applies Hydro. This means rapid Normal ATK DPS like Hu Tao can't Vaporize every hit; approximately every 3rd hit triggers a reaction.
- Characters with no ICD on certain abilities (some AoE Bursts, specific skills) can apply elements much more freely.
- Kazuha Swirling an element absorbs the element and applies it to all nearby enemies — this has its own ICD distinct from the source character.

---

## Damage Formula Overview

Genshin's damage calculation follows this general structure:

**Base Damage = Scaling Stat × Ability Scaling %**

Scaling stat is typically ATK, but some abilities scale with HP (Hu Tao, Zhongli shield, Itto, Yelan) or DEF (Noelle, Itto burst, Albedo).

**Total Damage = Base Damage × (1 + DMG Bonus) × CRIT multiplier × Enemy DEF multiplier × Enemy RES multiplier × Reaction multiplier**

Breaking this down:
- **DMG Bonus:** Sum of all elemental/physical DMG% bonuses from artifacts, weapons, and passives
- **CRIT Multiplier:** (1 + CRIT DMG%) on a CRIT hit, 1 on non-crit; averaged to (1 + CRIT Rate × CRIT DMG%) for theoretical average
- **Enemy DEF Multiplier:** Reduces based on attacker level vs. enemy level and DEF shred
- **Enemy RES Multiplier:** Reduces based on enemy elemental resistance; VV and Zhongli reduce this
- **Reaction Multiplier:** Vaporize/Melt multiplier, or additive bonus damage for Aggravate/Spread

### The CRIT Ratio — the 1:2 Rule
Optimal CRIT investment follows approximately a 1:2 ratio of CRIT Rate to CRIT DMG. 50% Rate / 100% DMG, 70% Rate / 140% DMG, etc. This maximizes average damage output. Deviating heavily in either direction (100% Rate / 50% DMG, for instance) is suboptimal.

Characters with guaranteed CRIT sources (Ganyu's Charged Attack Level 2 always CRITs, Hu Tao's Blood Blossom CRITs under certain conditions) can shift investment toward CRIT DMG.

---

## Elemental Application Strength (Gauge Theory Basics)

Elements in Genshin have invisible "gauge" values — stronger applications leave a bigger elemental aura that takes more of the opposing element to remove. Reactions consume specific amounts of gauge.

**Practical implications:**
- Hydro application from Xingqiu is moderate per slash. Pyro hits from Hu Tao consume the Hydro aura partially per hit, which is why even with ICD, Vaporize procs regularly.
- Bennett's Burst applies Pyro AoE repeatedly — strong Pyro aura, enough to enable off-field Melt reactions.
- Freeze duration depends on the combined strength of the Hydro and Cryo applications — strong applicators like Kokomi (Hydro) + Ayaka (Cryo Dash) maintain long Freeze durations.

---

## Character Stats — What Actually Matters

### ATK vs HP vs DEF Scaling
Most characters scale with ATK. HP scalers (Hu Tao, Zhongli, Yelan, Furina) specifically convert their HP stat into damage or utility, making HP% a primary stat for them instead of ATK%. DEF scalers (Noelle, Itto, Albedo's Flower) make DEF% valuable for damage.

### The Artifact Main Stat Priority
For DPS characters:
- Sands: ATK% (usually) or ER% if energy-hungry, or EM for reaction-focused characters
- Goblet: Elemental DMG Bonus (almost always, unless Physical DPS)
- Circlet: CRIT Rate or CRIT DMG (match to where you're deficient)

For supports:
- Sands: ER% (for Burst uptime) or HP%/ATK% depending on scaling
- Goblet: HP%, DEF%, or ATK% for shields/healing
- Circlet: Healing Bonus% for healers, or HP%/ATK% for shields

---

## Constellation System

Constellations are duplicate copies of a character — obtaining a character's item again (through wishes) unlocks constellation levels C1 through C6. This is where significant power spikes hide for some characters.

### Notable Constellations
- **Bennett C1:** Removes the HP threshold from his Burst ATK buff (below 70% HP requirement removed) — significant quality of life
- **Bennett C6:** Converts sword/claymore/polearm characters in field to Pyro — potentially destructive, not universally desired
- **Xingqiu C2:** Rain Swords deal 15% more DMG and grant 1 additional sword — major DPS increase
- **Kazuha C2:** Grants 200 EM after using Burst — massive personal DPS increase, makes him competitive as a main DPS
- **Fischl C6:** Joint ATK on every Electro reaction — nearly doubles her off-field output
- **Xiangling C4:** Extends Pyronado duration by 40% — dramatically improves her consistency
- **Ganyu C1:** Charged Attack generates an additional Cryo AoE — significant AoE improvement
- **Raiden C2:** Resistance to interruption during Burst and significantly higher Burst DMG — major improvement
- **Nahida C1:** Adds additional hit to her Skill marks — notable DPS boost
- **Hu Tao C1:** Allows Charged Attack use without stamina cost during E — removes a significant quality of life limitation

---

## Spiral Abyss — Endgame Content

The Spiral Abyss is the primary endgame challenge, consisting of 12 floors (floors 9-12 are the rotating difficult content). Each floor has two chambers, each with an enemy lineup and a time limit. Clearing within the time limit yields stars (up to 3 per chamber, 6 per floor). Full completion (36 stars) requires two separate teams since Floors 9-12 have a "split" mechanic — you must use two different teams for the two sides of each floor.

This is why virtually all endgame discussion involves two teams. Building two strong teams that don't rely on the same key supports (you cannot use Bennett on both sides simultaneously, for instance) is the core strategic challenge of progression in Genshin.

Floors 11-12 refresh every two weeks with new enemy lineups and modifiers. The current abyss cycle often features:
- Buff cards that enhance certain reaction types or elements
- Enemy weaknesses that reward specific element applications
- Boss variants with high HP that favor sustained DPS teams

### Spiral Abyss Team Archetypes
- **Hypercarry:** One DPS supported by three dedicated supports — all buffs point at one character
- **Dual DPS:** Two DPS characters alternating field time, supported by shared utilities
- **Reaction team:** Built around consistent reaction triggering (Vaporize, Quickbloom, Freeze) rather than a single DPS carry
- **Mono-element:** Single element team using resonance bonuses and elemental DMG buffs (Mono Pyro with Bennett/Xiangling/Kazuha)

---

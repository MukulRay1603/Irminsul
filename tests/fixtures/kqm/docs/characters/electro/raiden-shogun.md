---
description: Her Excellency, the Almighty Narukami Ogosho, who promised the people of Inazuma an unchanging Eternity.
---

import char from '@site/src/data/characters/Raiden_Shogun.json'
import SkillIcon from '@site/src/components/char/SkillIcon'

# Raiden Shogun

import Image from '@theme/IdealImage'

<Image img={require('/img/characters/gacha/Raiden_Shogun.png')} alt="Raiden Shogun's gacha art" />
<blockquote>{frontMatter.description}</blockquote>

## Resources

<!--
* [Raiden Mains Discord]()
-->
* [Raiden Shogun Guide](https://keqingmains.com/raiden/)

## Attacks

import Skill from '@site/src/components/char/Skill'

<Tabs queryString="ability">
<TabItem value='e' label='Skill'>
<SkillIcon char={char} skill='e' />
<div class='talent-columns'>
<Skill char={char} skill='e' />

| Type      | Skill   | Coordinated Attack |
| :-------- | :------ | :----------------- |
| Particles | -       | 0~1 (1:1)          |

</div>

**Notes**

* The Eye's Elemental Burst DMG Bonus does affect the Raiden Shogun.

</TabItem>
</Tabs>

## Constellations

<Constellation char={char} c={4} />

* C4 buff does not apply to the Raiden Shogun herself.

## Beta Changes

* Burst scaling was raised during testing.

## Frames

```js
import frames from './frames'  // a code sample, not an MDX import
```

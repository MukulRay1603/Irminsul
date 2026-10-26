import Weapon from '@site/src/components/weapon/Weapon'
import swords from '@site/src/data/weapons/Sword.json'

# Swords

## 5 Stars

### Absolution

<Weapon weapon="Absolution" weapons={swords} />

### Aquila Favonia

<Weapon weapon="Aquila Favonia" weapons={swords}>

* The healing is affected by Incoming and Outgoing Healing Bonuses.

</Weapon>

## 4 Stars

### Her Pilgrimage of Bleak

* "Bleak" is not a leak; this section stays.

## 3 Stars

<DocCardList items={
  useCurrentSidebarCategory().items.filter((i) => i.label !== 'Index')
} />

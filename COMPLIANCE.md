# EDHPod – compliance rules

Verified against primary sources 2026-11-26. Two separate rulebooks apply and they are not the same document: **Wizards' Fan Content Policy** governs whether the channel may exist and how it may earn money, and **Scryfall's terms** govern how card images and data may be handled. Scryfall's image rules are the stricter of the two, and they are the ones a design-led account is most likely to break.

This file is the pre-publish checklist. Every post gets checked against the hard rules below before it leaves the queue.

---

## Hard rules — check every post

- [ ] The card image is **unmodified**: not cropped, recoloured, blurred, sharpened, desaturated, stretched or skewed.
- [ ] **Nothing is overlaid on the card image.** The @edhpod wordmark and all branding sit on the surrounding canvas, never on the card itself.
- [ ] The card's **copyright line and artist name are visible and unobstructed** in the rendered slide.
- [ ] The post is a **composite with original commentary**, never a bare card scan republished on its own.
- [ ] **No Wizards marks as standalone design elements** — no Magic logo, planeswalker symbol, mana symbols or guild symbols used as decoration. Marks appearing *inside* an unmodified card image are fine and must not be removed.
- [ ] **Oracle text is quoted from Scryfall data**, never from memory or paraphrase.
- [ ] **Prices were recomputed at publish time** and the caption describes them as estimates.
- [ ] **No follow-gating, paywall, email capture or survey** anywhere in the post or caption.
- [ ] Caption within limits: **2200 characters, 30 hashtags, 20 @-mentions**.
- [ ] If any card shown is from a **Universes Beyond** set, the caption carries the third-party acknowledgement (see below).

---

## Wizards of the Coast — Fan Content Policy

Policy last updated 15 November 2017 and unchanged since, despite periodic claims otherwise. It explicitly permits fan pages that use Wizards' art, which is precisely what this channel is.

**Required disclaimer, exact wording.** This must appear verbatim in the pinned post:

> EDHPod is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.

**Content must be free.** No payments, surveys, downloads, subscriptions or email registration may be required to access it. The policy goes further than most summaries note: your content must be free for others — Wizards included — to view, share and use "without paying you anything, obtaining your approval, or giving you credit." Do not build anything that depends on exclusivity over your own posts.

**Monetization that is expressly allowed:** sponsorships, ad revenue and donations, including Patreon and platform partner programmes, with no prior permission needed. Sponsorship conditions: no Wizards competitors, no offensive sponsors, label sponsorship clearly, keep shout-outs brief, and never imply Wizards endorses the sponsor.

**Monetization that is unresolved:** affiliate and referral commissions. The policy neither permits nor forbids them, while separately forbidding you to "sell or license your Fan Content to any third parties for any type of compensation." Decide deliberately; if used, disclose clearly and be prepared to drop them.

**Wizards may revoke permission at any time, for any reason or none**, after which content must come down. A reason not to build anything that would be painful to unwind.

A note on card art ownership: it is widely described as work-for-hire owned by Wizards, which would mean no individual artist clearance is needed. That is the common understanding but it is not stated in the policy, and the policy does tell you to respect third-party IP. Rely on the composite-with-commentary posture rather than on an ownership argument.

---

## Universes Beyond sets — decided 2026-11-26

The Introduction format covers the newest Magic set, and as of November 2026 that set is **Star Trek (`trk`, released 2026-11-13)**, a Universes Beyond crossover. Every card in it carries a `© 2026 CBS` line alongside the Wizards one.

The Fan Content Policy covers Wizards' IP. It does not grant rights to third-party IP, and it explicitly tells you to respect it. So a Universes Beyond card image is covered by the policy for the Wizards half and uncovered for the CBS half.

**Decision: post them anyway**, on the same composite-with-commentary posture used everywhere else, with two additional requirements:

- [ ] The post is **commentary on the card as a Magic card** — mechanics, price, deckbuilding. Never a Star Trek post that happens to use Magic cards.
- [ ] The caption carries a third-party acknowledgement alongside the standing disclaimer:

  > Star Trek and related marks are the property of CBS Studios. Fan commentary only, not affiliated with CBS or Paramount.

The exposure is acknowledged, not eliminated. CBS is a more litigious rights-holder than Wizards and has no fan content policy of its own. If a takedown ever arrives, comply immediately and drop the Introduction format back to the newest non-Universes-Beyond set.

Separately, the pipeline enforces this by default. `cheapest_printing()` in `pipeline/scryfall.py` skips Universes Beyond printings unless asked, so a Card of the Day or Budget Combo post never silently shops a UB printing just because it is a few cents cheaper — it falls back to one only if no normal printing exists. A Card of the Day post can opt in with `"allow_universes_beyond": true` in its `editorial.json`, and doing so means the caption needs the acknowledgement line above. `build_intro_post.py` sidesteps the question entirely: it pins each card to the newest set by code, because the whole point of the format is the new set.

---

## Scryfall — data and image terms

No API key exists; Scryfall identifies and blocks by application and IP, so good behaviour is the only protection.

**Required on every API request:** a `User-Agent` header identifying EDHPod, and an `Accept` header. Requests are expected to carry both.

**Rate limits**, from the live documentation rather than the older figures in circulation:

| Endpoint | Limit |
|---|---|
| `/cards/search`, `/cards/named`, `/cards/random`, `/cards/collection` | 2 per second |
| `/cards/manifest` | 10 per minute |
| all other API methods | 10 per second |
| `cards.scryfall.io` (image CDN) | no limit |

A 429 response locks access for 30 seconds; repeated overruns escalate to a temporary or permanent ban of the application. Cache for at least 24 hours and use the bulk data files for anything touching many cards.

**Image handling.** Use the `png` size at 744×1040 — transparent background, pre-rounded corners, and Scryfall's recommended size for high-quality composite content. Note that JPG sizes appear to be on a deprecation path in favour of new WEBP variants; `png` is safe. Do not cover, crop or clip the copyright line or artist name; do not distort; do not add watermarks or logos to the image.

**If a template ever uses `art_crop`**, that crop strips the artist name and copyright line, and Scryfall then requires both to appear elsewhere in the same interface. On a social post the post *is* the interface, so burn "Illus. {artist}" and the Wizards copyright line into the graphic. This is the most commonly violated rule among MTG design accounts. No current EDHPod template uses art crops.

**Prices.** EUR comes from Cardmarket, USD from TCGplayer, updated once per day. Scryfall's own wording is that bulk prices are collected every 12–24 hours and are "dangerously stale after 24 hours", to be used only to track trends or give a general estimate. This is why the Budget Combo total is recomputed at publish time and why captions call prices estimates.

**Also forbidden by Scryfall specifically:** gating data behind a channel follow, paywalling, and republishing or proxying the data without adding value. Scryfall is also actively screening for naive automated scraping, which is another reason to send a real identifying User-Agent and to use the bulk files.

---

## Current template status

The seven post templates are compliant as designed. The card sits in its own frame with branding on the surrounding canvas, no Wizards marks are used as decoration, and the three highlight icons on the channel overview board are generic shapes rather than Magic iconography. Keep both properties when designing the highlight covers.

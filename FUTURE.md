# Future work (out of the MVP scope)

- **Company enrichment** (website, sector via Wikidata) shown as context only, never as a ranking criterion.
- **Learning what a company means** from career trajectories, the way an anime recommender learns what a studio means from who watches it. Still no prestige score.
- **Interleaving** between rankers. With so few users it would have no statistical power today.
- **Propensity-based correction** (inverse propensity scoring) of the exploration slots. The propensity of every card is already stored on its events.
- **More job sources**: Ashby, Remotive, RemoteOK, Himalayas and We Work Remotely are listed in `app/config.py` with `enabled=False`. Each has its own terms and format, and enabling one is the owner's decision.
- **Editing education separately** from the CV review.
- **Monetization** (CV optimization, regional boosts) is out of scope.

"""
"Frequently bought together" using plain co-occurrence statistics (explainable, no deep learning).

  support(A,B)    = baskets containing both / all baskets
  confidence(A→B) = baskets containing both / baskets containing A
  lift(A→B)       = confidence / (baskets containing B / all baskets)    (>1 means bought together more than chance)
"""
from collections import Counter
from itertools import combinations

from sales.models import SaleItem

MIN_PAIR_COUNT = 3
MIN_BASKETS = 30


def compute_associations(business, min_pair_count=MIN_PAIR_COUNT, min_lift=1.2):
    baskets = {}
    for sale_id, product_id in SaleItem.objects.filter(
        sale__business=business, sale__status="COMPLETED"
    ).values_list("sale_id", "product_id"):
        baskets.setdefault(sale_id, set()).add(product_id)
    n = len(baskets)
    if n < MIN_BASKETS:
        return None, {"n_baskets": n}
    single, pairs = Counter(), Counter()
    for items in baskets.values():
        single.update(items)
        if len(items) > 1:
            pairs.update(combinations(sorted(items), 2))
    rules = []
    for (a, b), c in pairs.items():
        if c < min_pair_count:
            continue
        for x, y in ((a, b), (b, a)):
            confidence = c / single[x]
            lift = confidence / (single[y] / n)
            if lift >= min_lift:
                rules.append({"a": x, "b": y, "count": c, "support": c / n, "confidence": confidence, "lift": lift})
    rules.sort(key=lambda r: -r["lift"])
    return rules, {"n_baskets": n, "n_rules": len(rules)}

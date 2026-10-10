# Interview preparation — based on THIS implementation

Practise saying each answer in your own words and open the named file while you explain. Short model answers below.

## Django
**Why a service layer instead of logic in views?** Web pages, the REST API and the demo-data command all need identical rules (stock, price snapshots, invoice numbers). `sales/services.py::create_sale` is the single implementation; views only parse input and render output. It also makes the rules unit-testable without HTTP.

**How do you keep a sale consistent?** `create_sale` is wrapped in `transaction.atomic()`. If stock is insufficient `adjust_stock` raises and *everything* rolls back (test: `test_insufficient_stock_rolls_back_everything`).

**Why a custom User model on day one?** `AUTH_USER_MODEL` cannot be swapped safely after the first migration. Role lives on `BusinessMember`, not on the user.

**Where is middleware used?** `businesses/middleware.py` attaches `request.business` and `request.membership` from the user's memberships. DRF views do the same per request (`api/base.py::perform_authentication`) because JWT auth happens inside the view.

**Signals?** `accounts/signals.py` logs logins via `user_logged_in`. I avoided signals for business rules on purpose: explicit service calls are easier to follow and test than hidden side effects.

**Query optimisation you did?** `select_related`/`prefetch_related` in list views and API viewsets; aggregates and annotations in the database (`customers_with_stats`, KPIs) instead of Python loops; composite indexes matching `(business, -sale_date)` etc.; `bulk_create` for association rules.

**Why `.annotate()` + `.order_by()` after it?** Annotations with aggregates drop the model's default ordering, which makes pagination unstable (Django warned me); I order explicitly.

**Class-based vs function views?** CBVs with a small hierarchy (`BusinessViewMixin` → `TenantListView/CreateView/UpdateView`) remove repetition for the ~20 CRUD pages; custom flows (POS, reports) are `TemplateView`/`View`.

## PostgreSQL / database design
**How do you prevent overselling?** `SELECT … FOR UPDATE` on the product row inside the transaction, products locked in id order (no deadlocks), plus a `CHECK (current_stock >= 0)`. Proved with two real threads buying the last unit (`inventory/tests/test_concurrency.py`).

**Why a stock ledger *and* `current_stock`?** The ledger is the history/audit trail (and ML input); the column is a cache for fast reads, changed only in `adjust_stock`. `reconcile_stock` verifies they agree.

**Invoice numbers under concurrency?** `BusinessSequence` row locked with `select_for_update`, `UNIQUE(business, number)`. `max()+1` would race. Test with 4 simultaneous sales.

**Why snapshot prices on SaleItem?** Otherwise changing a product's price rewrites history and profit.

**Constraints you used?** UNIQUE per business (sku, category name…), conditional unique (barcode when not empty), CHECK constraints (quantities, amounts, paid ≤ total), `PROTECT` on history, `SET_NULL` for optional links.

**Index strategy?** Composite indexes starting with `business` because every query is tenant-filtered; `(business, product, -occurred_at)` for ledger lookups.

**Why DecimalField for money?** Binary floats cannot represent 0.1 exactly.

## REST API
**HTTP methods/status codes?** GET list/detail, POST create + actions (`/cancel/`, `/payments/`), PATCH partial update, DELETE (soft delete → 204). 400 validation/business rule, 401 unauthenticated, 403 wrong role, 404 not found *or another tenant's*, 429 throttled.

**Why 404 and not 403 for another tenant's object?** 403 confirms the object exists; 404 leaks nothing.

**JWT vs session?** Sessions for the browser app (with CSRF), short-lived JWT access + refresh for API clients. Login endpoint is throttled.

**Consistent errors?** `api/exceptions.py` wraps DRF's handler and maps `BusinessRuleError` → 400 with the same envelope.

**Serializer validation vs service validation?** Serializers validate shape/ownership (`BusinessPKField` restricts FKs to the tenant); services enforce business rules (stock, discount ≤ line, paid ≤ total) so rules hold no matter who calls.

**Pagination/filtering?** `PageNumberPagination` (20), `SearchFilter`, `OrderingFilter`, explicit query-param filters.

## Security
**IDOR / multi-tenancy — explain.** See `docs/ARCHITECTURE.md` §4: tenant from membership not URL; `for_business()` everywhere; forms/serializers restrict FK choices; services re-check; tests attack every detail URL and forged POST bodies.

**CSRF?** Django middleware on all POSTs; the JSON sale/purchase endpoints send `X-CSRFToken` (test proves requests without it get 403). JWT API is not cookie-based so not CSRF-exposed.

**File-upload security?** Extension allow-list, size limit, magic-number check, random filename, private storage, tenant-scoped authorised download view.

**What stops an employee seeing profit?** Permission map → views refuse (403), templates hide, and the serializer strips `purchase_price`; tests cover each.

**Brute force?** Login lockout via cache (5 failures/15 min), DRF throttles. Production would use a shared cache (Redis) for these counters.

**Secrets?** `.env` via django-environ, `.env` git-ignored, audit metadata scrubbed of password/token keys, `check --deploy` clean.

**CSV injection?** Cells beginning with `= + - @` are prefixed with `'`.

## Machine learning
**Why these models?** Forecasting (stock decisions), RFM (marketing/retention), anomaly flags (review unusual bills), co-occurrence (cross-selling): each maps to a question in the problem statement. No chatbot — it would add risk without core value.

**Why baselines first?** A complex model must earn its place. On the synthetic data a 28-day moving average beat gradient boosting for 7-day product totals, so the system selected it. I report that honestly.

**Data leakage — where could it happen and how is it avoided?** (1) random splits → I split by time; (2) features using future values → all lags ≥ horizon (unit test mutates the future and checks features are unchanged); (3) product means → computed from training rows only.

**Why not MAPE?** Daily demand has zeros → division by zero / meaningless. I use MAE, RMSE, WAPE, and score 7-day totals because that is what the owner orders against.

**Why Isolation Forest, and how do you evaluate it?** Unsupervised, handles several features without labels. No fraud labels exist, so no accuracy; output is a ranked "potentially unusual" list with reasons, validated by injecting labelled synthetic outliers (all 5 found) and by human review.

**K-Means details?** `log1p` (skew) + standardisation (units differ), k by silhouette, clusters described by real averages, not invented names. Silhouette ≈ 0.29 shows weak structure — so rule-based RFM segments are the primary labels.

**Retraining and versioning?** `ModelVersion` per run (algorithm, data window, metrics, artifact path), weekly Celery beat or on demand, old versions kept inactive, predictions tables reference the version.

**Limitations?** Synthetic validation only; stock-outs look like zero demand; no promotions/price features; cold-start products; one model per business; small data favours simple models.

## System design
**Scaling?** Stateless web processes behind a load balancer; PostgreSQL read replicas for reports; move throttle/cache to Redis; heavy ML and alerts already off the request path (Celery); partition or archive old ledger/sales rows; tenant-id indexes already first in every composite index.

**Background jobs/caching?** Celery+Redis for alerts/training; dashboards could cache KPI queries per business for 30–60 s.

**Why a monolith?** One transactional core (sale touches stock, payment, invoice, audit); microservices would turn that into distributed transactions for no benefit at this scale.

**Why shared-schema multi-tenancy vs database-per-tenant?** Simpler ops and migrations for many small shops; isolation is enforced in code and tests. Trade-off: a bug could leak across tenants (hence the heavy testing); database-per-tenant gives stronger isolation at higher operating cost.

**What would you do next?** Forecast-vs-actual monitoring, supplier lead times, partial returns, GST support, row-level security in PostgreSQL as a second isolation layer.

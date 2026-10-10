# REST API (v1)

Base URL: `http://127.0.0.1:8000/api/v1/` · Format: JSON · Auth: JWT bearer token.
A Postman collection is in `docs/LocalBiz_AI.postman_collection.json` (import it, set `base_url`, run **Login** first; the token is stored automatically).

## Authentication
```http
POST /api/v1/auth/token/        {"username": "demo_owner", "password": "Demo@12345"}
→ 200 {"access": "...", "refresh": "..."}
POST /api/v1/auth/token/refresh/  {"refresh": "..."}
```
Send `Authorization: Bearer <access>` on every call. Optional `X-Business-ID: <id>` selects one of *your own* businesses (a business you do not belong to is ignored). Login is throttled to 10/min; other limits: 3000/hour per user, 50/hour anonymous.

## Conventions
* **Pagination**: `?page=2` → `{"count", "next", "previous", "results"}` (20 per page).
* **Search / ordering**: `?search=pen`, `?ordering=-name` where listed below.
* **Status codes**: 200 OK · 201 Created · 204 No Content (soft delete) · 400 validation/business rule · 401 not authenticated · 403 role not allowed · 404 not found **or not yours** · 429 throttled.
* **Errors** always look like:
```json
{"error": {"status": 400, "message": "Validation failed.", "details": {"sku": ["A product with this SKU already exists."]}}}
{"error": {"status": 400, "message": "Not enough stock for Pen: 20 available, 21 requested.", "details": null}}
```

## Endpoints
| Method & path | Who | Notes |
|---|---|---|
| `GET /me/` | any member | your memberships and active business |
| `GET/POST /categories/`, `GET/PATCH/DELETE /categories/{id}/` | view: all · write: manager+ | `search`, `ordering` |
| `GET/POST /suppliers/`, `…/{id}/` | manager+ | |
| `GET/POST /products/`, `GET/PATCH/DELETE /products/{id}/` | view: all · write: manager+ | `search` (name/sku/barcode), `ordering`, `?low_stock=true`, `?category=`, `?is_active=`. `POST` accepts `opening_stock`. `current_stock` is read-only. `DELETE` = soft delete. `purchase_price` is hidden from employees. |
| `GET /inventory/transactions/` | manager+ | the stock ledger; `?product=` |
| `POST /inventory/transactions/adjust/` | manager+ | `{"product", "txn_type": "ADJUSTMENT/DAMAGE/RETURN_IN/RETURN_OUT", "quantity", "note"}` |
| `GET/POST /purchases/` | manager+ | `{"supplier", "paid_amount", "items":[{"product","quantity","unit_cost"}]}` adds stock |
| `GET/POST /customers/`, `…/{id}/` | view: all · write: manager+ | includes `total_spent`, `outstanding` |
| `POST /customers/{id}/receive-payment/` | manager+ | `{"amount","method"}` applied to oldest unpaid bills first |
| `GET /sales/`, `GET /sales/{id}/` | all | `?status=`, `?customer=`, `?date_from=`, `?date_to=`, `search` |
| `POST /sales/` | all | see below |
| `POST /sales/{id}/cancel/` | manager+ | restores stock through the ledger |
| `POST /sales/{id}/payments/` | manager+ | `{"amount","method"}` |
| `GET/POST /expense-categories/`, `/expenses/` | owner | |
| `GET /analytics/kpis/` | manager+ | profit/expenses/inventory value only for the owner |
| `GET /analytics/insights/` | manager+ | rule-based insights |
| `GET /reports/{slug}/?start=&end=` | manager+ (financial: owner) | slugs: `daily-sales monthly-sales profit-loss inventory low-stock customers suppliers expenses tax` |
| `GET /ml/demand-forecasts/` | manager+ | `?status=SHORTAGE_RISK` |
| `GET /ml/sales-forecast/` · `/ml/customer-segments/` · `/ml/anomalies/` | manager+ | |
| `GET /ml/recommendations/?product=ID` | all | frequently bought together |
| `POST /ml/train/` | owner | retrains all models synchronously |

### Example: create a sale
```http
POST /api/v1/sales/
{"customer": 5, "payment_method": "UPI", "amount_paid": "100.00",
 "items": [{"product": 12, "quantity": 3, "discount": "5.00"}, {"product": 14, "quantity": 1}]}
→ 201 {"id": 88, "invoice_number": "INV-2026-000088", "total": "...", "balance": "...", "payment_status": "Partial", "items": [...]}
```
The whole operation (sale, items, stock ledger, payment, invoice, audit) is one database transaction.
The PDF invoice is available in the web app at `/sales/{id}/invoice.pdf`.

# Git history and resume wording

## Commit the project in meaningful steps
You received the finished code, so recreate a readable history yourself (recruiters do look at it). Run these from the project folder; skip the empty-folder warnings.

```powershell
git init
git add .gitignore .env.example requirements.txt manage.py config scripts
git commit -m "Initial project setup: Django 5.2, PostgreSQL, split settings, Celery config"

git add core accounts businesses audit
git commit -m "Authentication, multi-tenant architecture, roles and audit log"

git add catalog
git commit -m "Catalog module: categories, suppliers, products"

git add inventory
git commit -m "Inventory: append-only stock ledger, purchases, adjustments, reconcile command"

git add customers sales templates static/js static/css
git commit -m "Sales and customers: atomic checkout, payments, credit balances, PDF invoices, POS screen"

git add finance
git commit -m "Expenses with validated receipts and profit calculation"

git add analytics notifications
git commit -m "Dashboard KPIs, rule-based insights, reports with CSV export, notifications"

git add ml
git commit -m "ML: demand and sales forecasting, RFM/K-Means segmentation, anomaly detection, associations"

git add api
git commit -m "REST API: JWT auth, tenant-scoped viewsets, throttling, consistent errors"

git add -A
git commit -m "Tests, Docker setup and documentation"
```
(The tests live inside each app's `tests/` folder, so some are committed earlier; that is fine.)
Then create an empty GitHub repository and push: `git branch -M main`, `git remote add origin <url>`, `git push -u origin main`.
**Never commit `.env`** (it is in `.gitignore`).

## Resume bullet (use after you have run the project and can explain it)
> Built **LocalBiz AI**, a multi-tenant small-business management and analytics platform (Django, Django REST Framework, PostgreSQL): ledger-based inventory, atomic checkout with PDF invoicing, credit/customer balances, role-based access control with tenant isolation, JWT REST API, and ML-driven demand forecasting, RFM customer segmentation and anomaly flagging; 115 automated tests including concurrency tests.

Shorter version: *Multi-tenant Django/DRF/PostgreSQL business platform with stock ledger, atomic sales, RBAC, REST API and scikit-learn forecasting/segmentation/anomaly detection (115 tests).*

### Be honest and precise
* Say the demo data is **synthetic**. If you later get a real shop to try it, add that (it is a big credibility boost).
* Do **not** quote an "accuracy". If asked, explain: baselines vs models, hold-out period, WAPE, and that a baseline won on the synthetic data (that shows judgment).
* Only claim what you can demo: Celery/Redis and Docker are *configured*; say so unless you have run them yourself.
* Prepare a 2-minute demo: register → add products → sell on credit → receive payment → invoice PDF → dashboard → AI Insights → log in as employee and show what is hidden → show the failing "Business A reads Business B" test.

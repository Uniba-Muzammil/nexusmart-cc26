# Member B Handoff Guide (Cleaning + Data Quality)

Yeh document 3 logon ke liye hai: **B (aap)** GitHub par kya dalein, **A (pipeline / Airflow / Postgres)** isay kaise chalayein, **C (SQL / warehouse / FactSales)** kya rules maanein.
Har cheez jo yahan "tested" likhi hai woh maine chala kar dekhi hai (details Section 9 mein). Jo test nahi hui woh wahan alag likhi hai.

---

## 1. Ek nazar mein: B kya de raha hai

| Cheez | File | Kaun use karega |
|---|---|---|
| Cleaning code | `src/clean/clean_all.py`, `toolkit.py`, `nx_config.py` | A (DAG task) |
| Type contract (har column ka type) | `src/clean/clean_schema.py`, `sql/clean_schema.sql` | A (load), C (queries) |
| Postgres loader | `tools/load_postgres.py` | A |
| Sensitivity table | `src/clean/sensitivity.py` -> `out/sensitivity.csv` | B, judge |
| DQ report PDF | `src/clean/make_dq_report.py` -> `docs/data_quality_report.pdf` | B, judge |
| Hour-6 rehearsal | `tools/stress_test.py` | B |
| FactSales example | `sql/example_fact_sales.sql` | C |
| Docs | `README_CLEANING.md`, `CHANGES.md`, yeh guide | sab |
| Sample outputs | `out_samples/` (dq_log, reject, sensitivity) | judge / reviewer |

Clean output ka nateeja: **11 clean tables + dq_log + reject**, 9 raw CSV se. Naam aur columns playbook ke mutabiq hain.

**Naya in v3:** `nx_config.py` (pehle `config.py`, Airflow ke `config/` folder se takrata), `clean_schema.py`, `load_postgres.py`, `example_fact_sales.sql`.

---

## 2. GitHub par kaise dena hai (B ke steps)

### 2.1 Repo mein jagah
```
repo/
  src/clean/    nx_config.py toolkit.py clean_all.py clean_schema.py sensitivity.py make_dq_report.py README_CLEANING.md
  tools/        stress_test.py load_postgres.py
  sql/          clean_schema.sql example_fact_sales.sql
  docs/         data_quality_report.pdf HANDOFF_MEMBER_B.md
  out_samples/  dq_log.csv reject.csv sensitivity.csv
  requirements-clean.txt
  CHANGES.md
  .gitignore
```
Agar A ne pehle se `sql/` ya `docs/` bana rakha hai to unhi mein rakhein, folder naam badalne ki zaroorat nahi.

### 2.2 Commands
```bash
git checkout main && git pull
git checkout -b feature/cleaning-b

# zip kholein aur repo mein copy karein
unzip memberB_cleaning_v3.zip -d /tmp/b
cp -r /tmp/b/* .

# purani config.py ab nahi chahiye (naam badal kar nx_config.py ho gayi)
git rm -f src/clean/config.py 2>/dev/null || true

# commit se pehle ek baar poori chain chalayein (Section 3)
git status                 # sirf apni files dikhni chahiyen, data/ ya out/ nahi
git add src/clean tools sql docs out_samples requirements-clean.txt CHANGES.md .gitignore
git commit -m "cleaning: pipeline v3 (type contract, postgres loader, split payments, unit_cost, margin sensitivity, DQ report)"
git push -u origin feature/cleaning-b
```
Phir GitHub par **Pull Request** kholein (base: main), A aur C ko reviewer lagayein. PR description mein Section 8 ka message paste kar dein.
Merge ke baad: `git tag cleaning-v3 && git push --tags` (taake Hour 6 se pehle ek stable version pakda rahe).

### 2.3 Kya commit NAHI karna
`.gitignore` mein yeh rakhein:
```
data/
out/
stress/
__pycache__/
*.pyc
.env
```
- `data/` (raw CSV): bara hai aur competition data hai, repo mein nahi jata.
- `out/`: har run par dobara banta hai (idempotent), commit karne se sirf diff ka shor bante hai.
- `out_samples/`: chhote samples jo reviewer / judge ko dikhane ke liye hain. Yeh commit hon.
- Commit se pehle `out_samples/` mein dekh lein ke koi password / personal email-phone nahi hai.

### 2.4 `requirements-clean.txt`
```
pandas>=2.2
numpy
reportlab          # sirf PDF report ke liye
psycopg2-binary    # sirf Postgres load ke liye
```

---

## 3. Chalane ke commands (sab ek jagah)

```bash
pip install -r requirements-clean.txt

python src/clean/clean_all.py data out                       # 1. saaf karo   -> out/*.csv, dq_log.csv, reject.csv
python src/clean/clean_schema.py check out                   # 2. type contract check (fail ho to exit code 1)
python tools/load_postgres.py out "postgresql://user:pw@host:5432/db"   # 3. Postgres mein load (A)
python src/clean/sensitivity.py data out                     # 4. sensitivity.csv
python src/clean/make_dq_report.py out docs/data_quality_report.pdf data  # 5. PDF report
```
Asli data par pehli baar: **step 1 se 5 chalayein aur PDF ke numbers ko is guide ke numbers se milayein** (NMV 1,199,960,496, Net Revenue 1,142,292,237, Return Rate 5.148%, Cancel Rate 9.160%).

---

## 4. A ke liye: pipeline mein kaise lagana hai

### 4.1 Kya milta hai
- Python function jo CSV folder lekar CSV folder deta hai. Database ka koi hissa cleaning code mein nahi, isliye Airflow, cron ya laptop, kahin bhi chalta hai.
- Postgres mein 2 schema: `clean` (11 tables) aur `audit` (`dq_log`, `reject`).

### 4.2 Airflow task order
```
validate_raw -> clean -> check_contract -> load_postgres -> sensitivity -> dq_report
                                              |
                                              +-> (C ki SQL / dbt / warehouse build)
```
Snippet (Airflow mein maine nahi chalaya, sirf functions ko directly chalaya hai; apne DAG ke hisaab se adjust karein):
```python
import sys; sys.path[:0] = ["/opt/airflow/repo/src/clean", "/opt/airflow/repo/tools"]
import clean_all, clean_schema, load_postgres

def validate_raw():
    problems = clean_all.validate_raw("data")
    if problems: raise ValueError(problems)

def clean():           clean_all.run("data", "out")          # quality gate fail ho to khud exception deta hai
def check_contract():
    p = clean_schema.check("out")
    if p: raise ValueError(p)
def load():            load_postgres.load("out", DSN)
```
### 4.3 Zaroori baatein
| Baat | Matlab |
|---|---|
| **Fail hona theek hai** | `validate_raw` (column gayab), quality gate (kisi table ke 1% se zyada reject) aur contract check **jaan boojh kar** task fail karte hain. Chup chaap kharab data warehouse mein na jaye. |
| **Dobara chalana safe** | Cleaning ka output identical aata hai; loader `TRUNCATE + COPY` karta hai, ek transaction mein (ya sab load ya kuch nahi). Do baar load karne par row counts wohi. |
| **IDs TEXT hain** | `O0000001`, `C000001` jaise. Integer mein cast na karein. `city_id`, `ship_city_id`, `birth_year` INTEGER hain. |
| **Foreign key database mein nahi** | `orders.customer_id` aur `order_items.product_id` ke orphan rows jaan boojh kar rakhe gaye hain (flag `orphan_customer` / `orphan_product` = 1). FK lagayenge to load fail hoga. |
| **Empty = NULL** | CSV mein khali cell NULL ban jata hai. |
| **Settings env var se** | `NX_DATE_MIN`, `NX_DATE_MAX` (valid date window), `NX_GATE_SCALE` (reject limit ka multiplier). Code nahi badalna. Airflow mein `env` ya Variable se do. |
| **Sirf yeh install chahiye** | pandas, numpy; PDF ke liye reportlab; load ke liye psycopg2-binary. |

### 4.4 A ko kya NAHI karna
- `out/*.csv` ko haath se edit na karein.
- Loader ke bagair khud `to_sql` se types na guess karein, dates aur integer columns kharab hote hain. `sql/clean_schema.sql` hi sach hai.

---

## 5. C ke liye: FactSales aur dimensions ke rules

`sql/example_fact_sales.sql` ek **chali hui, verify ki hui** query hai (view `clean.v_fact_sales`). Row count bilkul `order_items` ke barabar aata hai, aur revenue, shipping fee, refund sab clean tables se reconcile hote hain.

### 5.1 Grain
FactSales ka grain = **order line** (`order_items` ki ek row). `orders.order_total` order level ki cheez hai, usay line rows par sum na karein (kai guna ho jayega). Line ka revenue `net_amount` hai.

### 5.2 Wo 7 rules jinke bina numbers galat honge
| # | Rule | Kyun |
|---|---|---|
| 1 | Payment: `JOIN payments ON order_id AND is_primary = 1` | 4,815 orders ki 2 payment rows hain (split payment, 60/40). Bina `is_primary` ke order double ginega. PaymentMethod ka sawal isi par depend karta hai. |
| 2 | `CostAmount = unit_cost * quantity` (`products.cost_price` nahi) | `unit_cost` mein orphan product lines ka estimate bhi hai. `cost_price` se 932 lines ki cost NULL/0 ho jati hai aur margin 0.22 pt upar jata hai. |
| 3 | Returns: `WHERE is_valid_return = 1`, aur pehle `order_item_id` par GROUP BY, phir join | `Rejected` status valid return nahi (spec). Seedha join karne se line duplicate ho sakti hai. |
| 4 | Orphan keys: `orphan_customer=1` -> customer key `-1`; `orphan_product=1` -> `-1`; `orphan_seller=1` -> `-1`; `ship_city_id IS NULL` -> `-1` | Revenue real hai, line delete na karein. Dim mein Unknown (-1) row banayein. |
| 5 | `customer_id` pehle se **master id** hai | Duplicate customers merge ho chuke. `customer_id_orig` sirf audit ke liye, dimension ki key na banayein. Same product ke liye `product_id` aur `product_id_orig`. |
| 6 | Shipping fee: order level fee ko lines mein `gross_amount` ke hisaab se taqseem karein (example SQL mein hai) | Warna fee line count se guna ho jati hai. |
| 7 | Dates sab `DATE` (yyyy-mm-dd); `order_date` window 2024-01-01..2025-06-30 | Sab repair/reject ho chuka hai, dimension Date ko aur filter nahi chahiye. |

### 5.3 Dimensions ke liye
| Dimension | Source | Note |
|---|---|---|
| DimCustomer | `clean.customers` + Unknown (-1) | master rows hi hain; `phone`/`gender` kuch NULL / `Unknown` hain, theek hai |
| DimProduct | `clean.products` + Unknown (-1) | `cost_imputed = 1` wale products ka cost estimate hai |
| DimSeller | `clean.sellers` + Unknown | `rating` NULL jaan boojh kar (quality signal impute nahi kiya) |
| DimLocation | `clean.locations` + Unknown | `latitude/longitude` NULL jahan Pakistan se bahar thay |
| Status / channel / method | labels pehle se standard (`Delivered`, `Cancelled`, `In Transit`, ...) | seedha group by |

### 5.4 C ke apni SQL ke 3 reconciliation checks (har build ke baad)
```sql
SELECT count(*) FROM <FactSales>;                    -- = SELECT count(*) FROM clean.order_items
SELECT sum(net_amount) FROM <FactSales>;             -- = SELECT sum(net_amount) FROM clean.order_items
SELECT count(*) FROM clean.payments WHERE is_primary = 1;   -- = count(*) FROM clean.orders
```
Agar inme se koi nahi milta, to join mein fan-out hai (aksar payments ya returns).

---

## 6. Naye columns ka matlab (flags)
| Column | Values | Matlab |
|---|---|---|
| `orders.date_repair` | khali / `SHIPPED_DATE` / `PAYMENT_DATE` | order date kahan se banayi gayi |
| `orders.orphan_customer` | 0/1 | customer table mein nahi mila |
| `order_items.orphan_product` / `orphan_seller` | 0/1 | product / seller table mein nahi mila |
| `order_items.qty_fix`, `price_fix` | khali ya fix ka tareeqa | quantity / price kaise theek hui |
| `order_items.cost_source` | `PRODUCT`, `PRODUCT_IMPUTED`, `NO_PRODUCT_COST_ESTIMATE` | cost kahan se aayi |
| `payments.n_payments` | 1 ya 2 | order ki kitni payment rows |
| `payments.is_primary` | 0/1 | har order ki ek row = 1 |
| `shipping.date_fix`, `fee_imputed` | flag | delivered date NULL ki gayi / fee impute hui |
| `returns.is_valid_return` | 0/1 | `Rejected` = 0 |
| `products.cost_imputed` | 0/1 | cost estimate hai |

---

## 7. Hour-6 (naya data aane par) runbook

Maqsad: naya data aaye to 15-20 minute mein clean + report taiyar.

1. Naya data `data/` mein rakhein. `python src/clean/clean_all.py data out`.
2. Agar **fail** ho: message padhein.
   - `missing columns ...` -> raw file ka header badal gaya; `nx_config.REQUIRED_COLUMNS` aur `clean_all.py` ka us table ka hissa dekhein.
   - `quality gate: orders rejected X%` -> pehle `out/reject.csv` aur `dq_log.csv` padhein. Wajah samajh kar hi `NX_GATE_SCALE=3` lagayein.
3. Chal jaye to `out/dq_log.csv` mein dekhein:
   - `UNMATCHED LABELS` -> naye spelling `nx_config.LABELS` mein sahi category ke neeche add karein (normalised form: lowercase, `&` -> `and`, punctuation nahi).
   - `UNRECOGNISED DATE FORMAT` -> naya pattern `toolkit._PATTERNS` mein.
4. Dobara `clean_all.py` chalayein jab tak dono khali na hon.
5. `clean_schema.py check out`, phir load, phir `sensitivity.py`, phir `make_dq_report.py`.
6. PDF ke Section 8 ke numbers (dates, customers, orphan cost, cost>list) naye data ke aaye hain, README ka "Key assumptions" block un numbers se update karein.
7. **Pehle se riyaz:** `python tools/stress_test.py data` (mutated copy banata hai: naye labels, naye date formats, `N/A`, extra column, duplicate keys, orphans), phir `clean_all.py stress/data stress/out`. Chal jana chahiye aur dq_log mein sab surprises aane chahiyen.

### 7.1 Kya cover hai aur kya nahi (sach)
| Cover hai | Cover nahi (khud karna hoga) |
|---|---|
| naye label spelling (fuzzy match, nahi mile to `Unknown` + dq_log) | naye label ka sahi category dena (insaan decide karega) |
| `NULL`, `N/A`, `-` jaise strings, naye date formats (`2024.05.12`, `20240512`, time wali) | bilkul ajeeb date format (dq_log mein aata hai, phir pattern add karein) |
| extra / reorder columns | **required column ka naam badalna**: yeh jaan boojh kar fail karta hai |
| duplicate primary key, orphans, naye cities | **naya table** ya naya relationship |
| alag date window (env var) | slash dates ka mm/dd/yyyy hona (hum dd/mm/yyyy maante hain) |
| IDs ka naya format (TEXT) | totally naye business rule (jaise naya discount code format) |

---

## 8. Team ko bhejne wale messages (copy-paste)

**A ko:**
> Cleaning v3 branch `feature/cleaning-b` mein hai. Order: `clean_all.py data out` -> `clean_schema.py check out` -> `tools/load_postgres.py out <DSN>`. Tables `clean.*` aur `audit.*` mein load hote hain, types `sql/clean_schema.sql` mein hain. IDs TEXT hain, orphan rows par FK mat lagana. Settings env var se: `NX_DATE_MIN/MAX`, `NX_GATE_SCALE`. `config.py` ka naam ab `nx_config.py` hai. Quality gate / contract fail hone par task fail hona theek hai. Hour 6 mein sirf `clean_all.py` dobara chalani hai.

**C ko:**
> FactSales ka grain order line hai. 4 rules: (1) payments sirf `is_primary = 1`, (2) `CostAmount = unit_cost * quantity`, (3) returns mein `is_valid_return = 1` aur pehle order_item par GROUP BY, (4) orphan flags ko Unknown (-1) mein map karo, line delete nahi karni. `sql/example_fact_sales.sql` chali hui example hai. Apni build ke baad 3 checks: line count, sum(net_amount), primary payment count, section 5.4 mein hain.

---

## 9. Tested vs. NOT tested (sach)

**Tested (maine chalaya):**
- Poori chain (clean, contract check, load, sensitivity, PDF report) ek chhote synthetic data par (1,500 orders, 3,000 lines; dirty dates, split payments, orphans, duplicates, bad costs shamil).
- Asli (embedded) Postgres par: DDL, `COPY`, do baar load = same counts, types (`date`, `integer`, `numeric`), `is_primary` = ek row per order, totals pandas se match.
- `example_fact_sales.sql` Postgres par: row count = order_items, revenue / shipping / refund reconcile.
- Stress data (naye labels, formats, `N/A`, extra column, duplicate keys, orphans) par pipeline nahi giri, contract OK, naye labels dq_log mein aaye.
- `config.py` -> `nx_config.py` rename ke baad output identical (sirf dq_log ke text mein naam badla).
- Cleaning dobara chalane par output byte-identical.

**NOT tested:**
- **Asli 160k-row data is chat mein nahi tha**, isliye asli numbers (NMV waghera) par yeh nayi files (`clean_schema`, loader) maine nahi chalayi. Aap Section 3 ke 5 commands ek baar asli data par chalayein; cleaning code wohi hai jo pehle asli data par verify hua tha, nayi cheezein sirf contract/loader/rename hain.
- Airflow ke andar (A ka DAG).
- C ki asli SQL (mere paas nahi hai).
- `docs/data_quality_report.pdf` is zip mein **purani generation** ki hai: us mein `config.LABELS` likha hai. Asli data par `make_dq_report.py` dobara chalane se naya text aa jayega.

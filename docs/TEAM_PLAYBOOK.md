# NexusMart Datathon: Team Playbook (4 members, parallel kaam)

Deadline: **Sunday 18 Oct, 6:00 PM**. Late = har 10 minute par 5% minus. Hamara target: **3:00 PM tak submit**, 4:00 PM se zyada late kabhi nahi.
Finals (agar shortlist hue): 22 Oct, UBIT, 5 min presentation + 3 min Q&A.

---

## 0. Score kahan se aata hai (100 points)

| Points | Kya | Kaun zimmedar |
|---|---|---|
| 30 | Power BI dashboard (.pbix + PDF of all pages) | D (C madad karta hai) |
| 20 | Airflow pipeline: ek README se chalay, order mein, dobara chalay | A |
| 15 | Cleaning (code se) + Data Quality Report (before/after counts) | B |
| 10 | SQL database + star schema + diagram | C |
| 10 | Correct answers (hamare numbers unki answer key se milen, revenue ±1%, rates ±0.5 pt) | B + C |
| 10 | Business insights + advice | B |
| 5 | Code + README | A |

Tie-breaker: pipeline score, phir live Q&A. **Penalty:** missing deliverable -5 se -15, non-reproducible setup -10, haath se data badalna = disqualify.

### Disqualify hone ki wajahen (poori team yaad rakhe)
1. Excel mein ya database mein haath se data theek karna. **Sab cleaning sirf Python code se.**
2. Power Query mein asli cleaning. Wahan sirf rename aur data type.
3. Pre-built dashboard template.
4. Bahari dataset ya copy kiya hua solution. Sirf diya gaya data (aur diya gaya holiday calendar).
5. Kisi aur team se kuch share karna.
6. Password code mein likhna. Passwords sirf `.env` mein.

AI tools allowed hain, lekin **har member ko apna hissa samjha kar explain karna aana chahiye**.

---

## 1. Noobs ke liye 6 cheezen

- **CSV:** raw files (9 files, ~860,000 rows). Inhe kabhi edit nahi karna.
- **Python/pandas:** wo code jo data saaf karta hai. Har fix ka record `dq_log` mein jaata hai.
- **PostgreSQL:** database jahan saaf data rakha jata hai. Hamare 4 "schemas" (folders): `raw`, `clean`, `mart`, `audit`.
- **Star schema:** ek bada table (`FactSales`, har row = ek order line) aur 5 chhote tables (`DimDate`, `DimCustomer`, `DimProduct`, `DimSeller`, `DimLocation`). Dimensions aapas mein link nahi hote.
- **Airflow:** ek manager jo tasks ko ek ke baad ek khud chalata hai. Har task ek Python function hai. Poori series ko **DAG** kehte hain.
- **Docker:** ek dabba jisme Airflow aur Postgres chalte hain, taake judges ke computer par bhi bilkul waisa hi chale.

---

## 2. Roles

| | Role | Pehla kaam | Phir |
|---|---|---|---|
| **A** | Pipeline lead | Docker + Airflow + Postgres chalao | DAG, README, final fresh-run test, packaging |
| **B** | Cleaning + Insights lead | Cleaning code samjho aur chalao | DQ report, 15 sawaal ke jawab, insights, 2-3 page report |
| **C** | Warehouse lead | Mart SQL (5 dims + fact) | ER diagram, quality checks, metric SQL views, RFM, seller score |
| **D** | BI lead | Wireframe, DAX measures list, Power BI + Postgres connection | 7 pages, PDF export, presentation |

Sab milkar: har ek ko dusron ka kaam 10 minute mein explain karna aana chahiye.

---

## 3. Shared contract (sab isi par ittefaq karte hain, badalna ho to poori team ko batao)

### 3.1 Repo structure
```
cc26/
  docker-compose.yaml   .env (git mein NAHI)   .env.example   .gitignore
  dags/        nexusmart_dag.py                        <- A
  src/clean/   clean_all.py  toolkit.py  config.py     <- B
  sql/         01_schemas.sql 02_dims.sql 03_fact.sql 04_checks.sql 05_metrics.sql  <- C
  bi/          NexusMart.pbix  dashboard.pdf           <- D
  docs/        README.md  data_quality_report.*  insights.pdf  star_schema.png
  data/        (9 raw CSVs)       out/ (cleaned CSVs)
```
Git rule: har banda **sirf apna folder** edit kare, apni branch par (`pipeline`, `cleaning`, `warehouse`, `bi`). Merge A karta hai. Din mein kam az kam 3 baar `git pull`.

### 3.2 Database schemas
- `raw`: CSVs bilkul jaise hain, sab text columns.
- `clean`: cleaning ka output (table naam = CSV naam jo `out/` mein banti hain: `customers, customer_map, products, product_map, sellers, locations, orders, order_items, payments, shipping, returns`).
- `audit`: `dq_log` aur `reject`.
- `mart`: `dim_date, dim_customer, dim_product, dim_seller, dim_location, fact_sales`.

### 3.3 Mart ke columns (spec ke mutabiq)
- Har dimension ka surrogate key integer hai aur **-1 = "Unknown" row**.
- `DimDate`: DateKey (yyyymmdd), Date, Day, DayName, Week, Month, MonthName, Quarter, Year, IsWeekend, IsRamadan, IsEidUlFitr, IsEidUlAdha, Is14August, Is1111, IsBlackFriday. Dates: 11 Mar-9 Apr 2024 aur 1-30 Mar 2025 (Ramadan); 10-12 Apr 2024 aur 31 Mar-2 Apr 2025 (Eid-ul-Fitr); 17-19 Jun 2024 aur 7-9 Jun 2025 (Eid-ul-Adha); 14 Aug; 11 Nov; 29 Nov 2024 (Black Friday).
- `DimCustomer`: CustomerKey, CustomerID (master), FullName, Email, Phone, Gender, RegistrationDate, BirthYear, City/Province/Region (customer ke registered city se), Segment (RFM). SCD Type 1 = naya data aaye to purani row overwrite.
- `DimProduct`: ProductKey, ProductID, ProductName, Category, SubCategory, Brand, ListPrice, WeightKg.
- `DimSeller`: SellerKey, SellerID, SellerName, JoinDate, Tier, City/Province, Rating.
- `DimLocation`: LocationKey, CityID, City, Province, Region, PopulationTier.
- `FactSales` (grain = ek order line): DateKey, CustomerKey, ProductKey, SellerKey, LocationKey (**ship city**), OrderID, OrderItemID, Quantity, UnitPrice, GrossAmount, DiscountAmount, NetAmount, CostAmount, ShippingFee, ShippingDays, IsCancelled, IsReturned, ReturnedAmount, ReturnDateKey, ReturnReason, ReturnStatus, OrderStatus, PaymentMethod, Channel.

### 3.4 Fact banane ke rules (C yeh code karta hai, baqi sab yeh jaanein)
- Return info **line level par aggregate**, sirf valid (non-Rejected) returns. Grain nahi tootna chahiye (row count `clean.order_items` ke barabar rahe).
- `CostAmount = cost_price x quantity`. `NetAmount = GrossAmount - DiscountAmount`.
- Shipping fee order level par hai. Isay lines mein **gross ke hisaab se taqseem** karo taake sum per order = fee (double count nahi). Jin orders ki shipping row nahi (cancelled), fee = 0.
- `ShippingDays` order level hai. DAX mein average per order lo, sum kabhi nahi.
- Ek order ki 2 payment rows (4,815 orders): ek chuno. Rule: Paid/Refunded ko Cancelled/Pending par tarjeeh, phir sab se nayi `payment_date`.
- Orphan customer/product (`C9xxxx`, `P9xxxx`) = Unknown key (-1). Line delete nahi hoti.
- `LocationKey` khali ship_city_id = -1.

---

## 4. Waqt ki taqseem (ab 3:50 PM Sat se, sab target times hain)

| Waqt | Kya | Sync point |
|---|---|---|
| Sat 4:00-5:00 PM | **Sab:** software install, GitHub repo, `docs/` mein ye playbook, `.env`. Har banda apna Section parh kar apna 1st task shuru. | |
| 5:00-8:00 PM | **Phase 1** (4 log parallel, Section 5-8) | 8:00 PM: A ka Docker chal raha ho, B ka `out/` bana ho, C ka mart SQL sample par chal chuka ho, D ka Power BI Postgres se connect ho. |
| 8:00-11:30 PM | **Phase 2:** DAG mein sab 7 tasks jodo, end-to-end chalao | 11:30 PM: DAG ek click se green. Mart tables bharay. |
| 11:30 PM-12:30 AM | D pages banata hai; B answers likhta hai; C views banata hai; A README ka pehla draft | |
| 12:30 AM-6:30 AM | **Neend.** Do shifts: A+C 12:30-5:30, B+D 1:30-6:30. Thake log bugs banate hain. | |
| **Hour-6 data aate hi** | Section 11 ka drill | |
| Sun 7:00-11:00 AM | D: pages 4-7. B: insights + DQ report. C: sab checks. A: README test | |
| **11:00 AM** | **Feature freeze.** Ab koi naya feature nahi, sirf bug fix. | |
| 11:00 AM-1:00 PM | Poori chain saaf folder mein chalao. PDF export. Report final. | |
| 1:00-3:00 PM | Packaging, submission, backup copy. **Submit karo.** | |
| 3:00-6:00 PM | Sirf bachaao ka buffer. Naya kaam nahi. | |

(Hour-6 ka drop kab aata hai wo organizers batayenge. Jab aaye, schedule us hisaab se aage-peeche karo.)

---

## 5. Person A: Pipeline lead

### A1. Install (30 min)
Docker Desktop, Git, Python 3.11, VS Code. Docker Desktop mein WSL2 on rakho.

### A2. Folder + Airflow (1 ghanta)
```powershell
mkdir cc26; cd cc26
mkdir dags,logs,plugins,config,data,sql,src,out,docs,bi
# Airflow version pin karo (stable ka latest version badal sakta hai aur imports badal jaate hain)
iwr https://airflow.apache.org/docs/apache-airflow/2.10.5/docker-compose.yaml -OutFile docker-compose.yaml
"AIRFLOW_UID=50000`nWH_PW=ChooseAStrongOne" | Out-File .env -Encoding ascii
```
`docker-compose.yaml` mein ye badlav karo:
1. `x-airflow-common` ke `environment:` mein: `WH_HOST: wh`, `WH_USER: wh`, `WH_PASSWORD: ${WH_PW}`, `WH_DB: wh`, `DATA_DIR: /opt/airflow/data`, `_PIP_ADDITIONAL_REQUIREMENTS: "pandas sqlalchemy psycopg2-binary"`.
2. `volumes:` mein `./src:/opt/airflow/src`, `./sql:/opt/airflow/sql`, `./data:/opt/airflow/data`, `./out:/opt/airflow/out`.
3. `services:` mein warehouse:
```yaml
  wh:
    image: postgres:16
    environment: {POSTGRES_USER: wh, POSTGRES_PASSWORD: "${WH_PW}", POSTGRES_DB: wh}
    ports: ["5433:5432"]
    volumes: ["wh-data:/var/lib/postgresql/data"]
```
aur neeche `volumes:` mein `wh-data:`.

Phir:
```powershell
docker compose up airflow-init
docker compose up -d
```
Airflow UI: http://localhost:8080 (login airflow/airflow). Agar login na ho to `docker compose logs airflow-webserver` se error bhejo.
Power BI/Python (apne computer se) Postgres ke liye: host `localhost`, port **5433**, user `wh`. Airflow ke andar se host `wh`, port 5432.

### A3. DAG skeleton (1 ghanta), task naam spec wale
`extract -> validate_raw -> clean -> load_staging -> build_dimensions -> build_fact -> quality_checks`
Har task ek khali Python function jo pehle sirf "ok" print kare. DAG green hona chahiye. Settings: `retries=2`, `retry_delay=2 min`, `catchup=False`, `schedule=None`. Credentials sirf environment variables se (`os.environ["WH_PASSWORD"]`).

### A4. Asli tasks jodna (Phase 2)
| Task | Kya karta hai |
|---|---|
| `extract` | `data/` mein 9 CSVs milti hain? Row counts log karo. |
| `validate_raw` | Zaroori columns maujood hain? Khali file? Fail ho to DAG ruk jaye. |
| `clean` | `src/clean/clean_all.py` ka `run()` chalao, `out/` mein CSVs likho, `dq_log` aur `reject` bhi. |
| `load_staging` | `raw` aur `clean` schemas mein **truncate-and-load** (dobara chalane par duplicate nahi). `audit.dq_log` aur `audit.reject` bhi. |
| `build_dimensions` | `sql/02_dims.sql` chalao (C ka). |
| `build_fact` | `sql/03_fact.sql` chalao (C ka). |
| `quality_checks` | `sql/04_checks.sql` chalao. Koi check fail ho to **task fail**. |

Har task log kare: kitne records **read**, **rejected**, **loaded**. Ye judges ko pipeline requirements mein chahiye.

### A5. README (Phase 2 se shuru, Sunday final)
Sections: prerequisites, `.env` kaise banayen, `docker compose up`, DAG trigger kaise karein (UI ya `docker compose exec airflow-scheduler airflow dags trigger nexusmart`), output kahan milega, architecture, design decisions, cleaning rules ka khulasa, known limitations.

### A6. Fresh-run test (Sunday 11 AM-1 PM, sab se zaroori)
Naya folder, `git clone`, `.env` banao, README ke steps **word-to-word** chalao. Behtar: kisi dusre laptop par. Jo step toot-ta hai README theek karo.

---

## 6. Person B: Cleaning + Insights lead

Cleaning ka pehla version bana hua hai (`src/clean/`). Teen file: `config.py` (labels aur limits), `toolkit.py` (chhote helpers), `clean_all.py` (har table ka cleaning function). B ka kaam isay **samajhna, perkhna, mazboot karna**.

### B1. Samjho (1 ghanta)
Har function ek table saaf karta hai. Sab se zaroori: `clean_orders` (dates repair), `clean_order_items` (price aur quantity repair), `clean_customers` (duplicates merge). Chalao:
```powershell
python src/clean/clean_all.py data out
```
`out/dq_log.csv` aur `out/reject.csv` kholo aur samjho har line kya kehti hai.

### B2. Do assumptions ko khud verify karo (judges poochenge)
1. Negative quantity ko `abs()` kiya. Order totals se 99.7% match mila.
2. Qty 500 ko `order_total` se wapas nikala (628 mein se 13 reject).
3. Impossible order date ko pehle payment date, phir shipped date se theek kiya (1,593 repaired, 12 reject).

### B3. Sensitivity table (bahut zaroori: answer key ±1% hai)
Har bade faisle ke bina aur uske saath NMV nikalo (price repair, qty repair, date repair, duplicate hatana). Jo faisle NMV ko 1% se zyada hilate hain wo README mein khaas assumption ke taur par likho.

### B4. Hour-6 ke liye mazboot karo
Naya data aaye to koi naya label ya naya format aa sakta hai. `dq_log` mein "UNMATCHED LABELS" dekho aur unhe `config.py` ke aliases mein jodo.

### B5. Data Quality Report (Phase 2 ke baad)
`audit.dq_log` se: har issue ke liye table, column, before/after counts, fix, assumption. Reject table ka summary reason code ke saath. Format: Excel nahi, ek PDF ya notebook.

### B6. 15 sawaal ke jawab + insights (Phase 2 ke baad, Sunday)
Section 10 ki table dekho. Har sawal ka jawab SQL se nikalo (C ke views use karo) aur D ke dashboard ke number se cross-check karo. Har insight: **kya dikha (number ke saath) -> kyun zaroori -> kya karna chahiye.** Jo data se sabit na ho wo likhna mana hai.
Executive Summary: 2-3 page PDF.

---

## 7. Person C: Warehouse lead

### C1. SQL scripts (Phase 1, sample par)
Postgres mein apne computer par (A ka docker ya local) `clean` schema ka chhota sample bana ke test karo, taake B ka intezar na karna pade.

- `01_schemas.sql`: `raw, clean, audit, mart` schemas.
- `02_dims.sql`: 5 dimensions (`DROP + CREATE + INSERT`, taake dobara chalane par same result). Har dimension mein **row -1 "Unknown"**.
  - `dim_date`: `generate_series('2024-01-01'::date, '2025-06-30'::date, '1 day')` se banao, flags upar ki dates se.
  - `dim_customer`: `clean.customers` + city details (`clean.locations`) + Segment (C3).
  - `dim_product`, `dim_seller`, `dim_location`: seedha clean tables se.
- `03_fact.sql`: `clean.order_items` se. Join `clean.orders`, `payments` (ek row per order), `shipping`, aur returns (valid, line level `GROUP BY order_item_id`). Rules Section 3.4 mein.
- `04_checks.sql`: har check ek row return kare (`check_name, failed_rows`) aur `failed_rows > 0` ho to fail:
  - fact rows = clean.order_items rows
  - koi key NULL nahi, `OrderItemID` unique
  - har fact FK dimension mein maujood
  - `SUM(NetAmount)` = clean.order_items ka net sum
  - har dimension mein -1 row

### C2. ER diagram
Star schema ki tasveer (draw.io ya dbdiagram.io). Fact beech mein, 5 dimensions charon taraf, dimensions aapas mein koi line nahi. PNG save karo `docs/star_schema.png`.

### C3. RFM aur metric views (Phase 2)
- **RFM:** Recency (30 Jun 2025 tak din), Frequency (non-cancelled orders), Monetary (NMV). `NTILE(5)` se score. Segments ke naam: Champions, Loyal, Potential, At Risk, Lost (qaida README mein likho).
- **Views** `mart.v_*` jo D aur B ko seedhe jawab dein (category margin, province share, MoM growth, seller quality, on-time delivery vs returns, payment method vs cancellations...).

---

## 8. Person D: BI lead

Power BI ko **warehouse tables** se connect karna hai (Postgres, host `localhost:5433`, database `wh`, schema `mart`). **CSVs se nahi.** Import mode use karo.
Agar connect na ho: Power BI error ka text bhejo (kabhi Npgsql driver install karna parta hai).

### D1. Phase 1 (mart ke ready hone se pehle)
1. 7 pages ka wireframe (kaghaz ya PowerPoint par). Har page par 5-7 visuals, 1-2 slicers.
2. DAX measures ki list (Section 9 ki definitions) likho.
3. Ek color palette aur font tay karo (poore dashboard mein ek jaisa).

### D2. Data model (mart ready hone par)
5 dimensions + fact import. Relationships: `fact[DateKey] -> DimDate`, aur baaqi 4 keys. `ReturnDateKey` ke liye **inactive** relationship (zarurat ho to `USERELATIONSHIP`). Dimensions ko aapas mein link **na** karo. Power Query mein sirf rename/type.

### D3. 7 pages (spec se)
| Page | Zaroori cheezen |
|---|---|
| Executive Overview | Net Revenue, Orders, AOV, Units, Return Rate, Cancellation Rate, Active Customers, month-over-month change |
| Time Analysis | Monthly/weekly revenue trend, moving average, seasonality, festival comparisons (Ramadan/Eid/11.11/Black Friday) |
| Product & Category | Category revenue aur margin, top/bottom products, sales vs return rate |
| Geography | City aur province performance, region revenue share, location-tier comparison |
| Customer Analysis | New vs returning, RFM segment revenue, retention/cohort, top customers |
| Seller Performance | Seller ranking, revenue, return rate, delivery time, tier comparison |
| Returns & Cancellations | Rates by category/seller/region, return reasons, trends |

Interactivity (zaroori): **slicers** (date, category, region, seller tier, customer segment), **drill-through ya drill-down**, aur kam az kam ek **bookmark ya tooltip page**. Har page ka title takeaway batae ("Electronics margin sab se zyada hai"), sirf "Category" nahi.

### D4. DAX (asli measures, sirf drag-drop nahi)
`NMV`, `Net Revenue`, `Return Rate`, `Cancellation Rate`, `AOV`, `Margin`, YoY/MoM, running total, % of total, moving average. Definitions Section 9 mein. Har measure B ke SQL jawab se cross-check karo.

### D5. Export
`File > Export > PDF` (sab pages), `.pbix` save, version control (copy date ke saath).

---

## 9. Metric definitions (problem statement se, inhi ko use karo)

| Metric | Definition |
|---|---|
| Gross sales | sum(quantity x unit_price), sab lines, discount aur cancellation se pehle |
| NMV | sum(quantity x unit_price - discount), **non-cancelled** lines. **In Transit shamil.** |
| Net Revenue | NMV - valid (non-Rejected) refunds |
| Return Rate | valid return wali lines / delivered lines |
| Delivered lines | non-cancelled lines jin ka order In Transit nahi |
| Kept lines | non-cancelled lines bina valid return ke |
| Cancellation Rate | cancelled orders / sab orders (duplicates hatane ke baad) |
| COGS | cost_price x quantity (kept lines) |
| Margin | Net Revenue - COGS (kept lines) |
| AOV | NMV / non-cancelled orders |
| Active customers | distinct customers jin ka kam az kam ek non-cancelled order ho |
| Units | non-cancelled lines ki quantity ka sum |

Extra: CLV (observed), Repeat Purchase Rate, RFM, Seller Quality Score (weights ka jawaz do), On-Time Delivery Rate (threshold shipping_days ke distribution se tay karo aur likho kyun).

---

## 10. 15 sawaal: kis ka jawab kahan se

| # | Sawal | Data/view | Dashboard page |
|---|---|---|---|
| 1 | Kaun si categories sab se zyada revenue aur margin | category x NetAmount, margin | Product |
| 2 | Kaun se provinces/cities sab se zyada/kam; top 5 cities ka share | location x NMV | Geography |
| 3 | Monthly revenue aur MoM growth | date x NMV | Time |
| 4 | Overall return/cancellation rates aur waqt ke saath tabdeeli | month x rates | Returns |
| 5 | Net revenue vs gross revenue (category ke hisaab se) | gross, net after returns/cancellations | Product |
| 6 | Observed CLV; repeat purchase region/category ke hisaab se | customer x NMV | Customer |
| 7 | Kaun sa RFM segment sab se zyada revenue deta hai, kitna bada | RFM | Customer |
| 8 | Sellers ko quality score se rank karo | revenue, return, on-time, cancel | Seller |
| 9 | On-time delivery ka returns/cancellations se rishta | shipping_days vs flags | Seller / Returns |
| 10 | High sales + high return products; seller se link? | product x seller | Product |
| 11 | Ramadan/Eid/11.11/Black Friday par spike ya returns/cancellations | DimDate flags | Time |
| 12 | Discounts revenue badhate hain? margin ya returns par asar? | discount % buckets | Product / Returns |
| 13 | Slow shipping wale regions mein zyada cancellation/returns? | region x shipping_days | Geography |
| 14 | Kaun se payment methods zyada cancel/return se jude; data quality wajah? | payment x flags | Returns |
| 15 | Profitability flat kyun jabke revenue barh raha hai; **3 actions** | margin trend, discounts, returns, shipping cost | Executive |

Har jawab mein: number, assumption, aur (insights ke liye) recommendation.

---

## 11. Hour-6 data drop drill (sab se nazuk lamha)

1. Naye CSVs `data/` mein dalo (purani `data_v1/` mein copy rakho).
2. A DAG **trigger** kare. Poori chain dobara chale (idempotent hai, duplicate nahi banenge).
3. B `audit.dq_log` mein "UNMATCHED LABELS" aur counts dekhe aur `config.py` update kare (agar naya spelling variant aaye).
4. C `04_checks.sql` ke result dekhe (row counts, null keys, orphans).
5. D dashboard ko **Refresh** kare, numbers ka mutaaliya kare, titles/insights update.
6. Dekho kya badla: kya naye issues aaye jo pehle nahi the? Wo README ke "known limitations" ya DQ report mein likho.

Agar pipeline toote to kabhi haath se data na theek karna. Code theek karo aur dobara chalao.

---

## 12. Submission checklist (spec ke 9 deliverables + 2 safety checks)

- [ ] Airflow DAG `.py` files
- [ ] `.sql` scripts
- [ ] Star schema diagram (PNG/PDF)
- [ ] `.pbix`
- [ ] Dashboard PDF (**sab pages**)
- [ ] Executive Summary / Insights (2-3 page PDF)
- [ ] Source code: GitHub repo ya ZIP
- [ ] README (architecture, setup, design decisions, cleaning rules, known limitations)
- [ ] Data Quality Report (before/after counts)
- [ ] **Koi password nahi** (`.env` shamil nahi, sirf `.env.example`)
- [ ] README fresh folder mein test ho chuka

---

## 13. Presentation (agar finals mein pohnche): 5 min + 3 min Q&A

| Waqt | Kya |
|---|---|
| 30 sec | Business problem |
| 3 min | Live dashboard: top 3 findings, har ek ki recommendation |
| 1 min | Pipeline aur cleaning ek jhalak |
| 30 sec | Sab se zaroori ek action |

Laptop par sab pehle se khula, aur backup PDF.

### Judges ke mumkina sawal (har member tayyar rahe)
- "Ye rows kyun hata di?" (reject table, reason code, 12 orders BAD_DATE, etc.)
- "Kaun si assumption ne totals badle?" (B3 ki sensitivity table)
- "DAG fail ho to kya hota hai?" (retries, quality_checks task fail karta hai, logs)
- "Dobara chalayen to duplicates kyun nahi?" (truncate-and-load, idempotent)
- "Duplicate customers kaise pakde?" (email/phone, naam se nahi, mapping table)
- "In Transit orders kyun shamil?" (spec ka rule)
- "Naya data aaye to?" (config aliases, Unknown label + dq_log, same DAG)

---

## 14. Rozana ke 5 rules

1. Har cheez code mein, haath se kuch nahi.
2. Har fix log hota hai, kuch chupke se delete nahi.
3. Har kuch dobara chal sakta ho (ek click).
4. Jo aapne likha hai usay explain kar sako.
5. Neend poori karo. Thake log bugs banate hain.

# NexusMart: Data Findings + Cleaning Decisions

Ye file raw data ko profile karke bani hai. Yahi cleaning code, Data Quality Report aur README ki buniyad hai. Counts raw CSVs se nikaale gaye hain.

## 0. Problem statement ki zaroori baatein (pehle ye samjho)

| Cheez | Kya likha hai |
|---|---|
| **Deadline** | **18 Oct, 6:00 PM** (kal). Late = har 10 min par 5% |
| **Hour 6 data drop** | Baad mein naya data aayega, **same schema par bilkul same nahi**. Pipeline dobara chalne ke qabil aur lachakdar honi chahiye |
| **Star schema** | **1 fact (`FactSales`) + 5 dimensions** (`DimDate`, `DimCustomer`, `DimProduct`, `DimSeller`, `DimLocation`). Dimensions aapas mein link nahi |
| **Unknown member** | Har dimension mein "Unknown" row |
| **Fact ka grain** | Ek row = ek order line item |
| **Reject table** | Jo repair na ho wo **reason code ke saath reject table** mein. Kabhi chupke se delete nahi |
| **Before/after counts** | Har cleaning decision ke saath |
| **Tolerance** | Revenue totals ±1%, rates ±0.5 percentage points |
| **Penalty** | Non-reproducible setup = **-10 points**. Missing deliverable = -5 se -15 |
| **Tie-breaker** | Pipeline score, phir live Q&A |
| **Dashboard** | 7 areas: Executive, Time, Product, Geography, Customer, Seller, Returns. Slicers: date, category, region, seller tier, customer segment. Drill-through/down + tooltip ya bookmark |
| **Business questions** | 15 sawal (problem statement Section 10). Jawab asli numbers se |
| **Credentials** | Environment variables / Airflow Variables / Connections mein |

## 1. Files aur rows

| File | Rows | Note |
|---|---|---|
| customers | 45,000 | Duplicate entities (alag IDs) |
| products | 3,200 | 26 duplicate names |
| sellers | 420 | |
| locations | 650 | |
| orders | 163,200 | **3,200 exact duplicate rows**, asli unique orders = **160,000** |
| order_items | 315,143 | |
| payments | 168,111 | **3,296 exact duplicates**. 4,815 orders ki 2 payment rows hain |
| shipping | 151,228 | 8,772 orders ki shipping row hi nahi (ye cancelled hain) |
| returns | 16,048 | |

## 2. Masle (counts ke saath)

### Duplicates
- orders: 3,200 exact duplicate rows
- payments: 3,296 exact duplicate rows
- customers: ek hi banda alag IDs se. Same email (lowercase karke) wali ~1,971 extra rows, same phone ~2,197. **Sirf naam se match nahi karna** (rule)
- products: 26 naam duplicate (alag ID, alag seller, thori alag price)

### Date problems (teen formats)
- Formats: `2024-01-31`, `31/01/2024` (**day/month/year**, rule ke mutabiq), `Nov 23 2024`
- Slash wali dates mein pehla number kabhi 12 se zyada aata hai, doosra kabhi nahi, yani **dd/mm/yyyy confirm**
- Impossible dates: `2024-02-30`, `2024-04-31`, `2024-13-05` (month 13), `00/00/2024`. Orders mein 1,150 parse nahi hoti
- Valid range (1 Jan 2024 se 30 Jun 2025) se bahar: orders mein 481 (zyadatar saal 2026/2027)
- Customers ki registration dates 2023 se 2025 tak (8,778 range se bahar, ye order range nahi hai, alag rule chahiye)
- Shipping: 1,269 jagah delivered_date < shipped_date; 436 jagah shipped_date < order_date; 266 jagah delivery 60 din se zyada

### Text labels (ek cheez, kayi spelling)
| Column | Variants | Hona chahiye |
|---|---|---|
| orders.order_status | 20 | Delivered, Cancelled, Returned, In Transit |
| orders.channel | 12 | App, Web, Mobile Web |
| payments.payment_method | 22 | COD, Card, JazzCash, EasyPaisa, Bank Transfer |
| payments.payment_status | 17 | Paid, Cancelled, Refunded, Pending |
| shipping.delivery_status | 15 | Delivered, In Transit, Returned to Seller |
| shipping.courier | 22 | TCS, Leopards, M&P, Trax, PostEx, BlueEx |
| returns.return_status | 10 | Refunded, Approved, Rejected |
| returns.return_reason | 38 | ~10 reasons (Size/fit, Not as described, Quality, Damaged, Changed mind, Wrong item, Colour mismatch, Late delivery, Missing parts) |
| products.category | 74 | **12 categories** (Fashion, Mobile & Accessories, Home & Kitchen, Electronics, Beauty & Personal Care, Footwear, Grocery, Sports & Outdoors, Health & Wellness, Toys & Games, Books & Stationery, Automotive) |
| customers.gender | 9 | M, F, Unknown |
| sellers.seller_tier | 11 | Gold, Silver, Bronze |
| locations.province | 22 | Punjab, Sindh, Khyber Pakhtunkhwa, Balochistan, Gilgit-Baltistan, Azad Kashmir, Islamabad |
| orders.discount_code | 33 | SAVE5, 10, 15, 20, 25, 30, 40, 50 |

### Numbers
- Text mein aate hain: `Rs. 2,290` (unit_price, order_total, amount, refund_amount, list_price)
- Sentinel / bekaar: `9999999` (unit_price, order_total, shipping_fee), negative values (unit_price 647 jagah <= 0, order_total 342 <= 0, payments 823 <= 0, shipping_fee 159 negative)
- quantity: `one`, `two`, `three`..., `1.0`, negative (-1 se -6), aur **500** (641 rows, outlier)
- unit_price ka list_price se ratio normal mein 1.00 se 1.045. Is se bahar: 1,246 jagah >3x, 2,164 jagah <0.3x
- products: 75 jagah cost > list, 8 jagah list_price <= 0, weight negative (10) ya >100 (7)
- sellers.rating: 0 se 11 tak (valid 1 se 5)
- customers.birth_year: 1900 se 2030
- refund_amount: 1,297 jagah 0, 273 jagah refund > line amount

### Missing
- customers: email 1,698, phone 3,599, gender 2,199, city_id 2,233, birth_year 4,600
- orders: ship_city_id 6,388 (unique orders par)
- products: cost_price 170, sub_category 485, brand 392, weight 296
- shipping: shipped_date 5,943, delivered_date 18,841, shipping_fee 9,145
- payments: payment_date 5,017
- returns: return_reason 2,390
- order_items: discount_amount 31,567 khali (10,183 jagah code hone ke bawajood khali)

### Broken references (orphans)
- orders.customer_id: 330 customers table mein nahi (IDs `C9xxxx`)
- order_items.product_id: 932 products table mein nahi (IDs `P9xxxx`)
- returns.order_item_id: 139 order_items mein nahi
- Baaqi sab links theek (seller, city, order links)

### Dilchasp patterns jo kaam aayenge
- Line discount = **gross x code%**: 99.6% rows mein bilkul match. Khali discount_amount ko code se nikaal sakte hain
- `order_total` = sum(qty x unit_price - discount) **97% orders mein match**. Jo match nahi karte unmein aksar unit_price corrupt hota hai, to order_total se unit_price wapas nikala ja sakta hai
- 8,772 cancelled orders ki shipping row nahi, 5,890 cancelled orders ki shipping status "Returned to Seller" hai
- Order status "Returned" wale 2,859 orders ki shipping "Delivered" hai (ye theek hai)
- In Transit orders: 1,353. **Ye NMV mein shamil hain** (rule), delivered lines mein nahi

## 3. Cleaning decisions (jo hum code mein lagayenge)

| Masla | Faisla | Reject/flag? |
|---|---|---|
| Exact duplicate orders/payments | `drop_duplicates`, count log | Count log |
| Date formats | Teeno formats parse, slash = dd/mm/yyyy | |
| Impossible date (30 Feb, month 13, 00/00) | Doosre columns se repair (jaise order_date ko payment_date/shipped_date se), warna reject | Reject reason `BAD_DATE` |
| Order date range se bahar | Repair try (saal ka typo), warna reject | `DATE_OUT_OF_RANGE` |
| Text labels | Mapping dictionary (lowercase + strip) se canonical | Unknown label flag |
| `Rs. 2,290` | Number mein convert | |
| Sentinel 9999999, negative, 0 prices | Repair: pehle products.list_price, phir order_total se. Warna reject | `BAD_PRICE` |
| quantity words | one/two/... ko number | |
| quantity 500, negative | Flag/fix with documented threshold | `BAD_QTY` |
| Missing discount_amount | gross x code% | |
| Orphan customer/product | "Unknown" member par map, flag set | `ORPHAN_CUSTOMER`, `ORPHAN_PRODUCT` |
| Orphan returns | Reject | `ORPHAN_RETURN` |
| Duplicate customers | Email (normalized) ya phone se merge, **mapping table** (dup_id -> master_id) | |
| Duplicate products | Same normalized naam + brand + category, mapping table | |
| Missing ship_city_id | "Unknown" location (customer city se bharna sirf documented assumption ke saath, 11% jagah ship city customer city se alag hai) | |
| Province, gender, tier | Canonical set, khali = Unknown | |
| Rating out of range, birth_year out of range | Null/flag | |
| Rejected returns | **Valid return nahi** (rule) | |

Har faisle ke liye code, `dq_log` mein record (issue, column, before count, after count, action), aur assumption.

## 4. Standard metrics (problem statement ke mutabiq, inhi se number nikalna)

| Metric | Definition |
|---|---|
| NMV | sum(quantity x unit_price - discount) non-cancelled lines. **In Transit shamil** |
| Net Revenue | NMV minus valid (non-Rejected) refunds |
| Return Rate | Valid return wali lines / delivered lines |
| Cancellation Rate | Cancelled orders / sab orders (duplicates hatane ke baad) |
| Margin | Net revenue minus COGS (kept lines par) |
| COGS | cost_price x quantity (kept lines) |
| AOV | NMV / non-cancelled orders |
| Delivered lines | Non-cancelled lines jinka order In Transit nahi |
| Kept lines | Non-cancelled lines bina valid return ke |
| Gross sales | sum(quantity x unit_price), discount aur cancellation se pehle |
| Active customers | Kam se kam ek non-cancelled order wale unique customers |
| Units | Non-cancelled lines ki quantity ka sum |

Additional: CLV (observed), Repeat Purchase Rate, RFM, Seller Quality Score (justified weights), On-Time Delivery Rate (threshold khud justify karo).

## 5. Agla kaam (team ke liye)

| Kaun | Kya |
|---|---|
| Pipeline lead | CSVs `data/` folder mein rakho. Airflow chalu rakho |
| Cleaning/DB lead | Section 3 ke hisaab se `clean` code (agla step, wo main yahan likhta hoon) |
| BI lead | Section 4 ke measures aur 7 pages ka layout draft |
| Story lead | Section 10 ke 15 sawal ki list, har ek ke liye kaun si table/measure |

**Hour 6 ka data drop yaad rakho:** cleaning rules hard-code mat karo (jaise sirf aaj dekhe hue labels). Mapping tables aur "unknown label" handling rakho, taake naya data aaye to pipeline na tootay.

# Team ke Git qaayde

1. **Sirf apna folder edit karo** (A: `dags/`, B: `src/clean/`, C: `sql/`, D: `bi/`). Dusre ka folder badalna ho to pehle us se baat karo.
2. **Apni branch par kaam karo**, `main` par seedha kabhi nahi:
   `pipeline` (A), `cleaning` (B), `warehouse` (C), `bi` (D).
3. **Kaam shuru karne se pehle** `git pull`, **chhote kaam ke baad** commit + push. Din mein kam az kam 3 baar.
4. Commit message saaf likho: `sql: add dim_date with festival flags`, na ke `update`.
5. **Kabhi commit nahi:** `.env`, passwords, `data/` ki CSVs, `out/` ke files. (`.gitignore` inhe rokta hai, phir bhi `git status` dekh lo.)
6. **`.pbix` sirf D** commit kare (binary file hai, do log ek saath badlenge to merge nahi hota).
7. Merge `main` mein sirf **A** karta hai, har sync point (8 PM, 11:30 PM, Sunday 11 AM) par.
8. Koi cheez toote to `main` mein haath se data ya file theek mat karo. Code theek karo aur dobara chalao.

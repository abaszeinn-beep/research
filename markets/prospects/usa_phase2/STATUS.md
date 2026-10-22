# USA Phase 2 checkpoint

Research was stopped on request. This is a partial checkpoint of slices that had already written `USA2_sNNN_log.csv`, `_companies.csv`, and `_people.csv` under `/tmp/prospects/usa_out2`. No new stores were researched. A slice is complete only when logged stores equal input stores. A partial slice contributes only its logged stores.

Phase 2 input is `usa_gap2` slices USA2_s001–USA2_s129 (7,087 stores: 128 slices of 55 and slice 129 with 47). Phase 1 (top 5,000 by traffic) is already in the workbooks. These Phase 2 domains were already rows in those workbooks, so the merge updates contacts in place and does not add stores.

## Slice inventory

| State | Slices | Stores in input | Logged | Companies | People rows | Stores with a primary decision maker |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Complete | 0 | 0 | 0 | 0 | 0 | 0 |
| Partial | 2 | 110 | 20 | 20 | 27 | 18 |
| Empty | 127 | 6,977 | 0 | 0 | 0 | 0 |
| **Phase 2 total** | **129** | **7,087** | **20** | **20** | **27** | **18** |

Partial slices (all three output files parse; log row count is below the input):

| Slice | Input stores | Log rows | Company rows | People rows | Primary decision maker |
| --- | ---: | ---: | ---: | ---: | ---: |
| USA2_s032 | 55 | 10 | 10 | 13 | 8 |
| USA2_s124 | 55 | 10 | 10 | 14 | 10 |

Empty slices have no log, companies, or people file: USA2_s001–s031, s033–s123, s125–s129. No corrupt output files. Logged domains match the company file on both partial slices, and every logged domain was already in the USA shard list.

## Workbooks after merge

Same columns and fashion rule as `build_gulf_workbooks.py` (a store is on the fashion workbook when its `Lists` value includes `fashion`). Deduped by store domain. Phones and emails are union-merged and support-type mailboxes are dropped. An existing company LinkedIn page is kept when the checkpoint names a different page. A checkpoint primary decision maker fills a blank and replaces a first-pass hint when the checkpoint names a different person (Arcadia Publishing: Richard Joseph to Brittain Phillips). Two people rows were already present (Sara Lively, Robert Winskowicz) and were not duplicated, so the workbooks gained 25 people rows from 27 checkpoint rows.

| Workbook | Master Prospects | With a decision maker | Decision Makers rows |
| --- | ---: | ---: | ---: |
| `markets/prospects/USA_Ecommerce_Prospects.xlsx` | 11,158 | 5,381 | 9,819 |
| `markets/prospects/USA_Fashion_Prospects.xlsx` | 2,938 | 1,594 | 3,032 |

Phase 1 baselines were 5,366 / 9,794 (ecommerce) and 1,588 / 3,023 (fashion). Master row counts are unchanged.

Craftmade was logged and stayed without a decision maker; its master-sheet fields were already filled or still not found. The Water Bottle Store gained business emails and still has no decision maker.

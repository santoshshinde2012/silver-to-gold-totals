# Synthetic order data

[`orders.json`](orders.json) contains the complete seed for the local Silver-to-Gold totals example. All orders, customers, and amounts are synthetic; region names are generic.

## Fields

| Key | Contents |
| --- | --- |
| `silver_first_load` | Silver's first commit: eight accepted orders with `order_id`, `business_date`, `region`, `customer`, `amount`, and `status`. |
| `move_7` | Order 7 moves from 3 Nov West to 4 Nov East. Its customer, C, still has order 4 in 3 Nov West. |
| `cancel_8` | Order 8 is cancelled. It was the only order in 5 Nov South. |
| `fix_3` | Order 3's amount is corrected from 40 to 35. Used for the race between two repairs. |
| `fix_2_late` | In November, order 2's amount is corrected from 50 to 45. Its business date is in October, a month that is already closed. |
| `closed_month` | The month treated as closed: `2026-10`. |

Each change is `{"order_id": ..., "updates": {column: new value}}` and becomes one `UPDATE` commit on Silver. Dates are ISO `YYYY-MM-DD` strings. Amounts are whole numbers in one currency.

## Scenario order

1. Load Silver (version 0) and build Gold with the full-rebuild query.
2. Move order 7 (version 1) and cancel order 8 (version 2).
3. Run each of the four repairs on its own Gold copy, once after each Silver commit, and compare it with a full rebuild.
4. Correct order 3 (version 3). Release a repair built from version 3, then retry one built from version 1, with and without the guard.
5. Approve October's total at version 3, then correct order 2 in November and compare dropping the late row with booking an adjustment.

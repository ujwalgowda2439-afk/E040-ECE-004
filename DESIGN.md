# ECE-004 Design & Business Rules

## 1. Solution overview
A command-file-driven Python 3.10+ engine. It reads `plans.csv`, `subscribers.csv`, `previous_bills.csv`, `usage.csv`, and `commands.txt`, simulates each calendar date in chronological order, then writes `daily_status.csv`, `bills.csv`, and `errors.csv`. It uses only the Python standard library. `Decimal` is used for money and weighted usage to avoid binary floating-point billing errors.

## 2. Business rules

- **BR-01 — Weighted FUP accounting:** Daily metered usage is `download_gb + 0.5 × upload_gb`. The cumulative total is compared with the applicable cap using a strict `>` comparison; exactly equal to the cap is not an FUP breach.
- **BR-02 — Next-day throttling:** If cumulative weighted usage first exceeds the applicable cap on date D, the subscriber is throttled to 2 Mbps beginning on D+1. The crossing day's speed remains unchanged.
- **BR-03 — Top-up:** Each valid top-up costs Rs 149 and adds 50 GB to the allowance beginning the day after purchase. It restores full speed when the cumulative usage is within the increased allowance. Top-up allowances are cycle-scoped and expire at cycle end.
- **BR-04 — Upgrade:** An upgrade is effective immediately on its command date. The new plan's full cap and speed apply from that date, and prior accepted usage remains in cumulative usage. The extra charge is `(new plan price − old plan price) × days remaining / 30`, where days remaining includes the upgrade date.
- **BR-05 — Downgrade:** A downgrade does not change the current cycle's plan, cap, speed, or charge. It is stored as `next_cycle_plan_id`.
- **BR-06 — Previous bill late fee and suspension:** A late fee of Rs 100 applies if the September bill remains unpaid after `due_date + 10 days`; payment on exactly `due_date + 10 days` avoids the fee. Suspension starts on `due_date + 20 days`; usage on suspension dates is rejected. A valid payment command resumes service on the payment date.
- **BR-07 — GST and rounding:** GST is 18% of plan charge, upgrade pro-rata charge, top-up charge, and late fee. GST is retained to two decimals. The final amount inclusive of GST is rounded to the nearest rupee using half-up rounding.
- **BR-08 — Usage validation:** Reject and log usage for unknown subscribers, dates outside the subscriber's 30-day cycle, duplicate subscriber/date rows, and subscribers suspended on that date.
- **BR-09 — Command validation:** Reject commands for unknown subscribers/plans, malformed dated commands, invalid cycle dates, and payments below the September bill amount.
- **BR-10 — Event order:** For each date, apply dated commands in original file order, then determine the day's service state and process that date's usage. Status output uses the requested date's cumulative end-of-day usage and that date's speed/state.

## 3. Data and calculation model
- Cycle length: 30 days, inclusive of cycle start and cycle start + 29.
- `plan_charge_rs`: original cycle-start plan price.
- `upgrade_prorata_rs`: sum of each accepted upgrade's incremental price prorated by inclusive days remaining.
- `topup_charge_rs`: count × Rs 149.
- `late_fee_rs`: Rs 100 or Rs 0 based on the previous bill's payment date / PAYMENT command.
- `subtotal_rs`: plan + upgrade pro-rata + top-ups + late fee.
- `gst_rs`: subtotal × 0.18.
- `total_rs`: nearest rupee after GST.
- `total_weighted_gb`: sum of accepted usage only; rejected suspended usage is excluded.
- `cap_gb`: final active plan cap plus all top-ups purchased in the cycle.
- `throttled_days` and `suspended_days`: count of calendar days in the subscriber's cycle in each state.

## 4. Pro-rata examples
- SUB-007 upgrades Basic (Rs 499) to Pro (Rs 1,099) on cycle day 1: `(1099 − 499) × 30 / 30 = Rs 600`.
- SUB-008 upgrades Basic to Standard (Rs 799) on cycle day 30: `(799 − 499) × 1 / 30 = Rs 10`.
- SUB-009 upgrades Standard (Rs 799) to Ultra (Rs 1,499) on cycle day 16: `(1499 − 799) × 15 / 30 = Rs 350`.

## 5. Why downgrade is deferred
A downgrade is recorded for the next cycle because the current cycle's plan price, speed entitlement, and data cap were committed at the beginning of that billing period. Applying a downgrade mid-cycle would retroactively alter the current service entitlement and make billing inconsistent. The engine therefore preserves current-cycle terms and exposes the requested plan as `next_cycle_plan_id`.

## 6. Known pack-specific validation outcomes
- SUB-003 reaches exactly 200.00 GB on Oct 20, remains full speed Oct 21, crosses on Oct 21, and is throttled from Oct 22.
- SUB-005 buys a top-up on its crossing date; the extra 50 GB begins Oct 13.
- SUB-007 and SUB-008 exercise day-1 and day-30 upgrade proration.
- SUB-010 has two top-ups in one cycle.
- SUB-012 has five suspended days (Oct 10–14); payment on Oct 15 resumes service that day.
- SUB-013 incurs Rs 100 late fee; SUB-016's payment exactly ten days after due date avoids it.
- Usage rows 902 and 903 and command line 17 are rejected as planted.
- SUB-014 and SUB-015 downgrades affect only the next cycle.

## 7. Assumptions where the brief/data pack requires interpretation
1. A valid PAYMENT amount must be at least the September bill amount; underpayments are rejected and do not resume service.
2. The bill's `plan_charge_rs` is the original cycle-start plan price; upgrades are represented separately in `upgrade_prorata_rs`.
3. The bill's `cap_gb` is the final active plan cap plus all cycle top-up allowances.
4. `fup_crossed_on` records the first date usage exceeded the cap in the cycle, even if a later upgrade/top-up raises the cap and restores full speed.
5. The status row's cumulative usage is the end-of-day total, while `speed_mbps` and `state` represent the speed/state in effect during that date.
6. Suspended days count every cycle date on which service is suspended, whether or not a usage row exists.

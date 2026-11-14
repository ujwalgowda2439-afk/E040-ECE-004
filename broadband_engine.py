#!/usr/bin/env python3
"""ECE-004 Broadband Plan, FUP Throttling and Pro-Rated Billing Engine.
Python 3.10+, standard library only.
Run: python broadband_engine.py --input-dir . --output-dir output
"""
from __future__ import annotations
import argparse, csv
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

D = Decimal
TOPUP_GB = D("50")
TOPUP_PRICE = D("149")
GST_RATE = D("0.18")
THROTTLED_SPEED = 2
CYCLE_DAYS = 30

def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def write_csv(path: Path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)

def fmt_money(value: Decimal) -> str:
    return f'{value.quantize(D("0.01"), rounding=ROUND_HALF_UP):.2f}'

def fmt_total(value: Decimal) -> str:
    return f'{value.quantize(D("1"), rounding=ROUND_HALF_UP):.2f}'

def run(input_dir: Path, output_dir: Path):
    plans_rows = read_csv(input_dir / "plans.csv")
    subs_rows = read_csv(input_dir / "subscribers.csv")
    prev_rows = read_csv(input_dir / "previous_bills.csv")
    usage_rows = read_csv(input_dir / "usage.csv")

    plans = {r["plan_id"]: {
        "name": r["plan_name"], "speed": int(r["speed_mbps"]),
        "cap": D(r["data_cap_gb"]), "price": D(r["price_rs"])
    } for r in plans_rows}
    subscribers = {r["subscriber_id"]: {
        **r, "start": date.fromisoformat(r["cycle_start_date"])
    } for r in subs_rows}
    previous = {r["subscriber_id"]: r for r in prev_rows}

    errors = []
    usage_by_date = defaultdict(list)
    seen_usage = set()
    # CSV physical line numbers include the header.
    for line_no, row in enumerate(usage_rows, start=2):
        sid, day = row["subscriber_id"], date.fromisoformat(row["date"])
        key = (sid, day)
        if key in seen_usage:
            errors.append(["usage.csv", line_no, "Duplicate usage row for subscriber and date"])
            continue
        seen_usage.add(key)
        if sid not in subscribers:
            errors.append(["usage.csv", line_no, f"Unknown subscriber {sid}"])
            continue
        start = subscribers[sid]["start"]
        if not start <= day <= start + timedelta(days=29):
            errors.append(["usage.csv", line_no, "Usage date outside subscriber billing cycle"])
            continue
        usage_by_date[day].append((line_no, row))

    state = {}
    for sid, sub in subscribers.items():
        bill = previous[sid]
        due = date.fromisoformat(bill["due_date"])
        paid = None if bill["paid_on"] == "NONE" else date.fromisoformat(bill["paid_on"])
        late_fee = D("100") if paid is None or paid > due + timedelta(days=10) else D("0")
        suspend_start = due + timedelta(days=20) if paid is None or paid >= due + timedelta(days=20) else None
        state[sid] = {
            "plan": sub["plan_id"], "base_plan": sub["plan_id"],
            "upgrade_prorata": D("0"), "topups": [], "downgrade": None,
            "cum": D("0"), "accepted_total": D("0"), "crossed": None,
            "paid_date": paid, "suspend_start": suspend_start,
            "late_fee": late_fee, "daily": {},
            "throttled_days": 0, "suspended_days": 0
        }

    dated_commands = defaultdict(list)
    command_path = input_dir / "commands.txt"
    for line_no, raw in enumerate(command_path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.strip().split("|")
        command = parts[0]
        if command in {"UPGRADE", "DOWNGRADE", "TOPUP", "PAYMENT", "STATUS"}:
            try:
                day_text = parts[3] if command in {"UPGRADE", "DOWNGRADE"} else parts[2]
                dated_commands[date.fromisoformat(day_text)].append((line_no, parts))
            except (IndexError, ValueError):
                errors.append(["commands.txt", line_no, "Malformed command or invalid date"])
        elif command not in {"LOAD_PLANS", "LOAD_SUBSCRIBERS", "LOAD_PREVIOUS_BILLS", "LOAD_USAGE", "BILL_ALL"}:
            errors.append(["commands.txt", line_no, f"Unknown command {command}"])

    status_requests = []
    all_dates = set(dated_commands)
    for sub in subscribers.values():
        all_dates.update(sub["start"] + timedelta(days=i) for i in range(CYCLE_DAYS))

    for day in sorted(all_dates):
        # Dated commands run first, in their original file order.
        for line_no, parts in dated_commands.get(day, []):
            command, sid = parts[0], parts[1]
            if command == "STATUS":
                if sid not in subscribers:
                    errors.append(["commands.txt", line_no, f"Unknown subscriber {sid}"])
                else:
                    status_requests.append((line_no, sid, day))
                continue
            if sid not in subscribers:
                errors.append(["commands.txt", line_no, f"Unknown subscriber {sid}"])
                continue
            sub, st = subscribers[sid], state[sid]
            cycle_start = sub["start"]
            cycle_end = cycle_start + timedelta(days=29)
            if command == "UPGRADE":
                new_plan = parts[2]
                if new_plan not in plans:
                    errors.append(["commands.txt", line_no, f"Unknown plan {new_plan}"])
                    continue
                if not cycle_start <= day <= cycle_end:
                    errors.append(["commands.txt", line_no, "Upgrade date outside billing cycle"])
                    continue
                old_plan = st["plan"]
                if plans[new_plan]["price"] < plans[old_plan]["price"]:
                    errors.append(["commands.txt", line_no, "UPGRADE must not reduce plan price"])
                    continue
                days_remaining = (cycle_end - day).days + 1
                difference = plans[new_plan]["price"] - plans[old_plan]["price"]
                st["upgrade_prorata"] += difference * D(days_remaining) / D(CYCLE_DAYS)
                st["plan"] = new_plan
            elif command == "DOWNGRADE":
                new_plan = parts[2]
                if new_plan not in plans:
                    errors.append(["commands.txt", line_no, f"Unknown plan {new_plan}"])
                    continue
                st["downgrade"] = new_plan
            elif command == "TOPUP":
                if not cycle_start <= day <= cycle_end:
                    errors.append(["commands.txt", line_no, "Top-up date outside billing cycle"])
                    continue
                # Purchased today; extra allowance and speed restoration begin tomorrow.
                st["topups"].append((day + timedelta(days=1), TOPUP_GB))
            elif command == "PAYMENT":
                amount = D(parts[3])
                outstanding = D(previous[sid]["amount_rs"])
                if amount < outstanding:
                    errors.append(["commands.txt", line_no, "Payment amount is less than outstanding September bill"])
                    continue
                st["paid_date"] = day

        # Determine service state at the START of each day, then accept that day's usage.
        for sid, sub in subscribers.items():
            if not sub["start"] <= day <= sub["start"] + timedelta(days=29):
                continue
            st = state[sid]
            plan = plans[st["plan"]]
            cap = plan["cap"] + sum((gb for effective, gb in st["topups"] if effective <= day), D("0"))
            suspended = bool(st["suspend_start"] and day >= st["suspend_start"]
                             and (st["paid_date"] is None or day < st["paid_date"]))
            throttled = st["cum"] > cap
            if suspended:
                day_state, speed = "SUSPENDED", 0
                st["suspended_days"] += 1
            elif throttled:
                day_state, speed = "THROTTLED", THROTTLED_SPEED
                st["throttled_days"] += 1
            else:
                day_state, speed = "FULL_SPEED", plan["speed"]

            for line_no, row in usage_by_date.get(day, []):
                if row["subscriber_id"] != sid:
                    continue
                if suspended:
                    errors.append(["usage.csv", line_no, "Usage rejected: subscriber is suspended"])
                    continue
                weighted = D(row["download_gb"]) + D(row["upload_gb"]) * D("0.5")
                st["cum"] += weighted
                st["accepted_total"] += weighted
                if st["cum"] > cap and st["crossed"] is None:
                    st["crossed"] = day

            st["daily"][day] = {
                "plan_id": st["plan"], "speed": speed, "state": day_state,
                "cap": cap, "cum": st["cum"]
            }

    daily_headers = ["subscriber_id", "date", "plan_id", "speed_mbps",
                     "cumulative_weighted_gb", "cap_gb", "state"]
    daily_rows = []
    for line_no, sid, day in sorted(status_requests):
        snap = state[sid]["daily"].get(day)
        if snap is None:
            errors.append(["commands.txt", line_no, "STATUS date outside subscriber billing cycle"])
            continue
        daily_rows.append([
            sid, day.isoformat(), snap["plan_id"], snap["speed"],
            f'{snap["cum"]:.2f}', f'{snap["cap"]:.2f}', snap["state"]
        ])

    bill_headers = ["subscriber_id", "cycle_start", "cycle_end", "plan_id",
        "plan_charge_rs", "upgrade_prorata_rs", "topup_count", "topup_charge_rs",
        "late_fee_rs", "subtotal_rs", "gst_rs", "total_rs", "total_weighted_gb",
        "cap_gb", "fup_crossed_on", "throttled_days", "suspended_days",
        "next_cycle_plan_id"]
    bill_rows = []
    for sid in sorted(subscribers):
        sub, st = subscribers[sid], state[sid]
        start, end = sub["start"], sub["start"] + timedelta(days=29)
        plan_charge = plans[st["base_plan"]]["price"]
        topup_count = len(st["topups"])
        topup_charge = TOPUP_PRICE * topup_count
        subtotal = plan_charge + st["upgrade_prorata"] + topup_charge + st["late_fee"]
        gst = subtotal * GST_RATE
        total = (subtotal + gst).quantize(D("1"), rounding=ROUND_HALF_UP)
        final_cap = plans[st["plan"]]["cap"] + TOPUP_GB * topup_count
        bill_rows.append([
            sid, start.isoformat(), end.isoformat(), st["plan"],
            fmt_money(plan_charge), fmt_money(st["upgrade_prorata"]),
            topup_count, fmt_money(topup_charge), fmt_money(st["late_fee"]),
            fmt_money(subtotal), fmt_money(gst), f"{total:.2f}",
            f'{st["accepted_total"]:.2f}', f"{final_cap:.2f}",
            st["crossed"].isoformat() if st["crossed"] else "NONE",
            st["throttled_days"], st["suspended_days"],
            st["downgrade"] or st["plan"]
        ])

    error_rows = [[source, line_no, reason] for source, line_no, reason in errors]
    write_csv(output_dir / "daily_status.csv", daily_headers, daily_rows)
    write_csv(output_dir / "bills.csv", bill_headers, bill_rows)
    write_csv(output_dir / "errors.csv", ["source", "line_no", "reason"], error_rows)
    return {"subscribers": len(subscribers), "daily_status": len(daily_rows),
            "errors": len(error_rows), "bills": len(bill_rows)}

def main():
    parser = argparse.ArgumentParser(description="ECE-004 broadband billing engine")
    parser.add_argument("--input-dir", default=".", help="Directory containing the four CSVs and commands.txt")
    parser.add_argument("--output-dir", default="output", help="Directory for generated output CSVs")
    args = parser.parse_args()
    result = run(Path(args.input_dir), Path(args.output_dir))
    print("ECE-004 completed:", ", ".join(f"{k}={v}" for k, v in result.items()))

if __name__ == "__main__":
    main()

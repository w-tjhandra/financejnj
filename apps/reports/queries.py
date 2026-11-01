"""Query rekap 4 periode (D2, D5, K-01): harian, mingguan, bulanan, tahunan.

Basis cakupan filter sama dengan `ledger.queries.transaction_list`: hanya
transaksi aktif, rentang tanggal, dan roll-up kategori LAYER→AFKIR.
Agregasi dilakukan SQL (window function + `FILTER`/`GROUP BY`), bukan loop
Python atas data mentah.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.db.models import Case, F, Q, Sum, When
from django.db.models.functions import TruncMonth

from core import messages
from core.errors import DomainError
from core.utils.dates import add_months, format_date_id, format_month_id, month_start
from core.utils.periods import format_period_label, week
from ledger.models import ACCOUNT_CHOICES, Account, AccountTransfer, Transaction
from master.models import Category

ZERO = Decimal("0")


@dataclass(frozen=True)
class SummaryRow:
    key: str
    label: str
    amount: Decimal


@dataclass(frozen=True)
class StockRecapRow:
    stock_item_id: int
    kode: str
    nama: str
    satuan: str
    opening: Decimal  # saldo awal periode: opening_qty + mutasi sebelum periode
    in_qty: Decimal
    out_qty: Decimal
    adj: Decimal  # penyesuaian bersih (sumber adjustment)
    closing: Decimal


@dataclass(frozen=True)
class RecapResult:
    date_from: date
    date_to: date
    period_label: str
    # 4 baris D2: Pemasukan, Pengeluaran, Mutasi non-operasional, Selisih
    summary: list[SummaryRow]
    # kunci: tanggal, kategori, item, flow, amount, qty, saldo_kas, stok_berjalan
    detail: list[dict]
    # per jenis stok: opening/in/out/adj/closing
    stock: list[StockRecapRow]
    accounts: list[dict]
    account_total: dict
    months: list[dict] | None = None  # hanya yearly_recap
    gaji: list[dict] | None = None  # hanya monthly_recap


def _category_pks(category_ids) -> list[int] | None:
    """Resolve filter kategori dengan roll-up D5.

    LAYER menyertakan AFKIR; AFKIR hanya AFKIR; lain utuh. ``None`` = tanpa
    filter kategori. Kategori yang tidak ada diabaikan.
    """
    if category_ids is None:
        return None
    if isinstance(category_ids, (int, str)) and str(category_ids).isdigit():
        category_ids = [int(category_ids)]
    ids = [int(c) for c in category_ids if str(c).isdigit()]
    if not ids:
        return None
    cats = Category.objects.filter(pk__in=ids).in_bulk()
    result = set(ids)
    if any(cats.get(pk) is not None and cats[pk].code == "LAYER" for pk in ids):
        result.update(
            Category.objects.filter(code__in=["LAYER", "AFKIR"]).values_list("pk", flat=True)
        )
    return sorted(result)


def _base_transactions(date_from: date, date_to: date, category_ids):
    opening_date = Account.objects.order_by("opening_balance_date").values_list(
        "opening_balance_date", flat=True
    ).first()
    qs = Transaction.objects.select_related("category", "item", "item__stock_item")
    if date_from is not None:
        qs = qs.filter(date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(date__lte=date_to)
    if opening_date is not None:
        qs = qs.filter(date__gte=opening_date)
    pks = _category_pks(category_ids)
    if pks is not None:
        qs = qs.filter(category_id__in=pks)
    return qs


def _summary_rows(qs) -> list[SummaryRow]:
    """4 baris D2 (agregasi SQL, satu kolom per baris)."""
    agg = qs.aggregate(
        pemasukan=Sum("amount", filter=Q(flow="income", is_opening_correction=False)),
        pengeluaran=Sum("amount", filter=Q(flow="expense", is_opening_correction=False)),
    )
    mutasi = qs.filter(is_opening_correction=True).aggregate(
        m=Sum(
            Case(
                When(flow="income", then=F("amount")),
                default=-F("amount"),
            )
        )
    )["m"]
    pemasukan = agg["pemasukan"] or ZERO
    pengeluaran = agg["pengeluaran"] or ZERO
    mutasi = mutasi or ZERO
    return [
        SummaryRow("pemasukan", "Pemasukan", pemasukan),
        SummaryRow("pengeluaran", "Pengeluaran", pengeluaran),
        SummaryRow(
            "mutasi_nonoperasional",
            "Mutasi non-operasional (koreksi saldo awal)",
            mutasi,
        ),
        SummaryRow("selisih", "Selisih", pemasukan - pengeluaran + mutasi),
    ]


def _account_summaries(date_from: date, date_to: date) -> list[dict]:
    account_order = {code: index for index, (code, _name) in enumerate(ACCOUNT_CHOICES)}
    accounts = sorted(
        Account.objects.filter(is_active=True),
        key=lambda row: account_order.get(row.code, len(account_order)),
    )
    account_ids = [account.pk for account in accounts]
    if not account_ids:
        return []

    transaction_totals = {
        row["account_id"]: row
        for row in (
            Transaction.objects.filter(
                account_id__in=account_ids,
                date__gte=F("account__opening_balance_date"),
                date__lte=date_to,
            )
            .values("account_id")
            .annotate(
                before=Sum(
                    Case(When(flow="income", then=F("amount")), default=-F("amount")),
                    filter=Q(date__lt=date_from),
                ),
                transaction_in=Sum(
                    "amount",
                    filter=Q(date__gte=date_from, flow="income"),
                ),
                transaction_out=Sum(
                    "amount",
                    filter=Q(date__gte=date_from, flow="expense"),
                ),
            )
        )
    }

    transfer_in_totals = {
        row["to_account_id"]: row
        for row in (
            AccountTransfer.objects.filter(
                to_account_id__in=account_ids,
                date__gte=F("to_account__opening_balance_date"),
                date__lte=date_to,
            )
            .values("to_account_id")
            .annotate(
                before=Sum("amount", filter=Q(date__lt=date_from)),
                period=Sum("amount", filter=Q(date__gte=date_from)),
            )
        )
    }
    transfer_out_totals = {
        row["from_account_id"]: row
        for row in (
            AccountTransfer.objects.filter(
                from_account_id__in=account_ids,
                date__gte=F("from_account__opening_balance_date"),
                date__lte=date_to,
            )
            .values("from_account_id")
            .annotate(
                before=Sum("amount", filter=Q(date__lt=date_from)),
                period=Sum("amount", filter=Q(date__gte=date_from)),
            )
        )
    }

    summaries = []
    for account in accounts:
        code = account.code or "cash"
        transaction_totals_for_account = transaction_totals.get(account.pk, {})
        transfer_in_for_account = transfer_in_totals.get(account.pk, {})
        transfer_out_for_account = transfer_out_totals.get(account.pk, {})
        opening = ZERO
        if date_from >= account.opening_balance_date:
            opening = (
                account.opening_balance
                + (transaction_totals_for_account.get("before") or ZERO)
                + (transfer_in_for_account.get("before") or ZERO)
                - (transfer_out_for_account.get("before") or ZERO)
            )
        transaction_in = transaction_totals_for_account.get("transaction_in") or ZERO
        transaction_out = transaction_totals_for_account.get("transaction_out") or ZERO
        transfer_in = transfer_in_for_account.get("period") or ZERO
        transfer_out = transfer_out_for_account.get("period") or ZERO
        closing = opening + transaction_in - transaction_out + transfer_in - transfer_out
        summaries.append(
            {
                "code": code,
                "name": account.name,
                "opening": opening,
                "transaction_in": transaction_in,
                "transaction_out": transaction_out,
                "transfer_in": transfer_in,
                "transfer_out": transfer_out,
                "closing": closing,
            }
        )
    return summaries


def _detail_rows(date_from: date, date_to: date, category_ids) -> list[dict]:
    """Fetch transaction details and stock balances for the report interval."""
    pks = _category_pks(category_ids)
    params: list = [date_from, date_to]
    if pks is None:
        cat_where = "TRUE"
    else:
        placeholders = ", ".join(["%s"] * len(pks))
        cat_where = f"t.category_id IN ({placeholders})"
        params.extend(pks)
    params.extend([date_from, date_to])
    sql = f"""
        WITH txns AS (
            SELECT t.id AS txn_id, t.date, t.flow, t.amount, t.qty, t.unit,
                   t.payment_method, t.transfer_bank,
                   t.needs_account_review, t.account_id,
                   c.code AS kategori_code, c.name AS kategori_name,
                   i.name AS item_name, i.stock_item_id,
                   a.code AS account_code, a.name AS account_name
            FROM ledger_transaction t
            JOIN master_category c ON c.id = t.category_id
            JOIN master_item i ON i.id = t.item_id
            JOIN ledger_account a ON a.id = t.account_id
            WHERE t.deleted_at IS NULL
              AND t.date >= %s AND t.date <= %s
              AND {cat_where}
        ),
        mov_daily AS (
            SELECT stock_item_id, date,
                   SUM(CASE direction WHEN 'in' THEN qty ELSE -qty END) AS signed_qty
            FROM stock_stockmovement
            WHERE deleted_at IS NULL
              AND date >= %s AND date <= %s
            GROUP BY stock_item_id, date
        ),
        mov_run AS (
            SELECT stock_item_id, date,
                   SUM(signed_qty) OVER (
                       PARTITION BY stock_item_id ORDER BY date
                       ROWS UNBOUNDED PRECEDING
                   ) AS run_delta
            FROM mov_daily
        )
        SELECT k.date AS tanggal,
               k.txn_id AS id,
               k.kategori_name AS kategori,
               k.item_name AS item,
               k.stock_item_id AS stock_item_id,
               k.flow AS flow,
               k.amount AS amount,
               k.qty AS qty,
               k.unit AS unit,
               k.payment_method AS payment_method,
               k.transfer_bank AS transfer_bank,
               k.needs_account_review AS needs_account_review,
               k.account_id AS account_id,
               k.account_code AS account_code,
               k.account_name AS account_name,
               0::numeric AS saldo_kas,
               0::numeric AS saldo_sumber,
               COALESCE(si.opening_qty, 0) + COALESCE(mv.run_delta, 0) AS stok_berjalan
        FROM txns k
        LEFT JOIN master_stockitem si ON si.id = k.stock_item_id
        LEFT JOIN LATERAL (
            SELECT run_delta
            FROM mov_run mr
            WHERE mr.stock_item_id = k.stock_item_id AND mr.date <= k.date
            ORDER BY mr.date DESC
            LIMIT 1
        ) mv ON true
        ORDER BY k.date, k.txn_id
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def _cash_ledger(
    date_from: date,
    date_to: date,
    details: list[dict],
    accounts: list[dict],
) -> list[dict]:
    """Merge internal transfers into the cash detail without changing operating totals."""
    balances = {row["code"]: row["opening"] for row in accounts}
    account_names = {row["code"]: row["name"] for row in accounts}
    visible_details = {row["id"]: row for row in details}
    events = []
    for txn in Transaction.objects.filter(date__gte=date_from, date__lte=date_to).select_related(
        "account"
    ):
        code = txn.account.code or "cash"
        events.append(
            (
                txn.date,
                0,
                txn.pk,
                "transaction",
                {
                    "id": txn.pk,
                    "account_id": txn.account_id,
                    "account_code": code,
                    "account_name": txn.account.name,
                    "flow": txn.flow,
                    "amount": txn.amount,
                    "detail": visible_details.get(txn.pk),
                },
            )
        )
    for transfer in AccountTransfer.objects.filter(
        date__gte=date_from,
        date__lte=date_to,
    ).select_related("from_account", "to_account"):
        source_code = transfer.from_account.code or "cash"
        destination_code = transfer.to_account.code or "cash"
        if source_code not in balances or destination_code not in balances:
            continue
        events.append(
            (
                transfer.date,
                1,
                transfer.pk,
                "transfer",
                {
                    "tanggal": transfer.date,
                    "id": transfer.pk,
                    "entry_type": "transfer",
                    "kategori": "Pindah dana",
                    "item": f"{transfer.from_account.name} → {transfer.to_account.name}",
                    "stock_item_id": None,
                    "flow": "transfer",
                    "amount": transfer.amount,
                    "qty": None,
                    "unit": None,
                    "payment_method": None,
                    "transfer_bank": None,
                    "needs_account_review": False,
                    "account_id": transfer.from_account_id,
                    "account_code": source_code,
                    "account_name": transfer.from_account.name,
                    "transfer_to": transfer.to_account.name,
                    "transfer_from_code": source_code,
                    "transfer_to_code": destination_code,
                    "stok_berjalan": None,
                },
            )
        )

    merged = []
    for _when, _kind_order, _pk, event_type, row in sorted(events):
        if event_type == "transfer":
            source_code = row["transfer_from_code"]
            destination_code = row["transfer_to_code"]
            balances[source_code] -= row["amount"]
            balances[destination_code] += row["amount"]
        else:
            code = row["account_code"] or "cash"
            delta = row["amount"] if row["flow"] == "income" else -row["amount"]
            balances[code] = balances.get(code, ZERO) + delta
            row = row["detail"]
            if row is None:
                continue
            row["account_code"] = code
            row["account_name"] = row["account_name"] or account_names.get(code, "Tunai")
            row["entry_type"] = "transaction"
        row["saldo_sumber"] = balances.get(row["account_code"], ZERO)
        row["saldo_kas"] = sum(balances.values(), ZERO)
        merged.append(row)
    return merged


def _stock_rows(date_from: date, date_to: date) -> list[StockRecapRow]:
    """opening/in/out/adj/closing per jenis stok (agregasi SQL, FILTER clause)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT s.id, s.code, s.name, s.unit, s.opening_qty,
                   COALESCE(SUM(m.qty) FILTER (
                       WHERE m.direction = 'in'
                         AND m.source <> 'adjustment'
                         AND m.date >= %s AND m.date <= %s
                   ), 0) AS in_qty,
                   COALESCE(SUM(m.qty) FILTER (
                       WHERE m.direction = 'out'
                         AND m.source <> 'adjustment'
                         AND m.date >= %s AND m.date <= %s
                   ), 0) AS out_qty,
                   COALESCE(SUM(CASE m.direction WHEN 'in' THEN m.qty ELSE -m.qty END) FILTER (
                       WHERE m.source = 'adjustment'
                         AND m.date >= %s AND m.date <= %s
                   ), 0) AS adj,
                   COALESCE(SUM(CASE m.direction WHEN 'in' THEN m.qty ELSE -m.qty END) FILTER (
                       WHERE m.date < %s
                   ), 0) AS before_delta
            FROM master_stockitem s
            LEFT JOIN stock_stockmovement m
              ON m.stock_item_id = s.id AND m.deleted_at IS NULL
            GROUP BY s.id, s.code, s.name, s.unit, s.opening_qty
            ORDER BY s.id
            """,
            [date_from, date_to, date_from, date_to, date_from, date_to, date_from],
        )
        rows = []
        for (
            stock_item_id,
            code,
            name,
            unit,
            opening,
            in_qty,
            out_qty,
            adj,
            before_delta,
        ) in cursor.fetchall():
            opening = Decimal(opening or 0)
            opening_period = opening + Decimal(before_delta or 0)
            closing = (
                opening_period + Decimal(in_qty or 0) - Decimal(out_qty or 0) + Decimal(adj or 0)
            )
            rows.append(
                StockRecapRow(
                    stock_item_id=stock_item_id,
                    kode=code,
                    nama=name,
                    satuan=unit or "",
                    opening=opening_period,
                    in_qty=Decimal(in_qty or 0),
                    out_qty=Decimal(out_qty or 0),
                    adj=Decimal(adj or 0),
                    closing=closing,
                )
            )
    return rows
    return rows


def _recap_range(date_from: date, date_to: date, period_label: str, category_ids) -> RecapResult:
    if date_from > date_to:
        raise DomainError(
            messages.DATE_RANGE, code="date_range", fields={"date": messages.DATE_RANGE}
        )
    base = _base_transactions(date_from, date_to, category_ids)
    accounts = _account_summaries(date_from, date_to)
    detail = _detail_rows(date_from, date_to, category_ids)
    account_total = {
        key: sum((row[key] for row in accounts), ZERO)
        for key in (
            "opening",
            "transaction_in",
            "transaction_out",
            "transfer_in",
            "transfer_out",
            "closing",
        )
    }
    return RecapResult(
        date_from=date_from,
        date_to=date_to,
        period_label=period_label,
        summary=_summary_rows(base),
        detail=_cash_ledger(date_from, date_to, detail, accounts),
        stock=_stock_rows(date_from, date_to),
        accounts=accounts,
        account_total=account_total,
    )


def daily_recap(date_from: date, date_to: date, category_ids=None) -> RecapResult:
    """Rekap harian: detail per transaksi + 4 baris D2 + stok per jenis."""
    if date_from == date_to:
        label = format_date_id(date_from)
    else:
        label = f"{format_date_id(date_from)} – {format_date_id(date_to)}"
    return _recap_range(date_from, date_to, label, category_ids)


def weekly_recap(week_start: date, category_ids=None) -> RecapResult:
    """Rekap mingguan: ISO Senin–Minggu."""
    start = week(week_start).start
    end = start + timedelta(days=6)
    return _recap_range(start, end, format_period_label(start, end), category_ids)


def monthly_recap(month_start_value: date, category_ids=None) -> RecapResult:
    """Rekap bulanan: transaksi berdasarkan tanggal, daftar gaji berdasarkan periodenya."""
    start = month_start(month_start_value)
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    result = _recap_range(start, end, format_month_id(start), category_ids)
    salary_transactions = Transaction.objects.filter(
        flow="expense",
        item__frequency="monthly",
        period_month=start,
    ).select_related("category", "item")
    opening_date = Account.objects.order_by("opening_balance_date").values_list(
        "opening_balance_date", flat=True
    ).first()
    if opening_date is not None:
        salary_transactions = salary_transactions.filter(date__gte=opening_date)
    category_pks = _category_pks(category_ids)
    if category_pks is not None:
        salary_transactions = salary_transactions.filter(category_id__in=category_pks)
    gaji = [
        {
            "tanggal": txn.date,
            "periode": format_month_id(txn.period_month),
            "kategori": txn.category.name,
            "item": txn.item.name,
            "amount": txn.amount,
        }
        for txn in salary_transactions.order_by("date", "id")
    ]
    return replace(result, gaji=gaji)


def yearly_recap(year: int, category_ids=None) -> RecapResult:
    """Rekap tahunan: 12 bulan dengan 4 baris per bulan + total tahunan."""
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    base = _base_transactions(start, end, category_ids)
    result = _recap_range(start, end, str(year), category_ids)

    month_rows = (
        base.annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(
            pemasukan=Sum("amount", filter=Q(flow="income", is_opening_correction=False)),
            pengeluaran=Sum("amount", filter=Q(flow="expense", is_opening_correction=False)),
            mutasi=Sum(
                Case(
                    When(flow="income", then=F("amount")),
                    default=-F("amount"),
                ),
                filter=Q(is_opening_correction=True),
            ),
        )
        .order_by("month")
    )
    kategori_rows = (
        base.annotate(month=TruncMonth("date"))
        .values("month", "category__code", "category__name")
        .annotate(
            pemasukan=Sum("amount", filter=Q(flow="income", is_opening_correction=False)),
            pengeluaran=Sum("amount", filter=Q(flow="expense", is_opening_correction=False)),
        )
        .order_by("month", "category__code")
    )
    by_month: dict[date, list[dict]] = {}
    for row in kategori_rows:
        by_month.setdefault(row["month"], []).append(
            {
                "kode": row["category__code"],
                "kategori": row["category__name"],
                "pemasukan": row["pemasukan"] or ZERO,
                "pengeluaran": row["pengeluaran"] or ZERO,
            }
        )

    months = []
    cursor_date = start
    while cursor_date.year == year:
        agg = next((row for row in month_rows if row["month"] == cursor_date), None)
        if agg is None:
            pemasukan = pengeluaran = mutasi = ZERO
        else:
            pemasukan = agg["pemasukan"] or ZERO
            pengeluaran = agg["pengeluaran"] or ZERO
            mutasi = agg["mutasi"] or ZERO
        months.append(
            {
                "bulan": cursor_date,
                "label": format_month_id(cursor_date),
                "summary": [
                    {"key": "pemasukan", "label": "Pemasukan", "amount": pemasukan},
                    {"key": "pengeluaran", "label": "Pengeluaran", "amount": pengeluaran},
                    {
                        "key": "mutasi",
                        "label": "Mutasi non-operasional (koreksi saldo awal)",
                        "amount": mutasi,
                    },
                    {
                        "key": "selisih",
                        "label": "Selisih",
                        "amount": pemasukan - pengeluaran + mutasi,
                    },
                ],
                "kategori": by_month.get(cursor_date, []),
            }
        )
        cursor_date = add_months(cursor_date, 1)

    return replace(result, months=months)

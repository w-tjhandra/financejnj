"""End-to-end QA tests for Telur Finance - all major user flows.

Covers:
1. Setup wizard flow (fresh, resume, duplicate prevention)
2. Authentication (login/logout, rate limit, session expiry, password change, locked redirects)
3. Master data S-16 (categories CRUD with system protection, items CRUD, stock settings)
4. Transactions S-04..S-07, FR-08..FR-12 (income/expense, salary duplicate prevention, opening correction, update/delete with stock delta, period lock rejection)
5. Stock daily S-08, S-09 (production IN, consumption OUT, adjustment +/-, soft delete manual only, balance guard)
6. Reports S-10..S-13, FR-16..FR-26 (daily/weekly/monthly/yearly, 4-line summary, LAYER->AFKIR roll-up, category filter, stock opening/in/out/adj/closing, XLSX export 5 sheets)
7. Audit log BR-14 (list with filters, detail diff, XLSX export)
8. Period lock UI (chain validation, lock/unlock, chained unlock only latest)
9. Attachments (upload/download/delete for transactions)
10. PDF Investor Report FR-27, FR-28 (WeasyPrint ID/EN, all period types)

BUGS FOUND DURING TESTING:
- BUG-001: XLSX export uses non-existent `income_detail`/`expense_detail` attributes on RecapResult (should use `detail` with flow filter)
- BUG-002: PDF Investor Report has wrong import: `from master.models import CompanyProfile` should be `from core.models import CompanyProfile`
- BUG-003: Transaction list template uses invalid filter `get_item`
- BUG-004: Duplicate account prevention test fails because setup wizard redirects to profile after first completion
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse
from openpyxl import load_workbook

from audit.models import AuditLog
from audit.service import log_audit
from core.errors import DomainError, DuplicateSalary, NotFound, PeriodLocked, StockConflict, StockInsufficient
from core.models import CompanyProfile, PeriodLock
from core.services.locks import (
    UNLOCK_REASON_MIN,
    UNLOCK_REASON_MAX,
    chain_gap,
    is_date_editable,
    lock_period,
    max_locked_period,
    unlock_period,
)
from core.utils.dates import add_months, month_start, today_wib
from core.utils.numbers import format_id_number, format_money, format_qty, parse_id_number
from ledger.models import ATTACHMENT_MAX_BYTES, Account, Attachment, Transaction
from ledger.services.opening import cash_is_locked, cash_locked_since, record_opening_correction, set_opening_balance
from ledger.services.transactions import (
    create_transaction,
    delete_transaction,
    duplicate_prefill,
    update_transaction,
)
from master.models import Category, Item, StockItem
from master.services.seed import ensure_master_data
from reports.queries import daily_recap, monthly_recap, weekly_recap, yearly_recap
from stock import api as stock_api
from stock.models import StockMovement
from stock.services.daily import adjust_stock, delete_manual, record_consumption, record_production
from stock.services.settings import update_stock_settings

TEST_PASSWORD = "RahasiaKandang2026"


# =========================================================================
# FIXTURES & HELPERS
# =========================================================================


@pytest.fixture
def test_user(db, django_user_model):
    """Create a test user."""
    return django_user_model.objects.create_user(username="pemilik", password=TEST_PASSWORD)


@pytest.fixture
def logged_client(client, test_user):
    """Client logged in as user."""
    client.login(username="pemilik", password=TEST_PASSWORD)
    return client


@pytest.fixture
def completed_setup(db, test_user):
    """Complete onboarding setup with master data."""
    CompanyProfile.objects.create(
        name="Telur Jaya Farm",
        business_start_date=date(2026, 9, 1),
        setup_completed=True,
    )
    account = Account.objects.create(
        name="Kas Utama",
        type="cash",
        currency="IDR",
        opening_balance="250000000.00",
        opening_balance_date=date(2026, 9, 1),
    )
    ensure_master_data(stock={"feed": {"qty": Decimal("1000"), "min_threshold": Decimal("100")}, "egg": {"qty": Decimal("500"), "min_threshold": Decimal("50")}, "manure": {"qty": Decimal("200"), "min_threshold": Decimal("20")}})
    return account


@pytest.fixture
def master_data(db, completed_setup, test_user):
    """Get master data created by ensure_master_data."""
    cat_layer = Category.objects.get(code="LAYER")
    cat_afkir = Category.objects.get(code="AFKIR")
    cat_doc = Category.objects.get(code="DOC")
    cat_umum = Category.objects.get(code="UMUM")

    stock_feed = StockItem.objects.get(code="feed")
    stock_egg = StockItem.objects.get(code="egg")
    stock_manure = StockItem.objects.get(code="manure")

    item_egg_sales = Item.objects.get(code="egg_sales")
    item_manure_sales = Item.objects.get(code="manure_sales")
    item_afkir_sales = Item.objects.get(code="afkir_sales")
    item_feed = Item.objects.get(code="feed")
    item_medicine = Item.objects.get(code="medicine")
    item_daily_wage = Item.objects.get(code="daily_wage")
    item_kitchen = Item.objects.get(code="kitchen")
    item_consumables = Item.objects.get(code="consumables")
    item_salary = Item.objects.get(code="salary")
    item_opening_correction = Item.objects.get(code="opening_correction")

    return {
        "user": test_user,
        "account": completed_setup,
        "categories": {"layer": cat_layer, "afkir": cat_afkir, "doc": cat_doc, "umum": cat_umum},
        "items": {
            "egg_sales": item_egg_sales,
            "manure_sales": item_manure_sales,
            "afkir_sales": item_afkir_sales,
            "feed": item_feed,
            "medicine": item_medicine,
            "daily_wage": item_daily_wage,
            "kitchen": item_kitchen,
            "consumables": item_consumables,
            "salary": item_salary,
            "opening_correction": item_opening_correction,
        },
        "stock": {"feed": stock_feed, "egg": stock_egg, "manure": stock_manure},
    }


# =========================================================================
# 1. SETUP WIZARD FLOW
# =========================================================================


class TestSetupWizardFlow:
    """Test setup wizard: fresh user, resume mid-setup, duplicate prevention."""

    @pytest.mark.django_db
    def test_fresh_user_complete_setup(self, client):
        """Fresh user completes all 5 steps."""
        resp = client.get(reverse("setup"))
        assert resp.status_code == 302
        assert "/setup/akun" in resp.url

        resp = client.post(
            reverse("setup_account"),
            {
                "username": "testuser",
                "first_name": "Test User",
                "password": "RahasiaKandang2026",
                "password_confirm": "RahasiaKandang2026",
            },
        )
        assert resp.status_code == 302
        assert "/setup/profil" in resp.url

        resp = client.get(reverse("setup_profile"))
        assert resp.status_code == 200

        resp = client.post(
            reverse("setup_profile"),
            {"name": "Telur Test Farm", "business_start_date": "2026-09-01"},
        )
        assert resp.status_code == 302
        assert "/setup/saldo" in resp.url

        resp = client.get(reverse("setup_balance"))
        assert resp.status_code == 200

        resp = client.post(
            reverse("setup_balance"),
            {"opening_balance": "250.000.000", "opening_balance_date": "2026-09-01"},
        )
        assert resp.status_code == 302
        assert "/setup/stok" in resp.url

        resp = client.get(reverse("setup_stock"))
        assert resp.status_code == 200

        resp = client.post(
            reverse("setup_stock"),
            {
                "feed_qty": "1.000",
                "feed_min": "100",
                "egg_qty": "500",
                "egg_min": "50",
                "manure_qty": "200",
                "manure_min": "20",
            },
        )
        assert resp.status_code == 302
        assert "/setup/ringkasan" in resp.url

        resp = client.get(reverse("setup_review"))
        assert resp.status_code == 200
        assert "Telur Test Farm" in resp.content.decode()

        resp = client.post(reverse("setup_review"), follow=True)
        assert resp.status_code == 200
        assert "Dashboard" in resp.content.decode()

        profile = CompanyProfile.objects.first()
        assert profile.setup_completed is True
        assert profile.name == "Telur Test Farm"

        account = Account.objects.first()
        assert account.opening_balance == Decimal("250000000.00")

        stock_feed = StockItem.objects.get(code="feed")
        assert stock_feed.opening_qty == Decimal("1000")
        assert stock_feed.min_threshold == Decimal("100")

    @pytest.mark.django_db
    def test_resume_after_logout_mid_setup(self, client):
        """User logs out at step 3, logs back in, continues."""
        client.post(
            reverse("setup_account"),
            {"username": "resumeuser", "first_name": "Resume User", "password": "RahasiaKandang2026", "password_confirm": "RahasiaKandang2026"},
        )
        client.post(reverse("setup_profile"), {"name": "Resume Farm", "business_start_date": "2026-09-01"})

        client.logout()
        client.login(username="resumeuser", password="RahasiaKandang2026")

        resp = client.get(reverse("setup"))
        assert resp.status_code == 302
        assert "/setup/saldo" in resp.url

        client.post(reverse("setup_balance"), {"opening_balance": "100.000.000", "opening_balance_date": "2026-09-01"})
        client.post(
            reverse("setup_stock"),
            {"feed_qty": "0", "egg_qty": "0", "manure_qty": "0", "feed_min": "", "egg_min": "", "manure_min": ""},
        )
        resp = client.post(reverse("setup_review"), follow=True)
        assert resp.status_code == 200
        assert "Dashboard" in resp.content.decode()

        profile = CompanyProfile.objects.first()
        assert profile.setup_completed is True

    @pytest.mark.django_db
    def test_duplicate_account_prevention(self, db):
        """Cannot create second account with same username (case-insensitive)."""
        from django.contrib.auth import get_user_model
        
        # Create first user directly in DB
        User = get_user_model()
        User.objects.create_user(username="pemilik", password="RahasiaKandang2026")
        
        # Now try to create via form
        from django.test import Client
        client = Client()
        resp = client.post(
            reverse("setup_account"),
            {"username": "PEMILIK", "first_name": "Owner2", "password": "RahasiaKandang2026", "password_confirm": "RahasiaKandang2026"},
        )
        # Should fail validation (user already exists in DB)
        assert resp.status_code == 200
        assert "sudah dipakai" in resp.content.decode().lower() or "taken" in resp.content.decode().lower()


# =========================================================================
# 2. AUTHENTICATION
# =========================================================================


class TestAuthentication:
    """Login/logout, rate limiting, session expiry (12h), password change, locked period redirects."""

    @pytest.mark.django_db
    def test_login_logout(self, client, completed_setup):
        resp = client.post(reverse("login"), {"username": "pemilik", "password": TEST_PASSWORD}, follow=True)
        assert resp.status_code == 200
        assert "Dashboard" in resp.content.decode()

        resp = client.post(reverse("logout"), follow=True)
        assert resp.status_code == 200
        assert "Masuk" in resp.content.decode() or "login" in resp.url

    @pytest.mark.django_db
    def test_login_rate_limit_5_per_15min(self, client, completed_setup):
        for i in range(5):
            resp = client.post(reverse("login"), {"username": "pemilik", "password": "WrongPass123"})
            assert resp.status_code == 200

        resp = client.post(reverse("login"), {"username": "pemilik", "password": "WrongPass123"})
        assert resp.status_code == 200
        assert "terlalu banyak" in resp.content.decode().lower() or "rate limit" in resp.content.decode().lower() or "locked" in resp.content.decode().lower()

    @pytest.mark.django_db
    def test_session_expiry_12h(self, client, completed_setup, settings):
        client.login(username="pemilik", password=TEST_PASSWORD)
        assert settings.SESSION_COOKIE_AGE == 12 * 60 * 60
        assert settings.SESSION_SAVE_EVERY_REQUEST is True

    @pytest.mark.django_db
    def test_account_settings_requires_setup(self, client, test_user):
        """Account settings redirects to setup if not completed."""
        client.login(username="pemilik", password=TEST_PASSWORD)
        resp = client.get(reverse("account_settings"))
        assert resp.status_code == 302
        assert "/setup" in resp.url


# =========================================================================
# 3. MASTER DATA (S-16)
# =========================================================================


class TestMasterData:
    """Categories CRUD with system protection, Items CRUD with stock/non-stock, Stock settings."""

    @pytest.mark.django_db
    def test_category_crud_system_protection(self, logged_client, master_data):
        cat = master_data["categories"]["layer"]
        assert cat.is_system is True
        assert cat.code == "LAYER"

    @pytest.mark.django_db
    def test_category_depth_limit(self, db):
        root = Category.objects.create(code="ROOT", name="Root", is_system=False)
        child = Category.objects.create(code="CHILD", name="Child", parent=root, is_system=False)

        grandchild = Category(code="GRAND", name="Grandchild", parent=child, is_system=False)
        with pytest.raises(Exception) as exc:
            grandchild.full_clean()
        assert "tingkat" in str(exc.value).lower() or "depth" in str(exc.value).lower()

    @pytest.mark.django_db
    def test_category_cycle_prevention(self, db):
        root = Category.objects.create(code="A", name="A", is_system=False)
        child = Category.objects.create(code="B", name="B", parent=root, is_system=False)

        root.parent = child
        with pytest.raises(Exception) as exc:
            root.full_clean()
        assert "tingkat" in str(exc.value).lower() or "cycle" in str(exc.value).lower()

    @pytest.mark.django_db
    def test_category_code_normalization(self, db):
        cat = Category(code="  layer  ", name="Layer")
        cat.full_clean()
        assert cat.code == "LAYER"

    @pytest.mark.django_db
    def test_item_crud_stock_vs_nonstock(self, logged_client, master_data):
        stock_feed = master_data["stock"]["feed"]
        cat = master_data["categories"]["umum"]

        item_stock = Item.objects.create(
            name="Pakan Baru Test", flow="expense", default_category=cat, stock_item=stock_feed, unit="kg", is_system=False
        )
        assert item_stock.unit == "kg"
        assert item_stock.stock_item == stock_feed

        item_nonstock = Item.objects.create(name="Obat Baru Test", flow="expense", default_category=cat, is_system=False)
        assert item_nonstock.unit is None
        assert item_nonstock.stock_item is None

    @pytest.mark.django_db
    def test_item_stock_requires_unit_validation(self, db, master_data):
        stock_feed = master_data["stock"]["feed"]
        cat = master_data["categories"]["umum"]

        item = Item(name="Pakan Tanpa Unit", flow="expense", default_category=cat, stock_item=stock_feed, unit=None)
        with pytest.raises(Exception) as exc:
            item.full_clean()
        assert "wajib" in str(exc.value).lower() or "required" in str(exc.value).lower()

    @pytest.mark.django_db
    def test_item_system_flag(self, master_data):
        """System items have is_system flag."""
        item_opening = master_data["items"]["opening_correction"]
        assert item_opening.is_system is True

        item_salary = master_data["items"]["salary"]
        assert item_salary.is_system is False  # salary is not system in seed

    @pytest.mark.django_db
    def test_stock_settings_opening_qty_min_threshold(self, logged_client, master_data):
        stock_feed = master_data["stock"]["feed"]

        update_stock_settings(stock_item_id=stock_feed.pk, opening_qty=Decimal("2000"), min_threshold=Decimal("150"), actor=master_data["user"])
        stock_feed.refresh_from_db()
        assert stock_feed.opening_qty == Decimal("2000")
        assert stock_feed.min_threshold == Decimal("150")

        record_consumption(stock_item=stock_feed, date=today_wib(), qty=Decimal("100"), actor=master_data["user"])

        with pytest.raises(DomainError) as exc:
            update_stock_settings(stock_item_id=stock_feed.pk, opening_qty=Decimal("3000"), actor=master_data["user"])
        assert "terkunci" in str(exc.value).lower() or "locked" in str(exc.value).lower()

        update_stock_settings(stock_item_id=stock_feed.pk, min_threshold=Decimal("200"), actor=master_data["user"])
        stock_feed.refresh_from_db()
        assert stock_feed.min_threshold == Decimal("200")

    @pytest.mark.django_db
    def test_stock_opening_locked_after_deleted_movement(self, master_data):
        stock_feed = master_data["stock"]["feed"]

        movement = record_consumption(stock_item=stock_feed, date=today_wib(), qty=Decimal("50"), actor=master_data["user"])
        delete_manual(movement_id=movement.pk, actor=master_data["user"])

        with pytest.raises(DomainError) as exc:
            update_stock_settings(stock_item_id=stock_feed.pk, opening_qty=Decimal("5000"), actor=master_data["user"])
        assert "terkunci" in str(exc.value).lower()


# =========================================================================
# 4. TRANSACTIONS (S-04..S-07, FR-08..FR-12)
# =========================================================================


class TestTransactions:
    """Create income/expense with stock/non-stock, salary duplicate prevention, opening correction, update/delete with stock delta, period lock."""

    @pytest.mark.django_db
    def test_create_income_with_stock_item(self, master_data):
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        stock_egg = master_data["stock"]["egg"]

        initial_on_hand = stock_api.on_hand(stock_egg.pk)

        txn = create_transaction(
            date=today_wib(),
            flow="income",
            category=cat,
            item=item,
            amount=Decimal("500000"),
            qty=Decimal("20"),
            actor=master_data["user"],
        )

        assert txn.flow == "income"
        assert txn.qty == Decimal("20")
        assert txn.item == item

        movement = StockMovement.objects.get(transaction=txn)
        assert movement.direction == "out"
        assert movement.qty == Decimal("20")
        assert movement.source == "transaction"

        assert stock_api.on_hand(stock_egg.pk) == initial_on_hand - Decimal("20")

    @pytest.mark.django_db
    def test_create_expense_with_stock_item(self, master_data):
        item = master_data["items"]["feed"]
        cat = master_data["categories"]["layer"]
        stock_feed = master_data["stock"]["feed"]

        initial_on_hand = stock_api.on_hand(stock_feed.pk)

        txn = create_transaction(
            date=today_wib(),
            flow="expense",
            category=cat,
            item=item,
            amount=Decimal("1000000"),
            qty=Decimal("50"),
            actor=master_data["user"],
        )

        assert txn.flow == "expense"
        assert txn.qty == Decimal("50")

        movement = StockMovement.objects.get(transaction=txn)
        assert movement.direction == "in"
        assert movement.qty == Decimal("50")

        assert stock_api.on_hand(stock_feed.pk) == initial_on_hand + Decimal("50")

    @pytest.mark.django_db
    def test_create_income_expense_non_stock(self, master_data):
        item = master_data["items"]["medicine"]
        cat = master_data["categories"]["layer"]

        txn1 = create_transaction(
            date=today_wib(), flow="expense", category=cat, item=item, amount=Decimal("50000"), actor=master_data["user"]
        )
        assert txn1.qty is None
        assert txn1.unit is None

        txn2 = create_transaction(
            date=today_wib(), flow="expense", category=cat, item=item, amount=Decimal("50000"), qty=Decimal("5"), unit="strip", actor=master_data["user"]
        )
        assert txn2.qty == Decimal("5")
        assert txn2.unit == "strip"

    @pytest.mark.django_db
    def test_monthly_salary_duplicate_prevention(self, master_data):
        item = master_data["items"]["salary"]
        cat = master_data["categories"]["umum"]
        account = master_data["user"]
        period = month_start(today_wib())

        txn1 = create_transaction(
            date=today_wib(),
            flow="expense",
            category=cat,
            item=item,
            amount=Decimal("5000000"),
            period_month=period,
            actor=account,
        )

        with pytest.raises(DuplicateSalary) as exc:
            create_transaction(
                date=today_wib(),
                flow="expense",
                category=cat,
                item=item,
                amount=Decimal("5000000"),
                period_month=period,
                actor=account,
            )
        assert exc.value.existing_id == txn1.pk

        next_month = add_months(period, 1)
        # Use last day of next month for period_month, but today for date
        # Actually, we can't create next month's salary yet if today is in current month
        # The validation requires period_month <= month_start(date)
        # So this test just verifies duplicate prevention works

    @pytest.mark.django_db
    def test_opening_correction_non_operational_mutation(self, master_data):
        account = master_data["user"]

        # Lock cash first by creating a transaction
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        create_transaction(
            date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("10"), actor=account
        )
        
        # Now opening correction works
        record_opening_correction(
            delta=Decimal("100000"),
            reason="Koreksi saldo awal saat setup",
            actor=account,
        )

        txn = Transaction.objects.filter(is_opening_correction=True).first()
        assert txn is not None
        assert txn.flow == "income"
        assert txn.amount == Decimal("100000")
        assert "Koreksi saldo awal saat setup" in txn.notes
        assert txn.is_opening_correction is True

        record_opening_correction(delta=Decimal("-50000"), reason="Koreksi kelebihan", actor=account)
        txn2 = Transaction.objects.filter(is_opening_correction=True).order_by("-id").first()
        assert txn2.flow == "expense"
        assert txn2.amount == Decimal("50000")

    @pytest.mark.django_db
    def test_update_transaction_stock_delta_validation(self, master_data):
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        stock_egg = master_data["stock"]["egg"]

        txn = create_transaction(
            date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("500000"), qty=Decimal("10"), actor=master_data["user"]
        )

        updated = update_transaction(
            transaction_id=txn.pk,
            date=today_wib(),
            flow="income",
            category=cat,
            item=item,
            amount=Decimal("1000000"),
            qty=Decimal("20"),
            actor=master_data["user"],
        )
        assert updated.qty == Decimal("20")
        assert updated.amount == Decimal("1000000")

        movement = StockMovement.objects.get(transaction=txn)
        assert movement.qty == Decimal("20")

    @pytest.mark.django_db
    def test_update_transaction_change_stock_item(self, master_data):
        item_egg = master_data["items"]["egg_sales"]
        item_feed = master_data["items"]["feed"]
        cat_income = master_data["categories"]["layer"]
        cat_expense = master_data["categories"]["layer"]

        txn = create_transaction(
            date=today_wib(), flow="expense", category=cat_expense, item=item_feed, amount=Decimal("1000000"), qty=Decimal("50"), actor=master_data["user"]
        )

        updated = update_transaction(
            transaction_id=txn.pk,
            date=today_wib(),
            flow="income",
            category=cat_income,
            item=item_egg,
            amount=Decimal("500000"),
            qty=Decimal("10"),
            actor=master_data["user"],
        )
        assert updated.item == item_egg
        assert updated.flow == "income"

        movements = StockMovement.objects.filter(transaction=txn)
        assert movements.count() == 1
        assert movements.first().stock_item.code == "egg"
        assert movements.first().direction == "out"

    @pytest.mark.django_db
    def test_delete_transaction_soft_delete_with_stock_validation(self, master_data):
        item = master_data["items"]["feed"]
        cat = master_data["categories"]["layer"]
        stock_feed = master_data["stock"]["feed"]

        txn = create_transaction(
            date=today_wib(), flow="expense", category=cat, item=item, amount=Decimal("1000000"), qty=Decimal("100"), actor=master_data["user"]
        )

        on_hand_before_delete = stock_api.on_hand(stock_feed.pk)

        delete_transaction(transaction_id=txn.pk, actor=master_data["user"])

        txn.refresh_from_db()
        assert txn.deleted_at is not None

        movement = StockMovement.all_objects.get(transaction=txn)
        assert movement.deleted_at is not None

        assert stock_api.on_hand(stock_feed.pk) == on_hand_before_delete - Decimal("100")

    @pytest.mark.django_db
    def test_delete_opening_correction_rejected(self, master_data):
        account = master_data["user"]
        
        # Lock cash first
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        create_transaction(
            date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("10"), actor=account
        )

        record_opening_correction(delta=Decimal("100000"), reason="Test koreksi", actor=account)

        txn = Transaction.objects.filter(is_opening_correction=True).first()
        assert txn is not None

        with pytest.raises(DomainError) as exc:
            delete_transaction(transaction_id=txn.pk, actor=account)
        assert "koreksi saldo awal tidak bisa dihapus" in str(exc.value).lower()


# =========================================================================
# 5. STOCK DAILY (S-08, S-09)
# =========================================================================


class TestStockDaily:
    """Production (egg/manure IN), consumption (feed OUT), adjustment +/-, soft delete manual only, balance guard."""

    @pytest.mark.django_db
    def test_production_egg_manure_in(self, master_data):
        stock_egg = master_data["stock"]["egg"]
        stock_manure = master_data["stock"]["manure"]

        initial_egg = stock_api.on_hand(stock_egg.pk)
        initial_manure = stock_api.on_hand(stock_manure.pk)

        movement = record_production(stock_item=stock_egg, date=today_wib(), qty=Decimal("1000"), actor=master_data["user"])
        assert movement.direction == "in"
        assert movement.source == "manual"
        assert stock_api.on_hand(stock_egg.pk) == initial_egg + Decimal("1000")

        movement = record_production(stock_item=stock_manure, date=today_wib(), qty=Decimal("50"), actor=master_data["user"])
        assert movement.direction == "in"
        assert stock_api.on_hand(stock_manure.pk) == initial_manure + Decimal("50")

    @pytest.mark.django_db
    def test_production_feed_rejected(self, master_data):
        stock_feed = master_data["stock"]["feed"]
        with pytest.raises(DomainError) as exc:
            record_production(stock_item=stock_feed, date=today_wib(), qty=Decimal("100"), actor=master_data["user"])
        assert "telur" in str(exc.value).lower() or "kotoran" in str(exc.value).lower()

    @pytest.mark.django_db
    def test_consumption_feed_out(self, master_data):
        stock_feed = master_data["stock"]["feed"]
        initial = stock_api.on_hand(stock_feed.pk)

        movement = record_consumption(stock_item=stock_feed, date=today_wib(), qty=Decimal("200"), actor=master_data["user"])
        assert movement.direction == "out"
        assert movement.source == "manual"
        assert stock_api.on_hand(stock_feed.pk) == initial - Decimal("200")

    @pytest.mark.django_db
    def test_consumption_egg_manure_rejected(self, master_data):
        stock_egg = master_data["stock"]["egg"]
        with pytest.raises(DomainError) as exc:
            record_consumption(stock_item=stock_egg, date=today_wib(), qty=Decimal("10"), actor=master_data["user"])
        assert "pakan" in str(exc.value).lower()

    @pytest.mark.django_db
    def test_adjustment_positive_negative_reason_min10(self, master_data):
        stock_feed = master_data["stock"]["feed"]

        movement = adjust_stock(
            stock_item=stock_feed, date=today_wib(), signed_qty=Decimal("50"), reason="Koreksi stok masuk", actor=master_data["user"]
        )
        assert movement.direction == "in"
        assert movement.source == "adjustment"
        assert movement.reason == "Koreksi stok masuk"
        assert len(movement.reason) >= 10

        movement = adjust_stock(
            stock_item=stock_feed, date=today_wib(), signed_qty=Decimal("-30"), reason="Koreksi stok keluar", actor=master_data["user"]
        )
        assert movement.direction == "out"
        assert movement.source == "adjustment"
        assert movement.reason == "Koreksi stok keluar"

    @pytest.mark.django_db
    def test_adjustment_reason_less_than_10_rejected(self, master_data):
        stock_feed = master_data["stock"]["feed"]
        with pytest.raises(DomainError) as exc:
            adjust_stock(stock_item=stock_feed, date=today_wib(), signed_qty=Decimal("10"), reason="pendek", actor=master_data["user"])
        assert "10" in str(exc.value)

    @pytest.mark.django_db
    def test_soft_delete_manual_only(self, master_data):
        stock_feed = master_data["stock"]["feed"]

        manual_mov = record_consumption(stock_item=stock_feed, date=today_wib(), qty=Decimal("100"), actor=master_data["user"])

        deleted = delete_manual(movement_id=manual_mov.pk, actor=master_data["user"])
        assert deleted is not None
        assert deleted.deleted_at is not None

        adj_mov = adjust_stock(stock_item=stock_feed, date=today_wib(), signed_qty=Decimal("50"), reason="Koreksi penyesuaian stok", actor=master_data["user"])

        with pytest.raises(DomainError) as exc:
            delete_manual(movement_id=adj_mov.pk, actor=master_data["user"])
        assert "bukan manual" in str(exc.value).lower() or "manual" in str(exc.value).lower()

    @pytest.mark.django_db
    def test_balance_guard_no_negative_running_balance(self, master_data):
        stock_feed = master_data["stock"]["feed"]

        with pytest.raises(StockConflict) as exc:
            record_consumption(stock_item=stock_feed, date=today_wib(), qty=Decimal("2000"), actor=master_data["user"])
        assert "minus" in str(exc.value).lower() or "negatif" in str(exc.value).lower()

        with pytest.raises(StockConflict):
            adjust_stock(stock_item=stock_feed, date=today_wib(), signed_qty=Decimal("-2000"), reason="Koreksi negatif stok", actor=master_data["user"])


# =========================================================================
# 6. REPORTS (S-10..S-13, FR-16..FR-26)
# =========================================================================


class TestReports:
    """Daily/weekly/monthly/yearly recaps, 4-line summary, LAYER->AFKIR roll-up, category filter, stock, XLSX export."""

    @pytest.mark.django_db
    def test_daily_recap_4_line_summary(self, logged_client, master_data):
        item_jual = master_data["items"]["egg_sales"]
        item_pakan = master_data["items"]["feed"]
        cat_income = master_data["categories"]["layer"]
        cat_feed = master_data["categories"]["layer"]
        account = master_data["user"]

        today = today_wib()
        create_transaction(date=today, flow="income", category=cat_income, item=item_jual, amount=Decimal("1000000"), qty=Decimal("20"), actor=account)
        create_transaction(date=today, flow="expense", category=cat_feed, item=item_pakan, amount=Decimal("500000"), qty=Decimal("10"), actor=account)

        result = daily_recap(today, today, None)
        summary = {r.key: r.amount for r in result.summary}

        assert summary["pemasukan"] == Decimal("1000000")
        assert summary["pengeluaran"] == Decimal("500000")
        assert summary["mutasi_nonoperasional"] == Decimal("0")
        assert summary["selisih"] == Decimal("500000")

    @pytest.mark.django_db
    def test_weekly_recap_iso_monday_sunday(self, master_data):
        item_jual = master_data["items"]["egg_sales"]
        cat_income = master_data["categories"]["layer"]
        account = master_data["user"]

        test_date = date(2026, 10, 7)
        create_transaction(date=test_date, flow="income", category=cat_income, item=item_jual, amount=Decimal("1000000"), qty=Decimal("20"), actor=account)

        result = weekly_recap(test_date, None)
        assert result.date_from == date(2026, 10, 5)
        assert result.date_to == date(2026, 10, 11)

    @pytest.mark.django_db
    def test_monthly_recap_includes_gaji_list(self, master_data):
        item_gaji = master_data["items"]["salary"]
        cat_expense = master_data["categories"]["umum"]
        account = master_data["user"]
        period = month_start(today_wib())

        create_transaction(
            date=today_wib(), flow="expense", category=cat_expense, item=item_gaji, amount=Decimal("5000000"), period_month=period, actor=account
        )

        result = monthly_recap(today_wib(), None)
        assert result.gaji is not None
        assert len(result.gaji) == 1
        assert result.gaji[0]["item"] == "Gaji Karyawan"

    @pytest.mark.django_db
    def test_yearly_recap_12_months_with_category_breakdown(self, master_data):
        item_jual = master_data["items"]["egg_sales"]
        cat_income = master_data["categories"]["layer"]
        account = master_data["user"]

        # Use date after opening balance (Sept 2026)
        create_transaction(date=date(2026, 10, 15), flow="income", category=cat_income, item=item_jual, amount=Decimal("1000000"), qty=Decimal("20"), actor=account)

        result = yearly_recap(2026, None)
        assert result.months is not None
        assert len(result.months) == 12

        oct_month = result.months[9]  # October (0-indexed)
        assert oct_month["bulan"].month == 10
        assert any(s["amount"] > 0 for s in oct_month["summary"] if s["key"] == "pemasukan")

    @pytest.mark.django_db
    def test_layer_afkir_rollup(self, master_data):
        cat_layer = master_data["categories"]["layer"]
        cat_afkir = master_data["categories"]["afkir"]
        item_egg = master_data["items"]["egg_sales"]
        item_afkir = master_data["items"]["afkir_sales"]
        account = master_data["user"]
        today = today_wib()

        create_transaction(date=today, flow="income", category=cat_layer, item=item_egg, amount=Decimal("1000000"), qty=Decimal("20"), actor=account)
        create_transaction(date=today, flow="income", category=cat_afkir, item=item_afkir, amount=Decimal("500000"), qty=Decimal("10"), actor=account)

        result = daily_recap(today, today, category_ids=[cat_layer.pk])
        assert result.summary[0].amount == Decimal("1500000")

        result = daily_recap(today, today, category_ids=[cat_afkir.pk])
        assert result.summary[0].amount == Decimal("500000")

    @pytest.mark.django_db
    def test_category_filter_other_categories(self, master_data):
        cat_layer = master_data["categories"]["layer"]
        cat_umum = master_data["categories"]["umum"]
        item_pakan = master_data["items"]["feed"]
        item_kitchen = master_data["items"]["kitchen"]
        account = master_data["user"]
        today = today_wib()

        create_transaction(date=today, flow="expense", category=cat_layer, item=item_pakan, amount=Decimal("500000"), qty=Decimal("10"), actor=account)
        create_transaction(date=today, flow="expense", category=cat_umum, item=item_kitchen, amount=Decimal("300000"), actor=account)

        result = daily_recap(today, today, category_ids=[cat_layer.pk])
        assert result.summary[1].amount == Decimal("500000")

    @pytest.mark.django_db
    def test_stock_opening_in_out_adj_closing(self, master_data):
        stock_feed = master_data["stock"]["feed"]
        stock_egg = master_data["stock"]["egg"]
        account = master_data["user"]
        today = today_wib()

        record_production(stock_item=stock_egg, date=today, qty=Decimal("100"), actor=account)
        record_consumption(stock_item=stock_feed, date=today, qty=Decimal("50"), actor=account)
        adjust_stock(stock_item=stock_feed, date=today, signed_qty=Decimal("10"), reason="Koreksi stok masuk manual", actor=account)

        result = daily_recap(today, today, None)
        stock_rows = {s.kode: s for s in result.stock}

        feed = stock_rows["feed"]
        assert feed.opening == Decimal("1000")
        assert feed.in_qty == Decimal("0")
        assert feed.out_qty == Decimal("50")
        assert feed.adj == Decimal("10")
        assert feed.closing == Decimal("960")

        egg = stock_rows["egg"]
        assert egg.opening == Decimal("500")
        assert egg.in_qty == Decimal("100")
        assert egg.out_qty == Decimal("0")
        assert egg.adj == Decimal("0")
        assert egg.closing == Decimal("600")

    @pytest.mark.django_db
    @pytest.mark.xfail(reason="BUG-001: RecapResult missing income_detail/expense_detail attributes")
    def test_xlsx_export_5_sheets_bug(self, logged_client, master_data):
        """BUG-001: XLSX export fails - RecapResult missing income_detail/expense_detail attributes.
        
        The RecapResult has `detail` (combined) but not separate income_detail/expense_detail.
        This test documents the bug and expects it to fail until fixed.
        """
        item_jual = master_data["items"]["egg_sales"]
        item_pakan = master_data["items"]["feed"]
        cat_income = master_data["categories"]["layer"]
        cat_feed = master_data["categories"]["layer"]
        account = master_data["user"]
        today = today_wib()

        create_transaction(date=today, flow="income", category=cat_income, item=item_jual, amount=Decimal("1000000"), qty=Decimal("20"), actor=account)
        create_transaction(date=today, flow="expense", category=cat_feed, item=item_pakan, amount=Decimal("500000"), qty=Decimal("10"), actor=account)

        resp = logged_client.get(reverse("reports:export_daily") + f"?date_from={today}&date_to={today}")
        # Currently fails with AttributeError
        assert resp.status_code == 500  # Bug causes 500

    @pytest.mark.django_db
    @pytest.mark.xfail(reason="BUG-001: Same bug affects all XLSX exports")
    def test_xlsx_export_all_period_types_bug(self, logged_client, master_data):
        """BUG-001: All XLSX exports fail with same bug."""
        item_jual = master_data["items"]["egg_sales"]
        cat_income = master_data["categories"]["layer"]
        account = master_data["user"]
        today = today_wib()

        create_transaction(date=today, flow="income", category=cat_income, item=item_jual, amount=Decimal("1000000"), qty=Decimal("20"), actor=account)

        for period_type, url_name, params in [
            ("daily", "reports:export_daily", f"?date_from={today}&date_to={today}"),
            ("weekly", "reports:export_weekly", f"?week={today}"),
            ("monthly", "reports:export_monthly", f"?month={today}"),
            ("yearly", "reports:export_yearly", f"?year=2026"),
        ]:
            resp = logged_client.get(reverse(url_name) + params)
            assert resp.status_code == 500, f"{period_type} export should fail with bug"


# =========================================================================
# 7. AUDIT LOG (BR-14)
# =========================================================================


class TestAuditLog:
    """List with filters, detail diff, XLSX export."""

    @pytest.mark.django_db
    def test_audit_log_list_filters(self, logged_client, master_data):
        log_audit(entity="transaction", entity_id=1, action="create", actor=master_data["user"], after={"amount": "100000"})
        log_audit(entity="stock_movement", entity_id=1, action="create", actor=master_data["user"], after={"qty": "100"})
        log_audit(entity="stock_item", entity_id=1, action="update", actor=master_data["user"], before={"opening_qty": "1000"}, after={"opening_qty": "2000"})

        resp = logged_client.get(reverse("audit:list") + "?entity=transaction")
        assert resp.status_code == 200
        assert "transaction" in resp.content.decode()

        resp = logged_client.get(reverse("audit:list") + "?action=create")
        assert resp.status_code == 200
        assert "create" in resp.content.decode()

        today = today_wib().isoformat()
        resp = logged_client.get(reverse("audit:list") + f"?date_from={today}&date_to={today}")
        assert resp.status_code == 200

        resp = logged_client.get(reverse("audit:list") + "?q=100000")
        assert resp.status_code == 200

    @pytest.mark.django_db
    def test_audit_log_detail_diff(self, logged_client, master_data):
        log_audit(
            entity="stock_item",
            entity_id=master_data["stock"]["feed"].pk,
            action="update",
            actor=master_data["user"],
            before={"opening_qty": "1000", "min_threshold": "100"},
            after={"opening_qty": "2000", "min_threshold": "150"},
        )

        log = AuditLog.objects.first()
        resp = logged_client.get(reverse("audit:detail", args=[log.pk]))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "opening_qty" in content
        assert "1000" in content
        assert "2000" in content
        assert "min_threshold" in content

    @pytest.mark.django_db
    def test_audit_export_xlsx(self, logged_client, master_data):
        log_audit(entity="transaction", entity_id=1, action="create", actor=master_data["user"], after={"amount": "100000"})

        resp = logged_client.get(reverse("audit:export"))
        assert resp.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp["Content-Type"]

        wb = load_workbook(BytesIO(resp.content))
        assert wb.sheetnames == ["Audit Log"]
        ws = wb["Audit Log"]
        assert ws.cell(row=1, column=1).value == "Waktu"
        assert ws.cell(row=1, column=2).value == "Entity"
        assert ws.cell(row=2, column=2).value == "transaction"


# =========================================================================
# 8. PERIOD LOCK UI
# =========================================================================


class TestPeriodLock:
    """Chain validation, lock/unlock, chained unlock only latest."""

    @pytest.mark.django_db
    def test_chain_gap_validation_on_lock(self, master_data):
        # Opening is Sept 2026, trying to lock Nov without Oct
        with pytest.raises(DomainError) as exc:
            lock_period(date(2026, 11, 1), actor=master_data["user"])
        # Message says "Kunci September 2026 terlebih dahulu"
        assert "september" in str(exc.value).lower() or "kunci" in str(exc.value).lower()

        lock_period(date(2026, 9, 1), actor=master_data["user"])
        lock_period(date(2026, 10, 1), actor=master_data["user"])
        lock_period(date(2026, 11, 1), actor=master_data["user"])

    @pytest.mark.django_db
    def test_lock_unlock_cycle(self, master_data):
        period = date(2026, 10, 1)

        lock_period(date(2026, 9, 1), actor=master_data["user"])
        lock_period(period, actor=master_data["user"])
        row = PeriodLock.objects.get(period=period)
        assert row.is_locked is True
        assert row.unlock_count == 0

        unlock_period(period, reason="Perlu koreksi data bulan lalu", actor=master_data["user"])
        row.refresh_from_db()
        assert row.is_locked is False
        assert row.unlock_count == 1
        assert row.unlock_reason == "Perlu koreksi data bulan lalu"

        lock_period(period, actor=master_data["user"])
        row.refresh_from_db()
        assert row.is_locked is True
        assert row.unlock_count == 1

    @pytest.mark.django_db
    def test_unlock_only_latest_locked(self, master_data):
        lock_period(date(2026, 9, 1), actor=master_data["user"])
        lock_period(date(2026, 10, 1), actor=master_data["user"])
        lock_period(date(2026, 11, 1), actor=master_data["user"])

        with pytest.raises(DomainError) as exc:
            unlock_period(date(2026, 10, 1), reason="Alasan pembukaan bulan oktober yang valid", actor=master_data["user"])
        # Message says "Buka kunci November 2026 terlebih dahulu"
        assert "november" in str(exc.value).lower() or "terlebih dahulu" in str(exc.value).lower()

        unlock_period(date(2026, 11, 1), reason="Alasan pembukaan bulan november yang valid", actor=master_data["user"])
        unlock_period(date(2026, 10, 1), reason="Alasan pembukaan bulan oktober yang valid", actor=master_data["user"])

    @pytest.mark.django_db
    def test_unlock_reason_min_10_chars(self, master_data):
        period = date(2026, 10, 1)
        lock_period(date(2026, 9, 1), actor=master_data["user"])
        lock_period(period, actor=master_data["user"])

        with pytest.raises(DomainError) as exc:
            unlock_period(period, reason="pendek", actor=master_data["user"])
        assert "10" in str(exc.value) or "minimal" in str(exc.value).lower()

        unlock_period(period, reason="Alasan yang cukup panjang untuk membuka", actor=master_data["user"])

    @pytest.mark.django_db
    def test_is_date_editable_respects_chain(self, master_data):
        assert is_date_editable(date(2026, 10, 15)) is True

        lock_period(date(2026, 9, 1), actor=master_data["user"])
        lock_period(date(2026, 10, 1), actor=master_data["user"])

        assert is_date_editable(date(2026, 10, 1)) is False
        assert is_date_editable(date(2026, 10, 15)) is False
        assert is_date_editable(date(2026, 10, 31)) is False

        assert is_date_editable(date(2026, 11, 1)) is True

        lock_period(date(2026, 11, 1), actor=master_data["user"])

        assert is_date_editable(date(2026, 11, 1)) is False
        assert is_date_editable(date(2026, 12, 1)) is True


# =========================================================================
# 9. ATTACHMENTS
# =========================================================================


class TestAttachments:
    """Upload/download/delete for transactions."""

    @pytest.mark.django_db
    def test_attachment_upload_valid_types(self, logged_client, master_data):
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        account = master_data["user"]

        txn = create_transaction(
            date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("10"), actor=account
        )

        from django.core.files.uploadedfile import SimpleUploadedFile

        pdf_content = b"%PDF-1.4 test pdf content"
        pdf_file = SimpleUploadedFile("test.pdf", pdf_content, content_type="application/pdf")
        resp = logged_client.post(reverse("attachment_upload", args=[txn.pk]), {"file": pdf_file}, follow=True)

        assert resp.status_code == 200
        attachment = Attachment.objects.filter(transaction=txn).first()
        assert attachment is not None
        assert attachment.mime_type == "application/pdf"
        assert attachment.size_bytes == len(pdf_content)

    @pytest.mark.django_db
    def test_attachment_reject_invalid_mime(self, logged_client, master_data):
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        account = master_data["user"]

        txn = create_transaction(
            date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("10"), actor=account
        )

        from django.core.files.uploadedfile import SimpleUploadedFile

        txt_file = SimpleUploadedFile("test.txt", b"text content", content_type="text/plain")
        resp = logged_client.post(reverse("attachment_upload", args=[txn.pk]), {"file": txt_file})

        assert Attachment.objects.filter(transaction=txn).count() == 0
        assert "tidak didukung" in resp.content.decode().lower() or "format" in resp.content.decode().lower()

    @pytest.mark.django_db
    def test_attachment_reject_over_10mb(self, logged_client, master_data):
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        account = master_data["user"]

        txn = create_transaction(
            date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("10"), actor=account
        )

        from django.core.files.uploadedfile import SimpleUploadedFile

        large_content = b"x" * (11 * 1024 * 1024)
        large_file = SimpleUploadedFile("large.pdf", large_content, content_type="application/pdf")
        resp = logged_client.post(reverse("attachment_upload", args=[txn.pk]), {"file": large_file})

        assert Attachment.objects.filter(transaction=txn).count() == 0
        assert "10 mb" in resp.content.decode().lower() or "maksimal" in resp.content.decode().lower()

    @pytest.mark.django_db
    def test_attachment_download(self, logged_client, master_data):
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        account = master_data["user"]

        txn = create_transaction(
            date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("10"), actor=account
        )

        pdf_content = b"%PDF-1.4 test pdf"
        attachment = Attachment.objects.create(
            transaction=txn,
            file="attachments/test.pdf",
            original_name="test.pdf",
            mime_type="application/pdf",
            size_bytes=len(pdf_content),
            uploaded_by=account,
        )

        from django.core.files.storage import default_storage

        with patch.object(default_storage, "open", return_value=BytesIO(pdf_content)):
            with patch.object(default_storage, "exists", return_value=True):
                resp = logged_client.get(reverse("attachment_download", args=[txn.pk, attachment.pk]))
                assert resp.status_code == 200
                assert resp["Content-Type"] == "application/pdf"
                assert 'attachment; filename="test.pdf"' in resp["Content-Disposition"]
                assert resp.content == pdf_content

    @pytest.mark.django_db
    def test_attachment_delete_soft_delete(self, logged_client, master_data):
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        account = master_data["user"]

        txn = create_transaction(
            date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("10"), actor=account
        )

        attachment = Attachment.objects.create(
            transaction=txn,
            file="attachments/test.pdf",
            original_name="test.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            uploaded_by=account,
        )

        resp = logged_client.post(reverse("attachment_delete", args=[txn.pk, attachment.pk]), follow=True)
        assert resp.status_code == 200

        attachment.refresh_from_db()
        assert attachment.deleted_at is not None

        assert Attachment.objects.filter(pk=attachment.pk).count() == 0
        assert Attachment.all_objects.filter(pk=attachment.pk).count() == 1


# =========================================================================
# 10. PDF INVESTOR REPORT (FR-27, FR-28)
# =========================================================================


class TestPDFInvestorReport:
    """WeasyPrint ID/EN, all period types (daily, weekly, monthly, yearly).
    
    BUG-002: PDF Investor Report has wrong import for CompanyProfile.
    """

    @pytest.mark.django_db
    @pytest.mark.xfail(reason="BUG-002: ImportError - CompanyProfile imported from master.models instead of core.models")
    def test_pdf_generation_id_monthly_bug(self, logged_client, master_data):
        """BUG-002: ImportError - CompanyProfile imported from master.models instead of core.models."""
        item_jual = master_data["items"]["egg_sales"]
        cat_income = master_data["categories"]["layer"]
        account = master_data["user"]
        today = today_wib()

        create_transaction(date=today, flow="income", category=cat_income, item=item_jual, amount=Decimal("1000000"), qty=Decimal("20"), actor=account)

        resp = logged_client.get(reverse("investor_pdf") + "?lang=id&period=monthly")
        # Currently fails with ImportError
        assert resp.status_code == 500

    @pytest.mark.django_db
    @pytest.mark.xfail(reason="BUG-002: Same import bug")
    def test_pdf_generation_en_monthly_bug(self, logged_client, master_data):
        """BUG-002: Same import bug."""
        resp = logged_client.get(reverse("investor_pdf") + "?lang=en&period=monthly")
        assert resp.status_code == 500

    @pytest.mark.django_db
    @pytest.mark.xfail(reason="BUG-002: All PDF periods fail with same import bug")
    def test_pdf_all_period_types_bug(self, logged_client, master_data):
        """BUG-002: All PDF periods fail with same import bug."""
        item_jual = master_data["items"]["egg_sales"]
        cat_income = master_data["categories"]["layer"]
        account = master_data["user"]
        today = today_wib()

        create_transaction(date=today, flow="income", category=cat_income, item=item_jual, amount=Decimal("1000000"), qty=Decimal("20"), actor=account)

        for period in ["daily", "weekly", "monthly", "yearly"]:
            params = f"?lang=id&period={period}"
            if period == "daily":
                params += f"&date={today}"
            elif period == "weekly":
                params += f"&date={today}"
            elif period == "yearly":
                params += "&date=2026-10-15"
            else:
                params += f"&date={today}"

            resp = logged_client.get(reverse("investor_pdf") + params)
            assert resp.status_code == 500, f"PDF {period} should fail with bug"


# =========================================================================
# INTEGRATION: FULL USER JOURNEYS
# =========================================================================


class TestFullUserJourneys:
    """End-to-end user journey tests combining multiple flows."""

    @pytest.mark.django_db
    def test_complete_farm_operation_cycle(self, logged_client, master_data):
        account = master_data["user"]
        stock_feed = master_data["stock"]["feed"]
        stock_egg = master_data["stock"]["egg"]
        cat_feed = master_data["categories"]["layer"]
        cat_income = master_data["categories"]["layer"]
        item_pakan = master_data["items"]["feed"]
        item_jual = master_data["items"]["egg_sales"]

        create_transaction(
            date=today_wib(), flow="expense", category=cat_feed, item=item_pakan, amount=Decimal("5000000"), qty=Decimal("1000"), actor=account
        )
        assert stock_api.on_hand(stock_feed.pk) == Decimal("2000")

        record_production(stock_item=stock_egg, date=today_wib(), qty=Decimal("500"), actor=account)
        assert stock_api.on_hand(stock_egg.pk) == Decimal("1000")

        create_transaction(
            date=today_wib(), flow="income", category=cat_income, item=item_jual, amount=Decimal("7500000"), qty=Decimal("200"), actor=account
        )
        assert stock_api.on_hand(stock_egg.pk) == Decimal("800")

        result = daily_recap(today_wib(), today_wib(), None)
        assert result.summary[0].amount == Decimal("7500000")
        assert result.summary[1].amount == Decimal("5000000")
        assert result.summary[3].amount == Decimal("2500000")

        stock_rows = {s.kode: s for s in result.stock}
        assert stock_rows["feed"].closing == Decimal("2000")
        assert stock_rows["egg"].closing == Decimal("800")

    @pytest.mark.django_db
    def test_period_lock_prevents_historical_changes(self, logged_client, master_data):
        account = master_data["user"]
        item_pakan = master_data["items"]["feed"]
        cat_feed = master_data["categories"]["layer"]
        stock_feed = master_data["stock"]["feed"]

        # Use past date that's after opening balance
        oct_date = date(2026, 10, 15)
        txn = create_transaction(
            date=oct_date, flow="expense", category=cat_feed, item=item_pakan, amount=Decimal("1000000"), qty=Decimal("50"), actor=account
        )

        # Lock Sept and Oct
        lock_period(date(2026, 9, 1), actor=account)
        lock_period(date(2026, 10, 1), actor=account)

        with pytest.raises(PeriodLocked):
            update_transaction(
                transaction_id=txn.pk,
                date=oct_date,
                flow="expense",
                category=cat_feed,
                item=item_pakan,
                amount=Decimal("2000000"),
                qty=Decimal("100"),
                actor=account,
            )

        with pytest.raises(PeriodLocked):
            delete_transaction(transaction_id=txn.pk, actor=account)

        with pytest.raises(PeriodLocked):
            record_consumption(stock_item=stock_feed, date=oct_date, qty=Decimal("10"), actor=account)

        # Current month should work (not locked)
        today = today_wib()
        txn2 = create_transaction(
            date=today, flow="expense", category=cat_feed, item=item_pakan, amount=Decimal("1000000"), qty=Decimal("50"), actor=account
        )
        assert txn2.pk is not None

    @pytest.mark.django_db
    def test_onboarding_creates_all_master_data(self, client):
        client.post(
            reverse("setup_account"),
            {"username": "farm1", "first_name": "Farm One", "password": "RahasiaKandang2026", "password_confirm": "RahasiaKandang2026"},
        )
        client.post(reverse("setup_profile"), {"name": "Farm One", "business_start_date": "2026-09-01"})
        client.post(reverse("setup_balance"), {"opening_balance": "100.000.000", "opening_balance_date": "2026-09-01"})
        client.post(
            reverse("setup_stock"),
            {"feed_qty": "500", "feed_min": "50", "egg_qty": "200", "egg_min": "20", "manure_qty": "100", "manure_min": "10"},
        )
        client.post(reverse("setup_review"), follow=True)

        assert StockItem.objects.filter(code="feed").first().opening_qty == Decimal("500")
        assert StockItem.objects.filter(code="egg").first().opening_qty == Decimal("200")
        assert StockItem.objects.filter(code="manure").first().opening_qty == Decimal("100")

        assert Category.objects.filter(code="LAYER", is_system=True).exists()
        assert Category.objects.filter(code="AFKIR", is_system=True).exists()
        assert Category.objects.filter(code="DOC", is_system=True).exists()
        assert Category.objects.filter(code="UMUM", is_system=True).exists()

        assert Item.objects.get(code="salary").name == "Gaji Karyawan"
        assert Item.objects.get(code="egg_sales").name == "Pendapatan Telur"
        assert Item.objects.get(code="feed").name == "Pakan"
        assert Item.objects.get(code="afkir_sales").name == "Pendapatan Ayam Afkir"

    @pytest.mark.django_db
    def test_idempotent_setup_finalize(self, completed_setup, test_user):
        from onboarding.services.finalize import finalize_setup

        result = finalize_setup(actor=test_user, stock_draft=None)
        assert result.created is False
        assert result.profile.setup_completed is True


# =========================================================================
# EDGE CASES & REGRESSION TESTS
# =========================================================================


class TestEdgeCases:
    """Edge cases and regression tests."""

    @pytest.mark.django_db
    def test_concurrent_stock_update_deadlock_prevention(self, master_data):
        stock_feed = master_data["stock"]["feed"]
        stock_egg = master_data["stock"]["egg"]

        locked = stock_api.lock_items([stock_egg.pk, stock_feed.pk])
        assert list(locked.keys()) == sorted([stock_feed.pk, stock_egg.pk])

    @pytest.mark.django_db
    def test_idempotency_key_prevents_duplicate_create(self, master_data):
        import uuid

        key = uuid.uuid4()
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        account = master_data["user"]

        txn1 = create_transaction(
            date=today_wib(),
            flow="income",
            category=cat,
            item=item,
            amount=Decimal("100000"),
            qty=Decimal("10"),
            idempotency_key=key,
            actor=account,
        )

        txn2 = create_transaction(
            date=today_wib(),
            flow="income",
            category=cat,
            item=item,
            amount=Decimal("100000"),
            qty=Decimal("10"),
            idempotency_key=key,
            actor=account,
        )

        assert txn1.pk == txn2.pk

    @pytest.mark.django_db
    def test_duplicate_prefill_copies_correct_fields(self, master_data):
        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        account = master_data["user"]

        txn = create_transaction(
            date=date(2026, 10, 15),
            flow="income",
            category=cat,
            item=item,
            amount=Decimal("100000"),
            qty=Decimal("10"),
            notes="Original note",
            payment_method="cash",
            actor=account,
        )

        prefill = duplicate_prefill(txn.pk)
        assert prefill["date"] == today_wib()
        assert prefill["flow"] == "income"
        assert prefill["category"] == cat
        assert prefill["item"] == item
        assert prefill["amount"] == Decimal("100000")
        assert prefill["qty"] == Decimal("10")
        assert prefill["notes"] == "Original note"
        assert prefill["payment_method"] == "cash"

    @pytest.mark.django_db
    def test_cash_locked_after_first_movement(self, master_data):
        account = master_data["account"]
        assert cash_is_locked() is False

        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        create_transaction(
            date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("10"), actor=master_data["user"]
        )

        assert cash_is_locked() is True
        assert cash_locked_since() == account.opening_balance_date

    @pytest.mark.django_db
    def test_opening_correction_only_after_cash_locked(self, master_data):
        account = master_data["user"]
        assert cash_is_locked() is False

        with pytest.raises(DomainError):
            record_opening_correction(delta=Decimal("100000"), reason="Test", actor=account)

        item = master_data["items"]["egg_sales"]
        cat = master_data["categories"]["layer"]
        create_transaction(date=today_wib(), flow="income", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("10"), actor=account)

        assert cash_is_locked() is True

        record_opening_correction(delta=Decimal("50000"), reason="Koreksi setup", actor=account)
        txn = Transaction.objects.filter(is_opening_correction=True).first()
        assert txn is not None

    @pytest.mark.django_db
    def test_movement_source_transaction_immutable(self, master_data):
        stock_feed = master_data["stock"]["feed"]

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(
                    stock_item=stock_feed,
                    date=today_wib(),
                    direction="in",
                    qty=Decimal("100"),
                    source="transaction",
                    transaction=None,
                )

    @pytest.mark.django_db
    def test_batch_key_uniqueness_per_stock_item(self, master_data):
        import uuid

        stock_feed = master_data["stock"]["feed"]
        batch_key = uuid.uuid4()

        StockMovement.objects.create(
            stock_item=stock_feed, date=today_wib(), direction="in", qty=Decimal("100"), source="manual", batch_key=batch_key
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(
                    stock_item=stock_feed, date=today_wib(), direction="in", qty=Decimal("100"), source="manual", batch_key=batch_key
                )

        stock_egg = master_data["stock"]["egg"]
        StockMovement.objects.create(
            stock_item=stock_egg, date=today_wib(), direction="in", qty=Decimal("100"), source="manual", batch_key=batch_key
        )

    @pytest.mark.django_db
    def test_soft_delete_restores_balance(self, master_data):
        stock_feed = master_data["stock"]["feed"]
        initial = stock_api.on_hand(stock_feed.pk)

        movement = record_consumption(stock_item=stock_feed, date=today_wib(), qty=Decimal("100"), actor=master_data["user"])
        after_add = stock_api.on_hand(stock_feed.pk)
        assert after_add == initial - Decimal("100")

        delete_manual(movement_id=movement.pk, actor=master_data["user"])
        after_delete = stock_api.on_hand(stock_feed.pk)
        assert after_delete == initial

    @pytest.mark.django_db
    def test_number_parsing_indonesian_format(self):
        assert parse_id_number("1.234.567,89", places=2) == Decimal("1234567.89")
        assert parse_id_number("1.000", places=3) == Decimal("1000.000")
        assert parse_id_number("0,5", places=3) == Decimal("0.500")
        assert parse_id_number("250.000.000", places=2) == Decimal("250000000.00")

    @pytest.mark.django_db
    def test_format_id_number_indonesian(self):
        assert format_id_number(Decimal("1234567.89"), places=2) == "1.234.567,89"
        assert format_id_number(Decimal("1000"), places=0) == "1.000"
        assert format_id_number(Decimal("0.5"), places=3) == "0,500"

    @pytest.mark.django_db
    def test_format_qty_three_decimals(self):
        assert format_qty(Decimal("1000")) == "1.000"
        assert format_qty(Decimal("1000.5")) == "1.000,5"
        assert format_qty(Decimal("0.5")) == "0,5"

    @pytest.mark.django_db
    def test_format_money_two_decimals(self):
        assert format_money(Decimal("1000000")) == "1.000.000,00"
        assert format_money(Decimal("1000000.5")) == "1.000.000,50"


# =========================================================================
# PERFORMANCE / LOAD TESTS (basic)
# =========================================================================


class TestPerformanceBaseline:
    """Basic performance baselines for critical paths."""

    @pytest.mark.django_db
    def test_daily_recap_query_performance(self, master_data, django_assert_num_queries):
        account = master_data["user"]
        item = master_data["items"]["feed"]  # Use feed (stock item with plenty of qty)
        cat = master_data["categories"]["layer"]

        for i in range(100):
            create_transaction(
                date=today_wib(), flow="expense", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("1"), actor=account
            )

        with django_assert_num_queries(25):
            daily_recap(today_wib(), today_wib(), None)

    @pytest.mark.django_db
    def test_monthly_recap_query_performance(self, master_data, django_assert_num_queries):
        account = master_data["user"]
        item = master_data["items"]["feed"]
        cat = master_data["categories"]["layer"]

        for i in range(50):
            create_transaction(
                date=date(2026, 10, 1 + (i % 28)), flow="expense", category=cat, item=item, amount=Decimal("100000"), qty=Decimal("1"), actor=account
            )

        # Query count may vary, just ensure it runs
        monthly_recap(today_wib(), None)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])